"""
Core service functions for TV show operations.

This module provides pure functional interfaces for:
- Fetching and normalizing show data
- Filtering episodes
- Merging metadata from multiple sources
"""

import html
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from app.core.cache import cache_delete, cache_exists, cache_hget, cached, extend_cache_ttl, get_redis
from app.core.config import settings
from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS
from app.models.schemas import EpisodeSchema, SeasonSchema, ShowSchema, create_show_schema
from app.services import epguides

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

_BATCH_SIZE = 5
_BATCH_DELAY_SECONDS = 0.5
_DATE_PLACEHOLDER_PATTERNS = [r"^_+", r"^TBA", r"^TBD", r"^\?+", r"^N/A"]
_MONTH_YEAR_FORMATS = ["%b %Y", "%B %Y", "%b %y", "%B %y"]

# Cache TTLs (centralized)
TTL_30_DAYS = 86400 * 30  # Show list/index
TTL_7_DAYS = 86400 * 7  # Enriched shows, seasons, episodes
TTL_1_YEAR = 86400 * 365  # Finished shows


async def invalidate_show_cache(normalized_id: str) -> None:
    """Invalidate all caches for a show."""
    await cache_delete(
        f"show:{normalized_id}",
        f"seasons:{normalized_id}",
        f"episodes:{normalized_id}",
    )


# =============================================================================
# Public API
# =============================================================================


def normalize_show_id(show_id: str) -> str:
    """Normalize show ID: lowercase, no spaces, strip 'the' prefix."""
    normalized = show_id.lower().replace(" ", "")
    return normalized[3:] if normalized.startswith("the") else normalized


@cached("shows:all", ttl=TTL_30_DAYS, model=ShowSchema, is_list=True)
async def get_all_shows() -> list[ShowSchema]:
    """Get all shows. Cache TTL: 30 days."""
    raw_data = await epguides.get_all_shows_metadata()
    return [_map_csv_row_to_show(row) for row in raw_data]


async def _get_show_by_key(normalized_id: str) -> ShowSchema | None:
    """Get single show by key (O(1) Redis hash lookup)."""
    # O(1) hash lookup
    if data := await cache_hget("show_index", normalized_id):
        return ShowSchema(**json.loads(data))

    # Build index if missing, retry lookup
    if not await cache_exists("show_index"):
        await _build_show_index()
        if data := await cache_hget("show_index", normalized_id):
            return ShowSchema(**json.loads(data))

    # Fallback to list scan
    shows = await get_all_shows()
    return next((s for s in shows if normalize_show_id(s.epguides_key) == normalized_id), None)


async def _build_show_index() -> None:
    """Build Redis hashes for O(1) lookups."""
    shows = await get_all_shows()
    try:
        redis = await get_redis()
        pipe = redis.pipeline()
        for show in shows:
            key = normalize_show_id(show.epguides_key)
            pipe.hset("show_index", key, show.model_dump_json())
            if show.run_time_min:
                pipe.hset("runtime_index", key, str(show.run_time_min))
        pipe.expire("show_index", TTL_30_DAYS)
        pipe.expire("runtime_index", TTL_30_DAYS)
        await pipe.execute()
        logger.info("Built show index: %d shows", len(shows))
    except Exception as e:
        logger.warning("Failed to build show index: %s", e)


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


def _show_ttl(show: ShowSchema | None) -> int | None:
    """Return 1 year TTL for finished shows, else default."""
    return TTL_1_YEAR if show and show.end_date else None


@cached(
    "show:{0}",
    ttl=TTL_7_DAYS,
    model=ShowSchema,
    key_transform=normalize_show_id,
    ttl_if=_show_ttl,
)
async def get_show(show_id: str) -> ShowSchema | None:
    """Get enriched show metadata. TTL: 7 days (ongoing) or 1 year (finished)."""
    normalized_id = normalize_show_id(show_id)

    show = await _get_show_by_key(normalized_id)
    if not show:
        show = await _create_show_from_scrape(normalized_id)
    if not show:
        return None

    return await _enrich_show_metadata(show, normalized_id)


def _episodes_ttl(episodes: list[EpisodeSchema]) -> int | None:
    """Return 1 year TTL if all episodes released (finished show)."""
    if episodes and all(ep.is_released for ep in episodes):
        return TTL_1_YEAR
    return None


@cached(
    "episodes:{0}",
    ttl=TTL_7_DAYS,
    model=EpisodeSchema,
    is_list=True,
    key_transform=normalize_show_id,
    ttl_if=_episodes_ttl,
)
async def get_episodes(show_id: str) -> list[EpisodeSchema]:
    """Get all episodes for a show. TTL: 7 days (ongoing) or 1 year (finished)."""
    import asyncio

    normalized_id = normalize_show_id(show_id)

    raw_data, run_time_min = await asyncio.gather(
        epguides.get_episodes_data(normalized_id),
        _get_show_runtime(normalized_id),
    )

    episodes = [ep for item in raw_data if (ep := _parse_episode(item, run_time_min))]
    episodes.sort(key=lambda ep: (ep.season, ep.number))
    return [ep.model_copy(update={"episode_number": idx}) for idx, ep in enumerate(episodes, start=1)]


@cached("seasons:{0}", ttl=TTL_7_DAYS, model=SeasonSchema, is_list=True, key_transform=normalize_show_id)
async def get_seasons(show_id: str) -> list[SeasonSchema]:
    """Get seasons with posters and summaries. TTL: 7 days."""
    import asyncio

    normalized_id = normalize_show_id(show_id)
    base_url = settings.API_BASE_URL.rstrip("/")

    # Parallel fetch
    episodes, maze_id = await asyncio.gather(
        get_episodes(show_id),
        epguides.get_maze_id_for_show(normalized_id),
    )
    if not episodes:
        return []

    # Build season stats
    season_stats = _build_season_stats(episodes)

    # Get TVMaze metadata
    tvmaze_seasons, show_poster = await _fetch_tvmaze_season_data(maze_id)

    # Build schemas
    return [
        SeasonSchema(
            number=num,
            episode_count=stats["episode_count"],
            premiere_date=stats["premiere_date"],
            end_date=stats["end_date"],
            poster_url=tvmaze_seasons.get(num, {}).get("poster_url") or show_poster,
            summary=tvmaze_seasons.get(num, {}).get("summary"),
            api_episodes_url=f"{base_url}/shows/{normalized_id}/seasons/{num}/episodes",
        )
        for num, stats in sorted(season_stats.items())
    ]


def _build_season_stats(episodes: list[EpisodeSchema]) -> dict[int, dict[str, Any]]:
    """Aggregate episode data into season statistics."""
    stats: dict[int, dict[str, Any]] = {}
    for ep in episodes:
        if ep.season not in stats:
            stats[ep.season] = {"episode_count": 0, "premiere_date": ep.release_date, "end_date": ep.release_date}
        stats[ep.season]["episode_count"] += 1
        if ep.release_date < stats[ep.season]["premiere_date"]:
            stats[ep.season]["premiere_date"] = ep.release_date
        if ep.release_date > stats[ep.season]["end_date"]:
            stats[ep.season]["end_date"] = ep.release_date
    return stats


async def _fetch_tvmaze_season_data(maze_id: int | None) -> tuple[dict[int, dict[str, Any]], str | None]:
    """Fetch season posters and summaries from TVMaze."""
    import asyncio

    if not maze_id:
        return {}, None

    show_poster, tvmaze_list = await asyncio.gather(
        epguides.get_show_poster(maze_id),
        epguides.get_tvmaze_seasons(maze_id),
    )

    seasons: dict[int, dict[str, Any]] = {}
    for data in tvmaze_list:
        num = data.get("number")
        if num is not None:
            summary = re.sub(r"<[^>]+>", "", data.get("summary") or "").strip() or None
            poster = epguides.extract_poster_url(data)
            if poster == epguides._DEFAULT_POSTER_URL and show_poster:
                poster = show_poster
            seasons[num] = {"summary": summary, "poster_url": poster}

    return seasons, show_poster


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


async def _enrich_show_metadata(show: ShowSchema, normalized_id: str) -> ShowSchema:
    """
    Enrich show with IMDB ID, poster, and derived episode data.

    Uses parallel fetching for performance.

    For finished shows (with end_date), extends cache TTL to 1 year
    since the data won't change.
    """
    import asyncio
    from collections.abc import Coroutine

    needs_imdb = not show.imdb_id
    needs_poster = not show.poster_url

    # Parallel fetch: IMDB ID, episode stats, poster
    tasks: list[Coroutine[Any, Any, Any]] = [
        _fetch_imdb_id_for_show(show) if needs_imdb else asyncio.sleep(0),
        _calculate_episode_stats(normalized_id),
        _get_poster_url(normalized_id) if needs_poster else asyncio.sleep(0),
    ]
    results = await asyncio.gather(*tasks)

    # Apply results
    if needs_imdb and isinstance(results[0], ShowSchema):
        show = results[0]

    if isinstance(results[1], _EpisodeStats):
        updates = _build_show_updates(show, results[1])
        if updates:
            show = show.model_copy(update=updates)

    if needs_poster and isinstance(results[2], str):
        show = show.model_copy(update={"poster_url": results[2]})

    # Extend cache TTLs for finished shows (data won't change)
    if show.end_date:
        await extend_cache_ttl("episodes", normalized_id, TTL_1_YEAR)
        await extend_cache_ttl("show", normalized_id, TTL_1_YEAR)

    return show


async def _get_poster_url(normalized_id: str) -> str | None:
    """Fetch poster URL from TVMaze."""
    maze_id = await epguides.get_maze_id_for_show(normalized_id)
    if maze_id:
        return await epguides.get_show_poster(maze_id)
    return None


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
    """Get runtime for a show (O(1) from runtime index)."""
    if data := await cache_hget("runtime_index", normalized_id):
        return int(data)

    if not await cache_exists("runtime_index"):
        await _build_show_index()
        if data := await cache_hget("runtime_index", normalized_id):
            return int(data)

    return None


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

        # Get summary and poster_url if available (from TVMaze)
        summary = item.get("summary", "") or ""
        poster_url = item.get("poster_url", "") or ""

        return EpisodeSchema(
            season=int(season_raw),
            number=int(number_raw),
            title=html.unescape(str(title_raw)),
            release_date=release_date.date(),
            is_released=is_released,
            run_time_min=run_time_min,
            episode_number=None,
            summary=summary if summary else None,
            poster_url=poster_url if poster_url else None,
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
