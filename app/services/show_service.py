"""
Core service functions for TV show operations.

This module provides pure functional interfaces for:
- Fetching and normalizing show data
- Filtering episodes
- Merging metadata from multiple sources
"""

import html
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS
from app.models.schemas import EpisodeSchema, ShowSchema, create_show_schema
from app.services import epguides

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

_BATCH_SIZE = 5
_BATCH_DELAY_SECONDS = 0.5
_DATE_PLACEHOLDER_PATTERNS = [r"^_+", r"^TBA", r"^TBD", r"^\?+", r"^N/A"]
_MONTH_YEAR_FORMATS = ["%b %Y", "%B %Y", "%b %y", "%B %y"]


# =============================================================================
# Public API Functions
# =============================================================================


def normalize_show_id(show_id: str) -> str:
    """
    Normalize show identifier for lookup.

    Handles case-insensitive matching and removes "the" prefix.

    Args:
        show_id: Raw show identifier (e.g., "The Breaking Bad")

    Returns:
        Normalized identifier (e.g., "breakingbad")
    """
    normalized = show_id.lower().replace(" ", "")
    return normalized[3:] if normalized.startswith("the") else normalized


async def get_all_shows() -> list[ShowSchema]:
    """
    Get all shows from master list.

    Fetches the complete list of shows from epguides master CSV.
    Results are cached for 30 days via the epguides module.

    Returns:
        List of all available shows.
    """
    raw_data = await epguides.get_all_shows_metadata()
    return [_map_csv_row_to_show(row) for row in raw_data]


async def search_shows(query: str) -> list[ShowSchema]:
    """
    Search shows by title.

    Performs case-insensitive substring search on show titles.

    Args:
        query: Search string to match against titles.

    Returns:
        List of shows matching the query.
    """
    shows = await get_all_shows()
    query_lower = query.lower()
    return [s for s in shows if query_lower in s.title.lower()]


async def get_show(show_id: str) -> ShowSchema | None:
    """
    Get show details with enriched metadata.

    Strategy:
    1. Try to find show in master list (has rich metadata)
    2. Enrich with IMDB ID if missing
    3. Derive end_date and total_episodes from actual episode data
    4. Fallback to scraped data if not in master list

    Args:
        show_id: The epguides key or show identifier.

    Returns:
        ShowSchema with complete metadata, or None if not found.
    """
    normalized_id = normalize_show_id(show_id)

    # Try master list first (has rich metadata)
    all_shows = await get_all_shows()
    show = _find_show_by_id(all_shows, normalized_id)

    if show:
        show = await _enrich_show_metadata(show, normalized_id)
        return show

    # Fallback: create from scraped data
    return await _create_show_from_scrape(normalized_id)


async def get_episodes(show_id: str) -> list[EpisodeSchema]:
    """
    Get episodes for a show.

    Episodes are sorted by season and episode number, and enriched
    with show metadata like runtime and season posters from TVMaze.

    For finished shows (all episodes released), extends cache TTL to 1 year.

    Args:
        show_id: The epguides key or show identifier.

    Returns:
        List of episodes sorted by season and episode number.
    """
    from app.core.cache import CACHE_TTL_FINISHED, extend_cache_ttl

    normalized_id = normalize_show_id(show_id)
    raw_data = await epguides.get_episodes_data(normalized_id)
    run_time_min = await _get_show_runtime(normalized_id)

    episodes = [episode for item in raw_data if (episode := _parse_episode(item, run_time_min)) is not None]

    # Sort and assign episode numbers
    episodes.sort(key=lambda ep: (ep.season, ep.number))
    episodes = [ep.model_copy(update={"episode_number": idx}) for idx, ep in enumerate(episodes, start=1)]

    # Fetch season posters from TVMaze and attach to episodes
    episodes = await _enrich_episodes_with_posters(episodes, normalized_id)

    # Extend cache for finished shows (all episodes released, none upcoming)
    if episodes:
        has_unreleased = any(not ep.is_released for ep in episodes)
        if not has_unreleased:
            await extend_cache_ttl("episodes", normalized_id, CACHE_TTL_FINISHED)
            logger.debug("Extended episode cache to 1 year for finished show: %s", normalized_id)

    return episodes


async def _enrich_episodes_with_posters(episodes: list[EpisodeSchema], normalized_id: str) -> list[EpisodeSchema]:
    """
    Attach season posters to episodes.

    Each episode gets the poster for its season. Falls back to show poster
    if season poster not available.

    Args:
        episodes: List of episodes to enrich.
        normalized_id: Normalized show identifier.

    Returns:
        Episodes with poster_url field populated.
    """
    if not episodes:
        return episodes

    maze_id = await epguides.get_maze_id_for_show(normalized_id)
    if not maze_id:
        return episodes

    # Get show poster and season posters
    show_poster = await epguides.get_show_poster(maze_id)
    season_posters = await epguides.get_season_posters(maze_id, show_poster)

    # Attach poster to each episode
    enriched: list[EpisodeSchema] = []
    for ep in episodes:
        # Use season poster if available, otherwise show poster
        poster = season_posters.get(ep.season, show_poster)
        enriched.append(ep.model_copy(update={"poster_url": poster}))

    return enriched


async def enrich_shows_with_imdb_ids(shows: list[ShowSchema]) -> list[ShowSchema]:
    """
    Enrich a list of shows with IMDB IDs by scraping epguides pages.

    Only fetches IMDB IDs for shows that don't have them.
    Uses batching to avoid overwhelming the server.

    Args:
        shows: List of shows to enrich.

    Returns:
        List of shows with IMDB IDs populated where available.
    """
    import asyncio

    shows_needing_enrichment = [s for s in shows if not s.imdb_id]
    if not shows_needing_enrichment:
        return shows

    enriched_map: dict[str, ShowSchema] = {}

    for i in range(0, len(shows_needing_enrichment), _BATCH_SIZE):
        batch = shows_needing_enrichment[i : i + _BATCH_SIZE]

        # Process batch in parallel
        batch_results = await asyncio.gather(*[_fetch_imdb_id_for_show(s) for s in batch])

        for enriched_show in batch_results:
            enriched_map[enriched_show.epguides_key] = enriched_show

        # Rate limit between batches
        if i + _BATCH_SIZE < len(shows_needing_enrichment):
            await asyncio.sleep(_BATCH_DELAY_SECONDS)

    # Merge enriched shows back, preserving order
    return [enriched_map.get(show.epguides_key, show) for show in shows]


# =============================================================================
# Private Helper Functions - Show Processing
# =============================================================================


def _find_show_by_id(shows: list[ShowSchema], normalized_id: str) -> ShowSchema | None:
    """Find a show in a list by normalized ID."""
    return next((s for s in shows if s.epguides_key.lower() == normalized_id), None)


async def _enrich_show_metadata(show: ShowSchema, normalized_id: str) -> ShowSchema:
    """
    Enrich show with IMDB ID, poster, and derived episode data.

    Fetches IMDB ID if missing, poster from TVMaze, and derives
    end_date/total_episodes from actual episode data for accuracy.

    For finished shows (with end_date), extends cache TTL to 1 year
    since the data won't change.
    """
    from app.core.cache import CACHE_TTL_FINISHED, extend_cache_ttl

    # Enrich with IMDB ID if missing
    if not show.imdb_id:
        enriched_list = await enrich_shows_with_imdb_ids([show])
        show = enriched_list[0]

    # Derive metadata from episode data
    episode_stats = await _calculate_episode_stats(normalized_id)
    if episode_stats:
        updates = _build_show_updates(show, episode_stats)
        if updates:
            show = show.model_copy(update=updates)

    # Fetch poster from TVMaze
    if not show.poster_url:
        show = await _enrich_show_with_poster(show, normalized_id)

    # Extend cache TTL for finished shows (data won't change)
    if show.end_date:
        await extend_cache_ttl("episodes", normalized_id, CACHE_TTL_FINISHED)
        await extend_cache_ttl("show_metadata", normalized_id, CACHE_TTL_FINISHED)
        logger.debug("Extended cache to 1 year for finished show: %s", normalized_id)

    return show


async def _enrich_show_with_poster(show: ShowSchema, normalized_id: str) -> ShowSchema:
    """Fetch and attach poster URL from TVMaze."""
    maze_id = await epguides.get_maze_id_for_show(normalized_id)
    if maze_id:
        poster_url = await epguides.get_show_poster(maze_id)
        return show.model_copy(update={"poster_url": poster_url})
    return show


async def _create_show_from_scrape(normalized_id: str) -> ShowSchema | None:
    """Create a ShowSchema by scraping epguides page directly."""
    metadata = await epguides.get_show_metadata(normalized_id)
    if not metadata:
        return None

    imdb_id = _parse_imdb_id(metadata[0]) if metadata[0] else None
    return create_show_schema(
        epguides_key=normalized_id,
        title=metadata[1],
        imdb_id=imdb_id,
    )


async def _fetch_imdb_id_for_show(show: ShowSchema) -> ShowSchema:
    """Fetch and attach IMDB ID for a single show."""
    metadata = await epguides.get_show_metadata(show.epguides_key)
    if metadata and metadata[0]:
        imdb_id = _parse_imdb_id(metadata[0])
        return show.model_copy(update={"imdb_id": imdb_id})
    return show


async def _get_show_runtime(normalized_id: str) -> int | None:
    """Get runtime for a show from the master list."""
    all_shows = await get_all_shows()
    show = _find_show_by_id(all_shows, normalized_id)
    return show.run_time_min if show else None


# =============================================================================
# Private Helper Functions - Episode Processing
# =============================================================================


class _EpisodeStats:
    """Statistics derived from episode data."""

    def __init__(self) -> None:
        self.has_unreleased: bool = False
        self.last_release_date: date | None = None
        self.valid_episode_count: int = 0


async def _calculate_episode_stats(normalized_id: str) -> _EpisodeStats | None:
    """
    Calculate statistics from raw episode data.

    Returns episode count, last release date, and whether there are
    unreleased episodes.
    """
    raw_data = await epguides.get_episodes_data(normalized_id)
    if not raw_data:
        return None

    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS)
    stats = _EpisodeStats()

    for item in raw_data:
        release_date = _parse_release_date(item.get("release_date"))
        if not release_date:
            continue

        # Check if episode is valid (has required fields)
        if _has_required_episode_fields(item):
            stats.valid_episode_count += 1

        # Check if unreleased
        if release_date > threshold:
            stats.has_unreleased = True

        # Track last release date
        if stats.last_release_date is None or release_date.date() > stats.last_release_date:
            stats.last_release_date = release_date.date()

    return stats


def _build_show_updates(show: ShowSchema, stats: _EpisodeStats) -> dict[str, date | int]:
    """Build update dict for show based on episode statistics."""
    updates: dict[str, date | int] = {}

    # Derive end_date if missing and all episodes are released
    if not show.end_date and not stats.has_unreleased and stats.last_release_date:
        updates["end_date"] = stats.last_release_date

    # Always use actual episode count (more accurate than CSV)
    if stats.valid_episode_count > 0:
        updates["total_episodes"] = stats.valid_episode_count

    return updates


def _parse_episode(item: dict[str, Any], run_time_min: int | None) -> EpisodeSchema | None:
    """
    Parse a raw episode dict into an EpisodeSchema.

    Args:
        item: Raw episode data from CSV.
        run_time_min: Runtime to attach to the episode.

    Returns:
        Parsed EpisodeSchema, or None if data is invalid.
    """
    try:
        release_date = _parse_release_date(item.get("release_date"))
        if not release_date:
            return None

        season_raw = item.get("season")
        number_raw = item.get("number")
        title_raw = item.get("title")

        if season_raw is None or number_raw is None or not title_raw:
            return None

        is_released = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS) > release_date

        # Get summary if available (from TVMaze)
        summary = item.get("summary", "") or ""

        return EpisodeSchema(
            season=int(season_raw),
            number=int(number_raw),
            title=html.unescape(str(title_raw)),
            release_date=release_date.date(),
            is_released=is_released,
            run_time_min=run_time_min,
            episode_number=None,
            summary=summary if summary else None,
        )
    except (ValueError, KeyError, TypeError):
        return None


def _has_required_episode_fields(item: dict[str, Any]) -> bool:
    """Check if episode item has all required fields."""
    return all(
        [
            item.get("season") is not None,
            item.get("number") is not None,
            item.get("title"),
        ]
    )


def _parse_release_date(release_date_str: Any) -> datetime | None:
    """Parse release date from raw value."""
    if not release_date_str or not isinstance(release_date_str, str):
        return None
    return epguides.parse_date_string(release_date_str)


# =============================================================================
# Private Helper Functions - Data Parsing
# =============================================================================


def _parse_imdb_id(imdb_id_raw: str) -> str:
    """
    Parse and format IMDB ID to standard format (tt + 7 digits).

    Example: "tt903747" -> "tt0903747"
    """
    try:
        prefix = imdb_id_raw[:2]
        number = int(imdb_id_raw[2:])
        return f"{prefix}{number:07d}"
    except (ValueError, IndexError):
        return imdb_id_raw


# Keep public alias for backwards compatibility
parse_imdb_id = _parse_imdb_id


def _parse_run_time(run_time_str: str | None) -> int | None:
    """Parse run time string to minutes."""
    if not run_time_str:
        return None
    match = re.search(r"(\d+)", run_time_str)
    return int(match.group(1)) if match else None


def _parse_total_episodes(episodes_str: str | None) -> int | None:
    """Parse total episodes string to int."""
    if not episodes_str:
        return None
    match = re.search(r"(\d+)", str(episodes_str))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _parse_date(date_str: str | None) -> date | None:
    """
    Parse date string to date object.

    Handles various formats including:
    - Full dates via epguides parser
    - Month-year formats (e.g., "Sep 2007")
    - ISO format (YYYY-MM-DD)
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Skip placeholder values
    if any(re.match(p, date_str, re.IGNORECASE) for p in _DATE_PLACEHOLDER_PATTERNS):
        return None

    # Try epguides parser first
    parsed = epguides.parse_date_string(date_str)
    if parsed:
        return parsed.date()

    # Try month-year formats
    for fmt in _MONTH_YEAR_FORMATS:
        try:
            parsed_dt = datetime.strptime(date_str, fmt)
            return parsed_dt.replace(day=1).date()
        except ValueError:
            continue

    # Try ISO format
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


# =============================================================================
# Private Helper Functions - CSV Mapping
# =============================================================================


def _map_csv_row_to_show(row: dict[str, str]) -> ShowSchema:
    """Map CSV row from epguides master list to ShowSchema."""
    title = _clean_title(row.get("title", ""))

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


def _clean_title(title: str) -> str:
    """
    Clean and fix common title encoding issues.

    Handles corrupted unicode characters that appear as leading spaces.
    """
    if not title:
        return title

    # Fix corrupted unicode that leaves leading space
    if title.startswith(" ") and len(title) > 1:
        title_lower = title.lower()

        # Known fixes for corrupted "À" character
        if " la carte" in title_lower:
            return "À La Carte"
        if title_lower.startswith(" la "):
            return "À" + title.lstrip()

        return title.lstrip()

    return title.strip()
