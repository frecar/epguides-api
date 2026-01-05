"""
Epguides.com data fetching and parsing.

This module handles all external API calls to epguides.com:
- Fetching the master show list
- Scraping show metadata (IMDB IDs)
- Parsing episode CSV data

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


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="episodes")
async def get_episodes_data(show_id: str) -> list[dict[str, Any]]:
    """
    Fetch episode data for a show.

    Scrapes the epguides show page to find CSV export URL,
    then fetches and parses the episode data. Also fetches
    episode summaries from TVMaze when available.

    Args:
        show_id: Epguides show identifier.

    Returns:
        List of episode dictionaries with season, number, title, release_date, summary.
        Returns empty list on error.
    """
    url = f"{EPGUIDES_BASE_URL}/{show_id}"
    response = await _fetch_url(url)

    if not response or response.status_code != 200:
        return []

    text = response.text
    csv_url, column_map, maze_id = _extract_csv_url_and_maze_id(text)

    if not csv_url:
        logger.warning("No CSV URL found for %s", show_id)
        return []

    rows = await fetch_csv(csv_url)
    episodes = _parse_episode_rows(rows, column_map)

    # Fetch and merge TVMaze summaries if we have a maze ID
    if maze_id and episodes:
        episodes = await _merge_tvmaze_summaries(episodes, maze_id)

    return episodes


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


async def _merge_tvmaze_summaries(episodes: list[dict[str, Any]], maze_id: str) -> list[dict[str, Any]]:
    """
    Fetch episode summaries from TVMaze and merge into episode data.

    Args:
        episodes: List of episode dicts from epguides CSV.
        maze_id: TVMaze show ID.

    Returns:
        Episodes with 'summary' field added where available.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{_TVMAZE_API_URL}/shows/{maze_id}/episodes")
            if response.status_code != 200:
                return episodes

            tvmaze_episodes = response.json()

            # Build lookup by season/episode
            summary_map: dict[tuple[int, int], str] = {}
            for ep in tvmaze_episodes:
                season = ep.get("season")
                number = ep.get("number")
                summary = ep.get("summary") or ""
                # Strip HTML tags from summary
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary).strip()
                if season and number and summary:
                    summary_map[(season, number)] = summary

            # Merge summaries into episodes
            for episode in episodes:
                try:
                    key = (int(episode.get("season", 0)), int(episode.get("number", 0)))
                    episode["summary"] = summary_map.get(key, "")
                except (ValueError, TypeError):
                    episode["summary"] = ""

            return episodes

    except Exception as e:
        logger.warning("Failed to fetch TVMaze summaries for maze=%s: %s", maze_id, e)
        return episodes


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

        try:
            episode = {key: row[idx] for key, idx in column_map.items() if len(row) > idx}
            if episode:
                episodes.append(episode)
        except (IndexError, KeyError):
            continue

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
