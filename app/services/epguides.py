"""
Epguides.com data fetching and parsing.

This module handles all external API calls to epguides.com:
- Fetching master show list
- Scraping show metadata
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
from app.core.constants import DATE_FORMATS, EPGUIDES_BASE_URL

logger = logging.getLogger(__name__)


def parse_date_string(date_string: str) -> datetime | None:
    """
    Parse date string in various formats.

    Supports:
    - "%d %b %y" (e.g., "20 Jan 08")
    - "%d/%b/%y" (e.g., "20/Jan/08")
    - "%Y-%m-%d" (e.g., "2008-01-20")

    Automatically fixes century for old shows (e.g., "08" -> 2008, not 2108).
    """
    if not date_string:
        return None

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(date_string, fmt)
            # Fix century for old shows
            if parsed.year > datetime.now().year + 2:
                parsed = parsed.replace(year=parsed.year - 100)
            return parsed
        except ValueError:
            continue
    return None


async def fetch_csv(url: str) -> list[list[str]]:
    """
    Fetch and parse CSV from URL.

    Uses httpx with 10 second timeout and follows redirects.
    Handles encoding issues gracefully.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            # Ensure proper encoding
            response.encoding = response.encoding or "utf-8"
            text = response.text
            # Clean up replacement characters (Unicode replacement char U+FFFD)
            if "\ufffd" in text:
                # Try to decode with error handling
                text = response.content.decode("utf-8", errors="replace")
                # Remove replacement characters
                text = text.replace("\ufffd", "")
            return list(csv.reader(io.StringIO(text, newline="")))
    except Exception as e:
        logger.error(f"Error fetching CSV from {url}: {e}")
        return []


@cache(ttl_seconds=86400, key_prefix="shows_metadata")
async def get_all_shows_metadata() -> list[dict[str, str]]:
    """
    Fetch master list of all shows from epguides.

    Returns list of dictionaries with show metadata from epguides.com/common/allshows.txt.
    Cached for 24 hours.
    """
    url = f"{EPGUIDES_BASE_URL}/common/allshows.txt"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            # Ensure proper encoding handling
            response.encoding = response.encoding or "utf-8"
            # Clean up any replacement characters and normalize unicode
            text = response.text
            # Replace replacement characters with empty string or try to fix encoding
            if "\ufffd" in text:
                # Try to decode with errors='replace' to handle malformed sequences
                text = response.content.decode("utf-8", errors="replace")
                # Remove replacement characters
                text = text.replace("\ufffd", "")
            return list(csv.DictReader(io.StringIO(text, newline="")))
    except Exception as e:
        logger.error(f"Error fetching shows metadata: {e}")
        return []


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="episodes")
async def get_episodes_data(show_id: str) -> list[dict[str, Any]]:
    """
    Fetch episode data for a show.

    Scrapes epguides.com to find the CSV export URL, then fetches and parses the CSV.
    Supports both TVRage and TVMaze export formats.

    Returns list of episode dictionaries with season, number, title, release_date.
    """
    url = f"{EPGUIDES_BASE_URL}/{show_id}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return []

            text = response.text
            data_url = None
            column_map = {}

            # Extract CSV URL
            if "exportToCSV.asp" in text:
                match = re.search(r"exportToCSV\.asp\?rage=([\d+]+)", text)
                if match:
                    data_url = f"{EPGUIDES_BASE_URL}/common/exportToCSV.asp?rage={match.group(1)}"
                    column_map = {"season": 1, "number": 2, "release_date": 4, "title": 5}
            elif "exportToCSVmaze" in text:
                match = re.search(r"exportToCSVmaze\.asp\?maze=([\d]+)", text)
                if match:
                    data_url = f"{EPGUIDES_BASE_URL}/common/exportToCSVmaze.asp?maze={match.group(1)}"
                    column_map = {"season": 1, "number": 2, "release_date": 3, "title": 4}

            if not data_url:
                logger.warning(f"No CSV URL found for {show_id}")
                return []

            # Parse CSV
            rows = await fetch_csv(data_url)
            episodes = []
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
    except Exception as e:
        logger.error(f"Error fetching episodes for {show_id}: {e}")
        return []


@cache(ttl_seconds=settings.CACHE_TTL_SECONDS, key_prefix="show_metadata")
async def get_show_metadata(show_id: str) -> tuple[str, str] | None:
    """
    Fetch basic show metadata (IMDB ID and title).

    Scrapes the epguides.com show page to extract IMDB ID and title.
    Returns tuple of (imdb_id_raw, title) or None if not found.
    """
    try:
        url = f"{EPGUIDES_BASE_URL}/{show_id}"
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: status {response.status_code}")
                return None

            text = response.text

            # Try multiple patterns to find IMDB ID
            imdb_id = None
            title = None

            # Pattern 1: Direct IMDB URL in the page
            imdb_match = re.search(r"imdb\.com/title/(tt\d+)", text, re.IGNORECASE)
            if imdb_match:
                imdb_id = imdb_match.group(1)

            # Pattern 2: H2 tag with link containing title/ID
            h2_match = re.search(
                r'<h2>.*?<a[^>]*href=["\']?[^"\']*title/([^"\'/]+)[^"\']*["\' ]?[^>]*>([^<]+)</a>',
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if h2_match:
                if not imdb_id:
                    imdb_id = h2_match.group(1)
                title = h2_match.group(2).strip()

            # Pattern 3: Simple H2 tag with title
            if not title:
                h2_simple = re.search(r"<h2>([^<]+)</h2>", text, re.IGNORECASE)
                if h2_simple:
                    title = h2_simple.group(1).strip()

            # Pattern 4: Title tag as fallback
            if not title:
                title_match = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()

            if imdb_id and title:
                return (imdb_id, title)
            elif imdb_id:
                # Return with placeholder title if we have IMDB ID
                return (imdb_id, "Unknown")
            elif title:
                # Return None for IMDB ID if we only have title
                logger.debug(f"Found title but no IMDB ID for {show_id}")
                return None

            logger.warning(f"Could not extract IMDB ID or title for {show_id}")
            return None

    except Exception as e:
        logger.error(f"Error fetching metadata for {show_id}: {e}", exc_info=True)
        return None
