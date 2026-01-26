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
from datetime import datetime
from typing import Any

import httpx

from app.core.cache import cache
from app.core.config import settings
from app.core.constants import CACHE_TTL_SHOWS_METADATA_SECONDS, DATE_FORMATS, EPGUIDES_BASE_URL, HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# =============================================================================
# Date Parsing
# =============================================================================


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
        Parsed datetime or None if unparseable.
    """
    if not date_string:
        return None

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(date_string, fmt)
            # Fix century for two-digit years that end up in the future
            if parsed.year > datetime.now().year + 2:
                parsed = parsed.replace(year=parsed.year - 100)
            return parsed
        except ValueError:
            continue

    return None


# =============================================================================
# HTTP Utilities
# =============================================================================


def _clean_unicode_text(response: httpx.Response) -> str:
    """
    Extract and clean text from HTTP response.

    Handles encoding issues and Unicode replacement characters.
    """
    response.encoding = response.encoding or "utf-8"
    text = response.text

    # Clean up replacement characters (U+FFFD)
    if "\ufffd" in text:
        text = response.content.decode("utf-8", errors="replace")
        text = text.replace("\ufffd", "")

    return text


async def _fetch_url(url: str) -> httpx.Response | None:
    """
    Fetch URL with standard timeout and error handling.

    Returns None on any error (logged).
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response
    except Exception as e:
        logger.error("Error fetching %s: %s", url, e)
        return None


# =============================================================================
# CSV Fetching
# =============================================================================


async def fetch_csv(url: str) -> list[list[str]]:
    """
    Fetch and parse CSV from URL.

    Args:
        url: URL to fetch CSV from.

    Returns:
        List of rows (each row is a list of strings).
        Returns empty list on error.
    """
    response = await _fetch_url(url)
    if not response:
        return []

    text = _clean_unicode_text(response)
    return list(csv.reader(io.StringIO(text, newline="")))


# =============================================================================
# Show Metadata
# =============================================================================


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


# =============================================================================
# Episode Data
# =============================================================================

# Column mappings for different CSV export formats
_TVRAGE_COLUMNS = {"season": 1, "number": 2, "release_date": 4, "title": 5}
_TVMAZE_COLUMNS = {"season": 1, "number": 2, "release_date": 3, "title": 4}

# TVMaze API base URL
_TVMAZE_API_URL = "https://api.tvmaze.com"


# =============================================================================
# TVMaze Episode Fetching (Fallback)
# =============================================================================


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

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{_TVMAZE_API_URL}/singlesearch/shows",
                params={"q": title},
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                logger.warning("TVMaze search failed for '%s': HTTP %d", title, response.status_code)
                return None
            return response.json()
    except Exception as e:
        logger.warning("TVMaze search error for '%s': %s", title, e)
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
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{_TVMAZE_API_URL}/shows/{maze_id}/episodes")
            if response.status_code != 200:
                logger.warning("TVMaze episodes fetch failed: HTTP %d for maze=%s", response.status_code, maze_id)
                return []

            tvmaze_episodes = response.json()
            episodes: list[dict[str, Any]] = []

            for ep in tvmaze_episodes:
                season = ep.get("season")
                number = ep.get("number")
                name = ep.get("name")
                airdate = ep.get("airdate")

                # Skip episodes missing required fields
                if not all([season, number, name, airdate]):
                    continue

                # Clean HTML from summary
                summary = ep.get("summary") or ""
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary).strip()

                # Extract poster URL
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
        logger.warning("TVMaze episodes fetch error for maze=%s: %s", maze_id, e)
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
    # Strategy 1: Look up in cached metadata
    metadata = await get_all_shows_metadata()
    show_id_lower = show_id.lower()

    for show in metadata:
        directory = show.get("directory", "").lower()
        if directory == show_id_lower:
            title = show.get("title")
            if title:
                return title

    # Strategy 2: Convert show_id to searchable format
    # This handles cases like "SharkTank" -> "Shark Tank" or "gameofthrones" -> "game of thrones"
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
    # Handle CamelCase (e.g., "SharkTank" -> "Shark Tank")
    title = re.sub(r"([a-z])([A-Z])", r"\1 \2", show_id)

    # If no spaces were added and it's all lowercase, try to add word boundaries
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
    # Common words in TV show titles, ordered by length (longer first)
    # to avoid partial matches (e.g., "the" matching inside "thrones")
    common_words = [
        # 10+ chars
        "recreation",
        # 8+ chars
        "stranger",
        "breaking",
        "walking",
        "brooklyn",
        "american",
        # 7 chars
        "thrones",
        "friends",
        "anatomy",
        # 6 chars
        "queens",
        "things",
        "office",
        "mirror",
        "knight",
        "modern",
        # 5 chars
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
        # 4 chars
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
        # 3 chars (careful with these)
        "bad",
        "big",
        "new",
        "old",
        "day",
        "and",
    ]

    result = text

    # Try to split on common word boundaries
    # Process longer words first to avoid partial matches
    for word in common_words:
        if word in result and len(word) >= 3:
            # Add space before the word (if preceded by letters)
            result = re.sub(rf"([a-z])({word})", r"\1 \2", result)
            # Add space after the word (if followed by letters)
            result = re.sub(rf"({word})([a-z])", r"\1 \2", result)

    # Handle common prefixes at the start (the, a, an)
    for prefix in ["the", "a", "an"]:
        if result.startswith(prefix + " "):
            # Already has space, good
            break
        if result.startswith(prefix) and len(result) > len(prefix):
            rest = result[len(prefix) :]
            # Only split if what follows looks like a separate word
            if rest[0].isalpha() and rest not in ["re", "nd", "n"]:  # Avoid "there", "and", "an"
                result = prefix + " " + rest
                break

    # Clean up multiple spaces
    result = re.sub(r"\s+", " ", result).strip()

    return result


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="episodes")
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
    # Strategy 1: Try epguides.com (primary)
    url = f"{EPGUIDES_BASE_URL}/{show_id}"
    response = await _fetch_url(url)

    if response and response.status_code == 200:
        text = response.text
        csv_url, column_map, maze_id = _extract_csv_url_and_maze_id(text)

        if csv_url:
            rows = await fetch_csv(csv_url)
            episodes = _parse_episode_rows(rows, column_map)

            if episodes:
                # Enrich with TVMaze data (summaries + images)
                if maze_id:
                    episodes = await _merge_tvmaze_episode_data(episodes, maze_id)
                logger.debug("Fetched %d episodes from epguides for %s", len(episodes), show_id)
                return episodes

    # Strategy 2: TVMaze fallback
    # Get the proper show title from our metadata for accurate search
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
    # Try TVRage format
    if "exportToCSV.asp" in page_html:
        match = re.search(r"exportToCSV\.asp\?rage=([\d+]+)", page_html)
        if match:
            url = f"{EPGUIDES_BASE_URL}/common/exportToCSV.asp?rage={match.group(1)}"
            return url, _TVRAGE_COLUMNS, None

    # Try TVMaze format
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
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{_TVMAZE_API_URL}/shows/{maze_id}/episodes")
            if response.status_code != 200:
                return episodes

            tvmaze_episodes = response.json()

            # Build lookup by season/episode for summary and image
            tvmaze_data_map: dict[tuple[int, int], dict[str, str]] = {}
            for ep in tvmaze_episodes:
                season = ep.get("season")
                number = ep.get("number")
                if not season or not number:
                    continue

                # Extract summary
                summary = ep.get("summary") or ""
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary).strip()

                # Extract episode image (still from the episode)
                image = ep.get("image")
                poster_url = ""
                if image:
                    poster_url = image.get("original") or image.get("medium") or ""

                tvmaze_data_map[(season, number)] = {
                    "summary": summary,
                    "poster_url": poster_url,
                }

            # Merge TVMaze data into episodes
            for episode in episodes:
                try:
                    key = (int(episode.get("season", 0)), int(episode.get("number", 0)))
                    tvmaze_ep = tvmaze_data_map.get(key, {})
                    episode["summary"] = tvmaze_ep.get("summary", "")
                    episode["poster_url"] = tvmaze_ep.get("poster_url", "")
                except (ValueError, TypeError):
                    episode["summary"] = ""
                    episode["poster_url"] = ""

            return episodes

    except Exception as e:
        logger.warning("Failed to fetch TVMaze episode data for maze=%s: %s", maze_id, e)
        return episodes


# =============================================================================
# TVMaze Images
# =============================================================================

# Default placeholder when no poster is available
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
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{_TVMAZE_API_URL}/shows/{maze_id}")
            if response.status_code != 200:
                return None
            data: dict[str, Any] = response.json()
            return data
    except Exception as e:
        logger.warning("Failed to fetch TVMaze show data for maze=%s: %s", maze_id, e)
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
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{_TVMAZE_API_URL}/shows/{maze_id}/seasons")
            if response.status_code != 200:
                return []
            data: list[dict[str, Any]] = response.json()
            return data
    except Exception as e:
        logger.warning("Failed to fetch TVMaze seasons for maze=%s: %s", maze_id, e)
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
        # Prefer original, fall back to medium
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
    # Strategy 1: Try epguides
    url = f"{EPGUIDES_BASE_URL}/{show_id}"
    response = await _fetch_url(url)

    if response and response.status_code == 200:
        _, _, maze_id = _extract_csv_url_and_maze_id(response.text)
        if maze_id:
            return maze_id

    # Strategy 2: Search TVMaze by title
    show_title = await _get_show_title(show_id)
    if show_title:
        tvmaze_show = await _search_tvmaze_by_title(show_title)
        if tvmaze_show:
            maze_id = tvmaze_show.get("id")
            if maze_id:
                return str(maze_id)

    return None


def _parse_episode_rows(rows: list[list[str]], column_map: dict[str, int]) -> list[dict[str, Any]]:
    """
    Parse CSV rows into episode dictionaries.

    Args:
        rows: Raw CSV rows.
        column_map: Mapping of field names to column indices.

    Returns:
        List of episode dictionaries.
    """
    episodes: list[dict[str, Any]] = []

    for row in rows:
        if not row:
            continue

        episode = {key: row[idx] for key, idx in column_map.items() if len(row) > idx}
        if episode:
            episodes.append(episode)

    return episodes


# =============================================================================
# IMDB Metadata
# =============================================================================

# Regex patterns for extracting IMDB data from show pages
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
    # Try direct IMDB URL
    match = _IMDB_URL_PATTERN.search(html)
    if match:
        return match.group(1)

    # Try H2 link
    match = _H2_LINK_PATTERN.search(html)
    if match:
        return match.group(1)

    return None


def _extract_title(html: str) -> str | None:
    """Extract show title from page HTML."""
    # Try H2 with link
    match = _H2_LINK_PATTERN.search(html)
    if match:
        return match.group(2).strip()

    # Try simple H2
    match = _H2_SIMPLE_PATTERN.search(html)
    if match:
        return match.group(1).strip()

    # Fallback to title tag
    match = _TITLE_TAG_PATTERN.search(html)
    if match:
        return match.group(1).strip()

    return None
