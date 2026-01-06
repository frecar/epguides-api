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


def clear_memory_caches() -> None:
    """
    Clear caches for testing.

    Note: This is a no-op for Redis caches in production.
    Tests should use mocks to control caching behavior.
    """
    pass  # Redis caches are managed by TTL


async def invalidate_show_cache(normalized_id: str) -> None:
    """Invalidate all caches for a show."""
    from app.core.cache import get_redis

    redis = await get_redis()
    try:
        await redis.delete(f"show:{normalized_id}", f"seasons:{normalized_id}")
    except Exception:
        pass


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


# =============================================================================
# Cache TTLs (aggressive caching - data changes slowly)
# =============================================================================

CACHE_TTL_SHOWS_LIST = 86400 * 30  # 30 days - show list rarely changes
CACHE_TTL_SHOW_INDEX = 86400 * 30  # 30 days - same as list
CACHE_TTL_ENRICHED = 86400 * 7  # 7 days for enriched show data
CACHE_TTL_SEASONS = 86400 * 7  # 7 days for seasons
CACHE_TTL_FINISHED = 86400 * 365  # 1 year for finished shows


async def get_all_shows() -> list[ShowSchema]:
    """
    Get all shows (cached as parsed list in Redis).

    Returns parsed ShowSchema list directly from cache for speed.
    Cache TTL: 30 days.
    """
    from app.core.cache import get_redis

    redis = await get_redis()
    cache_key = "shows_list_parsed"

    try:
        cached = await redis.get(cache_key)
        if cached:
            return [ShowSchema(**s) for s in json.loads(cached)]
    except Exception as e:
        logger.warning("Cache read error: %s", e)

    # Build and cache
    raw_data = await epguides.get_all_shows_metadata()
    shows = [_map_csv_row_to_show(row) for row in raw_data]

    try:
        await redis.setex(cache_key, CACHE_TTL_SHOWS_LIST, json.dumps([s.model_dump(mode="json") for s in shows]))
    except Exception as e:
        logger.warning("Cache write error: %s", e)

    return shows


async def _get_show_by_key(normalized_id: str) -> ShowSchema | None:
    """
    Get single show by key (O(1) Redis hash lookup).

    Falls back to full list scan if hash not built yet.
    """
    from app.core.cache import get_redis

    redis = await get_redis()

    try:
        # O(1) hash lookup
        cached: str | None = await redis.hget("show_index", normalized_id)  # type: ignore[assignment]
        if cached:
            return ShowSchema(**json.loads(cached))

        # Build index if missing
        if not await redis.exists("show_index"):
            await _build_show_index()
            cached = await redis.hget("show_index", normalized_id)  # type: ignore[assignment]
            if cached:
                return ShowSchema(**json.loads(cached))

        return None

    except Exception as e:
        logger.warning("Index lookup error: %s", e)
        # Fallback to list scan
        shows = await get_all_shows()
        return next((s for s in shows if normalize_show_id(s.epguides_key) == normalized_id), None)


async def _build_show_index() -> None:
    """Build Redis hash for O(1) show lookups."""
    from app.core.cache import get_redis

    redis = await get_redis()
    shows = await get_all_shows()

    pipe = redis.pipeline()
    for show in shows:
        pipe.hset("show_index", normalize_show_id(show.epguides_key), show.model_dump_json())
    pipe.expire("show_index", CACHE_TTL_SHOW_INDEX)
    await pipe.execute()

    logger.info("Built show index: %d shows", len(shows))


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
    Get enriched show metadata (cached in Redis).

    Cache TTL: 7 days (ongoing) or 1 year (finished).
    """
    from app.core.cache import get_redis

    normalized_id = normalize_show_id(show_id)
    redis = await get_redis()

    # Check cache first
    try:
        cached = await redis.get(f"show:{normalized_id}")
        if cached:
            return ShowSchema(**json.loads(cached))
    except Exception:
        pass

    # Get base show data
    show = await _get_show_by_key(normalized_id)
    if not show:
        show = await _create_show_from_scrape(normalized_id)
    if not show:
        return None

    # Enrich and cache
    show = await _enrich_show_metadata(show, normalized_id)
    ttl = CACHE_TTL_FINISHED if show.end_date else CACHE_TTL_ENRICHED

    try:
        await redis.setex(f"show:{normalized_id}", ttl, show.model_dump_json())
    except Exception:
        pass

    return show


async def get_episodes(show_id: str) -> list[EpisodeSchema]:
    """
    Get all episodes for a show.

    Episodes are sorted by season and episode number, and enriched
    with show metadata like runtime, summaries, and episode images from TVMaze.

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

    # Extend cache for finished shows (all episodes released, none upcoming)
    if episodes:
        has_unreleased = any(not ep.is_released for ep in episodes)
        if not has_unreleased:
            await extend_cache_ttl("episodes", normalized_id, CACHE_TTL_FINISHED)
            logger.debug("Extended episode cache to 1 year for finished show: %s", normalized_id)

    return episodes


async def get_seasons(show_id: str) -> list[SeasonSchema]:
    """
    Get seasons with posters and summaries (cached in Redis).

    Cache TTL: 7 days.
    """
    import asyncio

    from app.core.cache import get_redis

    normalized_id = normalize_show_id(show_id)
    redis = await get_redis()

    # Check cache
    try:
        cached = await redis.get(f"seasons:{normalized_id}")
        if cached:
            return [SeasonSchema(**s) for s in json.loads(cached)]
    except Exception:
        pass

    base_url = settings.API_BASE_URL.rstrip("/")

    # Get episodes and maze_id in parallel
    episodes_task = get_episodes(show_id)
    maze_id_task = epguides.get_maze_id_for_show(normalized_id)

    episodes, maze_id = await asyncio.gather(episodes_task, maze_id_task)

    if not episodes:
        return []

    # Build season stats from episodes
    season_stats: dict[int, dict[str, Any]] = {}
    for ep in episodes:
        if ep.season not in season_stats:
            season_stats[ep.season] = {
                "episode_count": 0,
                "premiere_date": ep.release_date,
                "end_date": ep.release_date,
            }
        season_stats[ep.season]["episode_count"] += 1
        if ep.release_date < season_stats[ep.season]["premiere_date"]:
            season_stats[ep.season]["premiere_date"] = ep.release_date
        if ep.release_date > season_stats[ep.season]["end_date"]:
            season_stats[ep.season]["end_date"] = ep.release_date

    # Get TVMaze data in parallel
    tvmaze_seasons: dict[int, dict[str, Any]] = {}
    show_poster = None

    if maze_id:
        # Parallel fetch of show poster and seasons
        poster_task = epguides.get_show_poster(maze_id)
        seasons_task = epguides.get_tvmaze_seasons(maze_id)
        show_poster, tvmaze_season_list = await asyncio.gather(poster_task, seasons_task)

        for season_data in tvmaze_season_list:
            season_num = season_data.get("number")
            if season_num is not None:
                # Extract summary (strip HTML)
                summary = season_data.get("summary") or ""
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary).strip()

                # Extract poster
                poster_url = epguides.extract_poster_url(season_data)
                if poster_url == epguides._DEFAULT_POSTER_URL and show_poster:
                    poster_url = show_poster

                tvmaze_seasons[season_num] = {
                    "summary": summary,
                    "poster_url": poster_url,
                }

    # Build season schemas
    seasons: list[SeasonSchema] = []
    for season_num in sorted(season_stats.keys()):
        stats = season_stats[season_num]
        tvmaze_data = tvmaze_seasons.get(season_num, {})

        seasons.append(
            SeasonSchema(
                number=season_num,
                episode_count=stats["episode_count"],
                premiere_date=stats["premiere_date"],
                end_date=stats["end_date"],
                poster_url=tvmaze_data.get("poster_url") or show_poster,
                summary=tvmaze_data.get("summary") or None,
                api_episodes_url=f"{base_url}/shows/{normalized_id}/seasons/{season_num}/episodes",
            )
        )

    # Cache result
    try:
        await redis.setex(
            f"seasons:{normalized_id}",
            CACHE_TTL_SEASONS,
            json.dumps([s.model_dump(mode="json") for s in seasons], default=str),
        )
    except Exception:
        pass

    return seasons


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

    Uses parallel fetching for performance.

    For finished shows (with end_date), extends cache TTL to 1 year
    since the data won't change.
    """
    import asyncio
    from collections.abc import Coroutine

    from app.core.cache import CACHE_TTL_FINISHED, extend_cache_ttl

    needs_imdb = not show.imdb_id
    needs_poster = not show.poster_url

    # Parallel fetch: IMDB ID (if needed), episode stats, and poster
    tasks: list[Coroutine[Any, Any, Any]] = [
        _fetch_imdb_id_for_show(show) if needs_imdb else asyncio.sleep(0),
        _calculate_episode_stats(normalized_id),
        _get_poster_url(normalized_id) if needs_poster else asyncio.sleep(0),
    ]

    results = await asyncio.gather(*tasks)

    # Apply IMDB enrichment
    if needs_imdb and results[0] and isinstance(results[0], ShowSchema):
        show = results[0]

    # Apply episode stats
    episode_stats = results[1]
    if episode_stats and isinstance(episode_stats, _EpisodeStats):
        updates = _build_show_updates(show, episode_stats)
        if updates:
            show = show.model_copy(update=updates)

    # Apply poster
    if needs_poster and results[2] and isinstance(results[2], str):
        show = show.model_copy(update={"poster_url": results[2]})

    # Extend cache TTL for finished shows (data won't change)
    if show.end_date:
        await extend_cache_ttl("episodes", normalized_id, CACHE_TTL_FINISHED)
        await extend_cache_ttl("show_metadata", normalized_id, CACHE_TTL_FINISHED)
        logger.debug("Extended cache to 1 year for finished show: %s", normalized_id)

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
    """Get runtime for a show."""
    show = await _get_show_by_key(normalized_id)
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
