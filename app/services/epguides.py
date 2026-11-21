"""
External data fetching for TV show information.

This module handles all external API calls:
- epguides.com: Master show list, episode CSV data, IMDB IDs
- TVMaze API: Episode data (fallback), summaries, posters

Data fetching strategy for episodes:
1. Primary: Fetch from epguides.com (established data source)
2. Fallback: Fetch from TVMaze API (when epguides is unreachable)

All functions are async and use Redis caching for performance.
"""

import csv
import io
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.cache import cache, mark_upstream_success
from app.core.config import settings
from app.core.constants import CACHE_TTL_SHOWS_METADATA_SECONDS, DATE_FORMATS, EPGUIDES_BASE_URL
from app.core.metrics import observe_upstream_response_age, record_upstream_request

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EpguidesBot/1.0; +https://epguides.frecar.no)",
}


def parse_date_string(date_string: str) -> datetime | None:
    """
    Parse date string in various formats.

    Supports multiple formats common in epguides data:
    - "20 Jan 08" (%d %b %y)
    - "20/Jan/08" (%d/%b/%y)
    - "2008-01-20" (%Y-%m-%d)

    Automatically corrects century for old shows (e.g., "08" -> 2008, not 2108).

    Args:
        date_string: Date string to parse.

    Returns:
        Parsed datetime or None if unparsable.
    """
    if not date_string:
        return None

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(date_string, fmt).replace(tzinfo=UTC)
            if parsed.year > datetime.now(UTC).year + 2:
                parsed = parsed.replace(year=parsed.year - 100)
            return parsed
        except ValueError:
            continue

    return None


def _clean_unicode_text(response: httpx.Response) -> str:
    """
    Extract and clean text from HTTP response.

    Handles encoding issues and Unicode replacement characters.
    """
    response.encoding = response.encoding or "utf-8"
    text = response.text

    if "\ufffd" in text:
        text = response.content.decode("utf-8", errors="replace")
        text = text.replace("\ufffd", "")

    return text


async def _fetch_url(url: str) -> httpx.Response | None:
    """
    Fetch URL with standard timeout and error handling.

    Returns None on any error (logged with specific error type).
    Records epguides upstream metrics on every call.
    """
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=settings.HTTP_TIMEOUT_SECONDS, headers=_DEFAULT_HEADERS
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            observe_upstream_response_age("epguides", time.monotonic() - start)
            record_upstream_request("epguides", "success")
            await mark_upstream_success("epguides")
            return response
    except httpx.TimeoutException:
        logger.warning("Timeout fetching %s after %ss", url, settings.HTTP_TIMEOUT_SECONDS)
        record_upstream_request("epguides", "timeout")
        return None
    except httpx.ConnectError:
        logger.warning("Connection failed for %s (host unreachable or DNS failure)", url)
        record_upstream_request("epguides", "http_error")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d from %s: %s", e.response.status_code, url, e)
        record_upstream_request("epguides", "http_error")
        return None
    except Exception as e:
        logger.error("Unexpected error fetching %s: %s: %s", url, type(e).__name__, e)
        record_upstream_request("epguides", "http_error")
        return None


_HTML_LEADING_MARKERS = ("<!doctype", "<html", "<head", "<meta", "<?xml", "<!--")


def _looks_like_html(text: str) -> bool:
    """
    Return True if ``text`` is an HTML document body rather than CSV.

    Only the leading bytes are inspected (after stripping a BOM and leading
    whitespace), so a legitimate CSV cell that merely *contains* angle
    brackets — e.g. an episode title like ``"3 < 4"`` — never false-positives;
    real CSV starts with a number/header token, not a markup marker.
    """
    head = text.lstrip("﻿").lstrip()[:512].lower()
    return head.startswith(_HTML_LEADING_MARKERS)


async def fetch_csv(url: str) -> list[list[str]]:
    """
    Fetch and parse CSV from URL.

    Args:
        url: URL to fetch CSV from.

    Returns:
        List of rows (each row is a list of strings).
        Returns empty list on error.

    Empty / whitespace-only response bodies are treated as upstream-unavailable:
    when epguides.com's CSV export endpoint is sick it sometimes returns HTTP 200
    with a zero-byte body instead of a proper error status. Detect that here so
    the caller falls through to the TVMaze fallback rather than treating an
    empty CSV as a valid (zero-episodes) result. Recorded as the
    ``empty_response`` outcome on the upstream-request counter for observability.

    HTML bodies masquerading as CSV (HTTP 200 returning the show page or an
    error page) are likewise treated as upstream-unavailable (#298): without
    this guard ``csv.reader`` parses the markup line-by-line and HTML fragments
    leak into episode fields. Recorded as the ``parse_error`` outcome.
    """
    response = await _fetch_url(url)
    if not response:
        return []

    text = _clean_unicode_text(response)

    if not text.strip():
        logger.warning(
            "Empty CSV body from %s (HTTP %d) — treating as upstream-unavailable",
            url,
            response.status_code,
        )
        record_upstream_request("epguides", "empty_response")
        return []

    if _looks_like_html(text):
        logger.warning(
            "HTML body where CSV expected from %s (HTTP %d) — treating as upstream-unavailable",
            url,
            response.status_code,
        )
        record_upstream_request("epguides", "parse_error")
        return []

    try:
        return list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as e:
        logger.error("CSV parse error for %s: %s", url, e)
        record_upstream_request("epguides", "parse_error")
        return []


@cache(ttl_seconds=CACHE_TTL_SHOWS_METADATA_SECONDS, key_prefix="shows_metadata")
async def get_all_shows_metadata() -> list[dict[str, str]]:
    """
    Fetch master list of all shows from epguides.

    Returns list of dictionaries with show metadata.
    Cached for 30 days (new shows added infrequently).
    """
    url = f"{EPGUIDES_BASE_URL}/common/allshows.txt"
    response = await _fetch_url(url)

    if not response or response.status_code != 200:
        return []

    text = _clean_unicode_text(response)
    return list(csv.DictReader(io.StringIO(text, newline="")))


_TVRAGE_COLUMNS = {"season": 1, "number": 2, "release_date": 4, "title": 5}
_TVMAZE_COLUMNS = {"season": 1, "number": 2, "release_date": 3, "title": 4}

_TVMAZE_API_URL = "https://api.tvmaze.com"
_TVMAZE_API_HOST = httpx.URL(_TVMAZE_API_URL).host


async def _tvmaze_get(url: str, *, follow_redirects: bool = False, **kwargs: Any) -> httpx.Response | None:
    """GET a TVMaze API endpoint with metric recording.

    Returns the response on HTTP 200, None on any error or non-200 status.
    Records tvmaze upstream request and latency metrics.

    ``follow_redirects`` is opt-in for endpoints TVMaze documents as
    redirecting (``/lookup/shows`` answers a hit with a 301 to
    ``/shows/<id>``). A redirect that leaves the TVMaze API host is treated
    as an error rather than trusted.
    """
    if follow_redirects:
        kwargs["follow_redirects"] = True
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, **kwargs)
            if follow_redirects and (response.url.scheme != "https" or response.url.host != _TVMAZE_API_HOST):
                record_upstream_request("tvmaze", "http_error")
                logger.warning("TVMaze %s redirected off the API origin to %s", url, response.url)
                return None
            if response.status_code != 200:
                record_upstream_request("tvmaze", "http_error")
                logger.debug("TVMaze %s returned HTTP %d", url, response.status_code)
                return None
            observe_upstream_response_age("tvmaze", time.monotonic() - start)
            record_upstream_request("tvmaze", "success")
            await mark_upstream_success("tvmaze")
            return response
    except httpx.TimeoutException:
        logger.warning("Timeout fetching TVMaze %s", url)
        record_upstream_request("tvmaze", "timeout")
        return None
    except Exception as e:
        logger.warning("TVMaze fetch error for %s: %s", url, e)
        record_upstream_request("tvmaze", "http_error")
        return None


async def _search_tvmaze_by_title(title: str) -> dict[str, Any] | None:
    """
    Search TVMaze for a show by its title.

    Uses the single-search endpoint which returns the best match.

    Args:
        title: Show title (e.g., "Shark Tank", "Game of Thrones").

    Returns:
        TVMaze show data dict or None if not found.
    """
    if not title:
        return None

    response = await _tvmaze_get(f"{_TVMAZE_API_URL}/singlesearch/shows", params={"q": title})
    if not response:
        return None
    try:
        result: dict[str, Any] = response.json()
        return result
    except Exception as e:
        logger.warning("TVMaze search parse error for '%s': %s", title, e)
        return None


async def lookup_tvmaze_by_imdb(imdb_id: str) -> dict[str, Any] | None:
    """
    Look up a TVMaze show by its IMDB ID.

    Uses the documented TVMaze /lookup/shows?imdb=<id> endpoint, which is
    indexed and returns the matching show directly — no fuzzy title match.
    Closes the user-reported gap (#229): title search can hit the remake
    instead of the original; IMDB ID is unambiguous.

    TVMaze answers a hit with ``301 Location: /shows/<tvmaze_id>`` rather
    than a 200 body, so the redirect must be followed. Before #474 it was
    not, and every hit was misread as a miss.

    Args:
        imdb_id: IMDB show identifier, e.g. "tt0903747" (Breaking Bad).
            Format is validated upstream of this helper.

    Returns:
        TVMaze show data dict on a hit, or None if TVMaze has no match
        (404) or the lookup failed (timeout, parse, etc).
    """
    if not imdb_id:
        return None

    response = await _tvmaze_get(f"{_TVMAZE_API_URL}/lookup/shows", params={"imdb": imdb_id}, follow_redirects=True)
    if not response:
        return None
    try:
        result: dict[str, Any] = response.json()
        return result
    except Exception as e:
        logger.warning("TVMaze imdb lookup parse error for '%s': %s", imdb_id, e)
        return None


async def _fetch_tvmaze_episodes(maze_id: str) -> list[dict[str, Any]]:
    """
    Fetch all episodes for a show from TVMaze.

    Returns episodes in the same format as epguides CSV parsing,
    but with summaries and poster URLs included.

    Args:
        maze_id: TVMaze show ID.

    Returns:
        List of episode dicts with season, number, title, release_date, summary, poster_url.
    """
    response = await _tvmaze_get(f"{_TVMAZE_API_URL}/shows/{maze_id}/episodes")
    if not response:
        return []

    try:
        tvmaze_episodes = response.json()
        episodes: list[dict[str, Any]] = []

        for ep in tvmaze_episodes:
            season = ep.get("season")
            number = ep.get("number")
            name = ep.get("name")
            airdate = ep.get("airdate")

            if not all([season, number, name, airdate]):
                continue

            summary = ep.get("summary") or ""
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary).strip()

            image = ep.get("image")
            poster_url = ""
            if image:
                poster_url = image.get("original") or image.get("medium") or ""

            episodes.append(
                {
                    "season": str(season),
                    "number": str(number),
                    "title": name,
                    "release_date": airdate,
                    "summary": summary,
                    "poster_url": poster_url,
                }
            )

        return episodes

    except Exception as e:
        logger.warning("TVMaze episodes parse error for maze=%s: %s", maze_id, e)
        return []


async def _get_show_title(show_id: str) -> str | None:
    """
    Get the actual show title for a show ID.

    Strategy:
    1. Look up title from cached show metadata (most accurate)
    2. Fall back to converting show_id to searchable format

    Args:
        show_id: Epguides show identifier (e.g., "sharktank", "GameOfThrones").

    Returns:
        Show title (e.g., "Shark Tank") or converted show_id.
    """
    metadata = await get_all_shows_metadata()
    show_id_lower = show_id.lower()

    for show in metadata:
        directory = show.get("directory", "").lower()
        if directory == show_id_lower:
            title = show.get("title")
            if title:
                return title

    return _convert_show_id_to_title(show_id)


def _convert_show_id_to_title(show_id: str) -> str:
    """
    Convert a show ID to a searchable title.

    Handles common patterns:
    - CamelCase: "SharkTank" -> "Shark Tank"
    - Lowercase: "sharktank" -> "shark tank" (using common word detection)

    TVMaze search is fuzzy, so approximate titles usually work.

    Args:
        show_id: Epguides show identifier.

    Returns:
        A search-friendly version of the show ID.
    """
    title = re.sub(r"([a-z])([A-Z])", r"\1 \2", show_id)

    if " " not in title and title.islower():
        title = _add_word_boundaries(title)

    return title.strip()


def _add_word_boundaries(text: str) -> str:
    """
    Add spaces at likely word boundaries in a lowercase string.

    Uses a list of common TV show words to identify boundaries.
    This is a heuristic - TVMaze's fuzzy search helps with imperfect matches.

    Args:
        text: Lowercase string without spaces (e.g., "sharktank").

    Returns:
        String with spaces at detected word boundaries.
    """
    common_words = [
        "recreation",
        "stranger",
        "breaking",
        "walking",
        "brooklyn",
        "american",
        "thrones",
        "friends",
        "anatomy",
        "queens",
        "things",
        "office",
        "mirror",
        "knight",
        "modern",
        "shark",
        "house",
        "parks",
        "place",
        "black",
        "girls",
        "crown",
        "night",
        "greys",
        "white",
        "tank",
        "game",
        "dead",
        "good",
        "boys",
        "nine",
        "nine",
        "star",
        "trek",
        "wars",
        "band",
        "bad",
        "big",
        "new",
        "old",
        "day",
        "and",
    ]

    result = text

    for word in common_words:
        if word in result and len(word) >= 3:
            result = re.sub(rf"([a-z])({word})", r"\1 \2", result)
            result = re.sub(rf"({word})([a-z])", r"\1 \2", result)

    for prefix in ["the", "a", "an"]:
        if result.startswith(prefix + " "):
            break
        if result.startswith(prefix) and len(result) > len(prefix):
            rest = result[len(prefix) :]
            if rest[0].isalpha() and rest not in ["re", "nd", "n"]:
                result = prefix + " " + rest
                break

    result = re.sub(r"\s+", " ", result).strip()

    return result


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="episodes_raw")
async def get_episodes_data(show_id: str) -> list[dict[str, Any]]:
    """
    Fetch episode data for a show.

    Fetching strategy:
    1. Try epguides.com (primary source)
       - Scrape show page for CSV export URL
       - Parse episode CSV data
       - Enrich with TVMaze summaries/images
    2. If epguides fails, try TVMaze directly (fallback)
       - Look up show title from our cached metadata
       - Search TVMaze by title
       - Fetch episodes from TVMaze

    Args:
        show_id: Epguides show identifier (e.g., "sharktank").

    Returns:
        List of episode dictionaries with season, number, title, release_date, summary, poster_url.
        Returns empty list if both sources fail.
    """
    url = f"{EPGUIDES_BASE_URL}/{show_id}"
    response = await _fetch_url(url)

    show_page_maze_id: str | None = None

    if response and response.status_code == 200:
        text = response.text
        csv_url, column_map, maze_id = _extract_csv_url_and_maze_id(text)
        show_page_maze_id = maze_id

        if csv_url:
            rows = await fetch_csv(csv_url)
            episodes = _parse_episode_rows(rows, column_map)

            if episodes:
                if maze_id:
                    episodes = await _merge_tvmaze_episode_data(episodes, maze_id)
                logger.debug("Fetched %d episodes from epguides for %s", len(episodes), show_id)
                return episodes

            logger.warning(
                "epguides CSV returned no episodes for %s (csv_url=%s) — falling back to TVMaze",
                show_id,
                csv_url,
            )

    if show_page_maze_id:
        episodes = await _fetch_tvmaze_episodes(show_page_maze_id)
        if episodes:
            logger.info(
                "Fetched %d episodes from TVMaze for %s (maze=%s, via show-page id)",
                len(episodes),
                show_id,
                show_page_maze_id,
            )
            return episodes

    show_title = await _get_show_title(show_id)
    if show_title:
        tvmaze_show = await _search_tvmaze_by_title(show_title)
        if tvmaze_show:
            maze_id = str(tvmaze_show.get("id", ""))
            if maze_id:
                episodes = await _fetch_tvmaze_episodes(maze_id)
                if episodes:
                    logger.info(
                        "Fetched %d episodes from TVMaze for '%s' (maze=%s)", len(episodes), show_title, maze_id
                    )
                    return episodes

    logger.warning("No episode data found for %s", show_id)
    return []


def _extract_csv_url_and_maze_id(page_html: str) -> tuple[str | None, dict[str, int], str | None]:
    """
    Extract CSV export URL, column mapping, and TVMaze ID from show page HTML.

    Returns:
        Tuple of (csv_url, column_map, maze_id) or (None, {}, None) if not found.
    """
    if "exportToCSV.asp" in page_html:
        match = re.search(r"exportToCSV\.asp\?rage=([\d+]+)", page_html)
        if match:
            url = f"{EPGUIDES_BASE_URL}/common/exportToCSV.asp?rage={match.group(1)}"
            return url, _TVRAGE_COLUMNS, None

    if "exportToCSVmaze" in page_html:
        match = re.search(r"exportToCSVmaze\.asp\?maze=([\d]+)", page_html)
        if match:
            maze_id = match.group(1)
            url = f"{EPGUIDES_BASE_URL}/common/exportToCSVmaze.asp?maze={maze_id}"
            return url, _TVMAZE_COLUMNS, maze_id

    return None, {}, None


async def _merge_tvmaze_episode_data(episodes: list[dict[str, Any]], maze_id: str) -> list[dict[str, Any]]:
    """
    Fetch episode data from TVMaze and merge summaries and images into episode data.

    Args:
        episodes: List of episode dicts from epguides CSV.
        maze_id: TVMaze show ID.

    Returns:
        Episodes with 'summary' and 'poster_url' fields added where available.
    """
    response = await _tvmaze_get(f"{_TVMAZE_API_URL}/shows/{maze_id}/episodes")
    if not response:
        return episodes

    try:
        tvmaze_episodes = response.json()

        enrichment_by_season_and_episode: dict[tuple[int, int], dict[str, str]] = {}
        for ep in tvmaze_episodes:
            season = ep.get("season")
            number = ep.get("number")
            if not season or not number:
                continue

            summary = ep.get("summary") or ""
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary).strip()

            image = ep.get("image")
            poster_url = ""
            if image:
                poster_url = image.get("original") or image.get("medium") or ""

            enrichment_by_season_and_episode[(season, number)] = {
                "summary": summary,
                "poster_url": poster_url,
            }

        for episode in episodes:
            try:
                key = (int(episode.get("season", 0)), int(episode.get("number", 0)))
                episode_enrichment = enrichment_by_season_and_episode.get(key, {})
                episode["summary"] = episode_enrichment.get("summary", "")
                episode["poster_url"] = episode_enrichment.get("poster_url", "")
            except ValueError, TypeError:
                episode["summary"] = ""
                episode["poster_url"] = ""

        return episodes

    except Exception as e:
        logger.warning("Failed to merge TVMaze episode data for maze=%s: %s", maze_id, e)
        return episodes


_DEFAULT_POSTER_URL = "https://static.tvmaze.com/images/no-img/no-img-portrait-text.png"


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="tvmaze_show")
async def get_tvmaze_show_data(maze_id: str) -> dict[str, Any] | None:
    """
    Fetch show data from TVMaze including poster image.

    Args:
        maze_id: TVMaze show ID.

    Returns:
        TVMaze show data dict or None on error.
    """
    response = await _tvmaze_get(f"{_TVMAZE_API_URL}/shows/{maze_id}")
    if not response:
        return None
    try:
        data: dict[str, Any] = response.json()
        return data
    except Exception as e:
        logger.warning("Failed to parse TVMaze show data for maze=%s: %s", maze_id, e)
        return None


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="tvmaze_seasons")
async def get_tvmaze_seasons(maze_id: str) -> list[dict[str, Any]]:
    """
    Fetch season data from TVMaze including season posters.

    Args:
        maze_id: TVMaze show ID.

    Returns:
        List of season data dicts with image URLs.
    """
    response = await _tvmaze_get(f"{_TVMAZE_API_URL}/shows/{maze_id}/seasons")
    if not response:
        return []
    try:
        data: list[dict[str, Any]] = response.json()
        return data
    except Exception as e:
        logger.warning("Failed to parse TVMaze seasons for maze=%s: %s", maze_id, e)
        return []


def extract_poster_url(tvmaze_data: dict[str, Any] | None) -> str:
    """
    Extract poster URL from TVMaze data.

    Falls back to default placeholder if no image available.

    Args:
        tvmaze_data: TVMaze API response dict.

    Returns:
        URL to poster image.
    """
    if not tvmaze_data:
        return _DEFAULT_POSTER_URL

    image = tvmaze_data.get("image")
    if image:
        return image.get("original") or image.get("medium") or _DEFAULT_POSTER_URL

    return _DEFAULT_POSTER_URL


async def get_show_poster(maze_id: str) -> str:
    """
    Get poster URL for a show.

    Args:
        maze_id: TVMaze show ID.

    Returns:
        URL to show poster image.
    """
    show_data = await get_tvmaze_show_data(maze_id)
    return extract_poster_url(show_data)


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="maze_id")
async def get_maze_id_for_show(show_id: str) -> str | None:
    """
    Get TVMaze ID for a show.

    Strategy:
    1. Try scraping epguides page for maze ID
    2. If that fails, search TVMaze by show title

    Cached to avoid repeated HTTP calls.

    Args:
        show_id: Epguides show identifier.

    Returns:
        TVMaze show ID or None if not found.
    """
    url = f"{EPGUIDES_BASE_URL}/{show_id}"
    response = await _fetch_url(url)

    if response and response.status_code == 200:
        _, _, maze_id = _extract_csv_url_and_maze_id(response.text)
        if maze_id:
            return maze_id

    show_title = await _get_show_title(show_id)
    if show_title:
        tvmaze_show = await _search_tvmaze_by_title(show_title)
        if tvmaze_show:
            maze_id = tvmaze_show.get("id")
            if maze_id:
                return str(maze_id)

    return None


def _is_integer_token(value: Any) -> bool:
    """
    Return True if ``value`` is a clean integer token (optionally signed).

    Used to reject non-episode rows before they reach ``EpisodeSchema``: the
    header row, blank separators, and — crucially — HTML fragments such as
    ``' user-scalable=yes">'`` that slip in when the upstream returns markup
    instead of CSV (#298). ``str.isdigit`` alone would reject a legitimately
    signed ``"+1"``; ``int()`` accepts surrounding whitespace and signs while
    still rejecting any markup.
    """
    if isinstance(value, int):
        return True
    if not isinstance(value, str):
        return False
    try:
        int(value.strip())
        return True
    except ValueError:
        return False


def _parse_episode_rows(rows: list[list[str]], column_map: dict[str, int]) -> list[dict[str, Any]]:
    """
    Parse CSV rows into episode dictionaries.

    Rows whose ``season`` or ``number`` columns are not clean integers are
    skipped, not kept: that is the header row, blank separators, and any HTML
    fragment that leaked past the upstream guard (#298). Skipping here means a
    future source-layout shift produces a logged parse-miss rather than a
    record with markup in ``EpisodeSchema.number``.

    Args:
        rows: Raw CSV rows.
        column_map: Mapping of field names to column indices.

    Returns:
        List of episode dictionaries (numeric season/number guaranteed).
    """
    episodes: list[dict[str, Any]] = []
    skipped = 0

    for row in rows:
        if not row:
            continue

        episode = {key: row[idx] for key, idx in column_map.items() if len(row) > idx}
        if not episode:
            continue

        if not (_is_integer_token(episode.get("season")) and _is_integer_token(episode.get("number"))):
            skipped += 1
            continue

        episodes.append(episode)

    if skipped:
        logger.debug("Skipped %d non-episode CSV row(s) with non-numeric season/number", skipped)

    return episodes


_IMDB_URL_PATTERN = re.compile(r"imdb\.com/title/(tt\d+)", re.IGNORECASE)
_H2_LINK_PATTERN = re.compile(
    r'<h2>.*?<a[^>]*href=["\']?[^"\']*title/([^"\'/]+)[^"\']*["\' ]?[^>]*>([^<]+)</a>',
    re.IGNORECASE | re.DOTALL,
)
_H2_SIMPLE_PATTERN = re.compile(r"<h2>([^<]+)</h2>", re.IGNORECASE)
_TITLE_TAG_PATTERN = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="show_metadata")
async def get_show_metadata(show_id: str) -> tuple[str, str] | None:
    """
    Fetch IMDB ID and title for a show.

    Scrapes the epguides show page to extract metadata.

    Args:
        show_id: Epguides show identifier.

    Returns:
        Tuple of (imdb_id, title) or None if not found.
    """
    url = f"{EPGUIDES_BASE_URL}/{show_id}"
    response = await _fetch_url(url)

    if not response or response.status_code != 200:
        logger.warning("Failed to fetch metadata for %s", show_id)
        return None

    text = response.text
    imdb_id = _extract_imdb_id(text)
    title = _extract_title(text)

    if imdb_id and title:
        return (imdb_id, title)
    elif imdb_id:
        return (imdb_id, "Unknown")

    logger.debug("Could not extract IMDB ID for %s", show_id)
    return None


def _extract_imdb_id(html: str) -> str | None:
    """Extract IMDB ID from page HTML."""
    match = _IMDB_URL_PATTERN.search(html)
    if match:
        return match.group(1)

    match = _H2_LINK_PATTERN.search(html)
    if match:
        return match.group(1)

    return None


def _extract_title(html: str) -> str | None:
    """Extract show title from page HTML."""
    match = _H2_LINK_PATTERN.search(html)
    if match:
        return match.group(2).strip()

    match = _H2_SIMPLE_PATTERN.search(html)
    if match:
        return match.group(1).strip()

    match = _TITLE_TAG_PATTERN.search(html)
    if match:
        return match.group(1).strip()

    return None
