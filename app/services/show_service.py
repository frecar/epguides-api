"""
Core service functions for TV show operations.

This module provides pure functional interfaces for:
- Fetching and normalizing show data
- Filtering episodes
- Merging metadata from multiple sources
"""

import logging
import re
from datetime import date, datetime, timedelta

from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS
from app.models.schemas import EpisodeSchema, ShowSchema
from app.services import epguides

logger = logging.getLogger(__name__)


def normalize_show_id(show_id: str) -> str:
    """
    Normalize show identifier for lookup.

    Handles case-insensitive matching and removes "the" prefix.
    Example: "The Breaking Bad" -> "breakingbad"
    """
    normalized = show_id.lower().replace(" ", "")
    return normalized[3:] if normalized.startswith("the") else normalized


def parse_imdb_id(imdb_id_raw: str) -> str:
    """
    Parse and format IMDB ID to standard format.

    Converts raw IMDB ID (e.g., "tt0903747") to properly formatted string.
    """
    try:
        prefix = imdb_id_raw[:2]
        number = int(imdb_id_raw[2:])
        return f"{prefix}{number:07d}"
    except (ValueError, IndexError):
        return imdb_id_raw


async def get_all_shows() -> list[ShowSchema]:
    """
    Get all shows from master list.

    Fetches the complete list of shows from epguides master CSV.
    Results are cached for 24 hours.
    """
    raw_data = await epguides.get_all_shows_metadata()
    return [_map_show(row) for row in raw_data]


async def enrich_shows_with_imdb_ids(shows: list[ShowSchema]) -> list[ShowSchema]:
    """
    Enrich a list of shows with IMDB IDs by scraping epguides pages.

    Only fetches IMDB IDs for shows that don't have them.
    Uses batching to avoid overwhelming the server (max 5 concurrent requests).
    """
    import asyncio

    # Filter shows that need IMDB IDs
    shows_to_enrich = [s for s in shows if not s.imdb_id]

    if not shows_to_enrich:
        return shows

    # Fetch IMDB IDs with batching to avoid rate limiting
    batch_size = 5
    enriched_map = {}

    for i in range(0, len(shows_to_enrich), batch_size):
        batch = shows_to_enrich[i : i + batch_size]

        async def enrich_show(show: ShowSchema) -> ShowSchema:
            metadata = await epguides.get_show_metadata(show.epguides_key)
            if metadata and metadata[0]:
                imdb_id = parse_imdb_id(metadata[0])
                return show.model_copy(update={"imdb_id": imdb_id})
            return show

        # Process batch in parallel
        batch_results = await asyncio.gather(*[enrich_show(s) for s in batch])
        for result in batch_results:
            enriched_map[result.epguides_key] = result

        # Small delay between batches to be respectful
        if i + batch_size < len(shows_to_enrich):
            await asyncio.sleep(0.5)

    # Merge enriched shows back into the original list
    result = []
    for show in shows:
        if show.epguides_key in enriched_map:
            result.append(enriched_map[show.epguides_key])
        else:
            result.append(show)

    return result


async def search_shows(query: str) -> list[ShowSchema]:
    """
    Search shows by title.

    Performs case-insensitive substring search on show titles.
    """
    shows = await get_all_shows()
    query_lower = query.lower()
    return [s for s in shows if query_lower in s.title.lower()]


async def get_show(show_id: str) -> ShowSchema | None:
    """
    Get show details, merging master list data with scraped IMDB ID.

    Strategy:
    1. Try to find show in master list (has rich metadata)
    2. Enrich with IMDB ID if missing (uses same enrichment as list endpoint)
    3. Fallback to scraped data if not in master list

    This ensures consistent IMDB ID fetching across all endpoints.
    """
    normalized_id = normalize_show_id(show_id)

    # Try master list for rich metadata first
    all_shows = await get_all_shows()
    show = next((s for s in all_shows if s.epguides_key.lower() == normalized_id), None)

    if show:
        # Enrich with IMDB ID if missing (same logic as list endpoint)
        if not show.imdb_id:
            enriched = await enrich_shows_with_imdb_ids([show])
            if enriched:
                show = enriched[0]

        # If end_date is missing, try to derive it from the last episode
        # Avoid circular dependency by getting raw episode data directly
        updates = {}
        if not show.end_date:
            raw_data = await epguides.get_episodes_data(normalized_id)
            if raw_data:
                # Find the last valid episode date
                from datetime import timedelta
                from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS

                last_release_date = None
                for item in reversed(raw_data):  # Start from the end
                    release_date_str = item.get("release_date")
                    if release_date_str and isinstance(release_date_str, str):
                        parsed = epguides.parse_date_string(release_date_str)
                        if parsed:
                            last_release_date = parsed.date()
                            break

                if last_release_date:
                    # Check if all episodes are released (last episode is old enough)
                    threshold_date = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS)
                    if last_release_date < threshold_date.date():
                        updates["end_date"] = last_release_date

        if updates:
            return show.model_copy(update=updates)
        return show

    # Fallback: create from scraped data
    metadata = await epguides.get_show_metadata(normalized_id)
    if metadata:
        from app.models.schemas import create_show_schema

        imdb_id = parse_imdb_id(metadata[0]) if metadata[0] else None
        return create_show_schema(
            epguides_key=normalized_id,
            title=metadata[1],
            imdb_id=imdb_id,
        )

    return None


async def get_episodes(show_id: str, filter_query: str | None = None) -> list[EpisodeSchema]:
    """
    Get episodes for a show, optionally filtered.

    Episodes are sorted by season and episode number.
    Supports fast regex-based filtering via filter_query parameter.
    Enriched with show metadata like runtime.
    """
    normalized_id = normalize_show_id(show_id)
    raw_data = await epguides.get_episodes_data(normalized_id)

    # Get show metadata for runtime (avoid circular dependency by using get_all_shows)
    # This is more efficient than calling get_show which might call get_episodes
    all_shows = await get_all_shows()
    show_metadata = next((s for s in all_shows if s.epguides_key.lower() == normalized_id), None)
    run_time_min = show_metadata.run_time_min if show_metadata else None

    episodes = []

    for item in raw_data:
        try:
            # Get release_date and ensure it's a string
            release_date_str = item.get("release_date")
            if not release_date_str or not isinstance(release_date_str, str):
                continue

            release_date = epguides.parse_date_string(release_date_str)
            if not release_date:
                continue

            # Episode is considered "released" if it aired more than threshold hours ago
            is_released = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS) > release_date

            # Get and validate required fields
            season = item.get("season")
            number = item.get("number")
            title = item.get("title")

            if not all([season, number, title]):
                continue

            # Decode HTML entities in title
            import html

            decoded_title = html.unescape(str(title))

            episodes.append(
                EpisodeSchema(
                    season=int(season),
                    number=int(number),
                    title=decoded_title,
                    release_date=release_date.date(),
                    is_released=is_released,
                    run_time_min=run_time_min,
                    episode_number=None,  # Will be set after sorting
                )
            )
        except (ValueError, KeyError, TypeError):
            continue

    # Sort episodes by season and episode number
    episodes.sort(key=lambda x: (x.season, x.number))

    # Set episode_number based on sorted order (1-indexed across all seasons)
    # Pydantic models are immutable, so we need to create new instances
    episodes_with_number = []
    for idx, episode in enumerate(episodes, start=1):
        episodes_with_number.append(episode.model_copy(update={"episode_number": idx}))
    episodes = episodes_with_number

    if filter_query:
        episodes = await _filter_episodes(episodes, filter_query)

    return episodes


async def _filter_episodes(episodes: list[EpisodeSchema], query: str) -> list[EpisodeSchema]:
    """
    Smart episode filtering with regex and optional LLM fallback.

    First tries fast regex-based filtering for common patterns:
    - Season: "season 2", "s2", "s 2"
    - Episode: "episode 5", "e5", "ep 5"
    - Year: "2008", "from 2008"
    - Title: Any text (searches in episode titles)

    If regex doesn't match and LLM is enabled, falls back to LLM for natural language queries.
    """
    query_lower = query.lower().strip()
    filtered = episodes

    # Fast regex-based filtering
    season_match = re.search(r"(?:season|s)\s*(\d+)", query_lower)
    episode_match = re.search(r"(?:episode|ep|e)\s*(\d+)", query_lower)
    year_match = re.search(r"\b(19|20)\d{2}\b", query)

    # Season filter
    if season_match:
        season = int(season_match.group(1))
        filtered = [e for e in filtered if e.season == season]

    # Episode number filter
    if episode_match:
        ep_num = int(episode_match.group(1))
        filtered = [e for e in filtered if e.number == ep_num]

    # Year filter
    if year_match:
        year = int(year_match.group(0))
        filtered = [e for e in filtered if e.release_date.year == year]

    # Title search (if no other filters matched)
    if not (season_match or episode_match or year_match):
        filtered = [e for e in filtered if query_lower in e.title.lower()]

    # If regex didn't match anything and LLM is enabled, try LLM
    if not (season_match or episode_match or year_match) and query_lower not in " ".join(
        [e.title.lower() for e in episodes]
    ):
        try:
            from app.services import llm_service

            # Convert to dict format for LLM
            episodes_dict = [
                {
                    "season": e.season,
                    "number": e.number,
                    "title": e.title,
                    "release_date": str(e.release_date),
                }
                for e in episodes
            ]

            llm_filtered = await llm_service.parse_natural_language_query(query, episodes_dict)
            if llm_filtered:
                # Map back to EpisodeSchema
                filtered_dict = {f"{e['season']}:{e['number']}": e for e in llm_filtered}
                filtered = [e for e in episodes if f"{e.season}:{e.number}" in filtered_dict]
        except Exception:
            # LLM failed, fall back to regex results
            pass

    return filtered


def _parse_run_time(run_time_str: str | None) -> int | None:
    """Parse run time string to minutes (int)."""
    if not run_time_str:
        return None
    # Extract number from strings like "60 min", "60", "30 minutes", etc.
    match = re.search(r"(\d+)", run_time_str)
    if match:
        return int(match.group(1))
    return None


def _parse_total_episodes(episodes_str: str | None) -> int | None:
    """Parse total episodes string to int."""
    if not episodes_str:
        return None
    # Handle formats like "279 eps", "279", "279 episodes"
    # Extract first number from the string
    match = re.search(r"(\d+)", str(episodes_str))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _parse_date(date_str: str | None) -> date | None:
    """Parse date string to date object."""
    if not date_str:
        return None

    date_str = date_str.strip()

    # Skip placeholder values like "___ ____" or "TBA" or "TBD"
    placeholder_patterns = [r"^_+", r"^TBA", r"^TBD", r"^\?+", r"^N/A"]
    if any(re.match(pattern, date_str, re.IGNORECASE) for pattern in placeholder_patterns):
        return None

    # Try parsing with epguides.parse_date_string first (handles full dates)
    parsed = epguides.parse_date_string(date_str)
    if parsed:
        return parsed.date()

    # Handle month-year format like "Sep 2007" or "May 2019"
    month_year_patterns = [
        "%b %Y",  # "Sep 2007"
        "%B %Y",  # "September 2007"
        "%b %y",  # "Sep 07"
        "%B %y",  # "September 07"
    ]

    for pattern in month_year_patterns:
        try:
            parsed = datetime.strptime(date_str, pattern)
            # For month-year only, use the first day of the month
            return parsed.replace(day=1).date()
        except ValueError:
            continue

    # Try ISO format as fallback
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _map_show(row: dict[str, str]) -> ShowSchema:
    """Map CSV row from epguides master list to ShowSchema."""
    from app.models.schemas import create_show_schema

    # Clean title: fix unicode issues before stripping
    title = row.get("title", "")
    # Fix common corrupted unicode characters
    # Handle cases where replacement character was removed, leaving space
    if title.startswith(" ") and len(title) > 1:
        title_lower = title.lower()
        # Common fixes for known corrupted titles
        if " la carte" in title_lower:
            title = "À La Carte"  # Fix corrupted "À"
        elif title_lower.startswith(" la "):
            # Could be other "À La" titles, try to fix
            title = "À" + title.lstrip()
        else:
            title = title.lstrip()
    # Strip whitespace after fixing
    title = title.strip()

    return create_show_schema(
        epguides_key=row.get("directory", ""),
        title=title,
        imdb_id=None,
        network=row.get("network"),
        run_time_min=_parse_run_time(row.get("run time")),
        start_date=_parse_date(row.get("start date")),
        end_date=_parse_date(row.get("end date")),
        country=row.get("country"),
        total_episodes=_parse_total_episodes(row.get("number of episodes")),
    )
