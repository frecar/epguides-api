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


# =============================================================================
# Cache TTLs (centralized - data changes slowly)
# =============================================================================

CACHE_TTL_30_DAYS = 86400 * 30  # Show list/index
CACHE_TTL_7_DAYS = 86400 * 7  # Enriched shows, seasons, episodes
CACHE_TTL_1_YEAR = 86400 * 365  # Finished shows


async def invalidate_show_cache(normalized_id: str) -> None:
    """Invalidate all caches for a show."""
    from app.core.cache import cache_delete

    await cache_delete(
        f"show:{normalized_id}",
        f"seasons:{normalized_id}",
        f"episodes_parsed:{normalized_id}",
    )


# =============================================================================
# Public API
# =============================================================================


def normalize_show_id(show_id: str) -> str:
    """Normalize show ID: lowercase, no spaces, strip 'the' prefix."""
    normalized = show_id.lower().replace(" ", "")
    return normalized[3:] if normalized.startswith("the") else normalized


async def get_all_shows() -> list[ShowSchema]:
    """
    Get all shows (cached as parsed list in Redis).

    Returns parsed ShowSchema list directly from cache for speed.
    Cache TTL: 30 days.
    """
    from app.core.cache import cache_get, cache_set

    cache_key = "shows_list_parsed"

    # Check cache
    if cached := await cache_get(cache_key):
        return [ShowSchema(**s) for s in json.loads(cached)]

    # Build and cache
    raw_data = await epguides.get_all_shows_metadata()
    shows = [_map_csv_row_to_show(row) for row in raw_data]
    await cache_set(cache_key, json.dumps([s.model_dump(mode="json") for s in shows]), CACHE_TTL_30_DAYS)

    return shows


async def _get_show_by_key(normalized_id: str) -> ShowSchema | None:
    """
    Get single show by key (O(1) Redis hash lookup).

    Falls back to full list scan if Redis unavailable.
    """
    from app.core.cache import cache_exists, cache_hget

    # O(1) hash lookup
    if cached := await cache_hget("show_index", normalized_id):
        return ShowSchema(**json.loads(cached))

    # Build index if missing
    if not await cache_exists("show_index"):
        await _build_show_index()
        if cached := await cache_hget("show_index", normalized_id):
            return ShowSchema(**json.loads(cached))

    # Fallback to list scan (Redis unavailable or show not found)
    shows = await get_all_shows()
    return next((s for s in shows if normalize_show_id(s.epguides_key) == normalized_id), None)


async def _build_show_index() -> None:
    """Build Redis hashes for O(1) lookups: shows, runtimes, titles."""
    from app.core.cache import get_redis

    shows = await get_all_shows()

    try:
        redis = await get_redis()
        pipe = redis.pipeline()
        for show in shows:
            key = normalize_show_id(show.epguides_key)
            pipe.hset("show_index", key, show.model_dump_json())
            # Store runtime separately for O(1) lookup without deserializing full show
            if show.run_time_min:
                pipe.hset("runtime_index", key, str(show.run_time_min))
        pipe.expire("show_index", CACHE_TTL_30_DAYS)
        pipe.expire("runtime_index", CACHE_TTL_30_DAYS)
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


async def get_show(show_id: str) -> ShowSchema | None:
    """
    Get enriched show metadata (cached in Redis).

    Cache TTL: 7 days (ongoing) or 1 year (finished).
    """
    from app.core.cache import cache_get, cache_set

    normalized_id = normalize_show_id(show_id)
    cache_key = f"show:{normalized_id}"

    # Check cache
    if cached := await cache_get(cache_key):
        return ShowSchema(**json.loads(cached))

    # Get base show data
    show = await _get_show_by_key(normalized_id)
    if not show:
        show = await _create_show_from_scrape(normalized_id)
    if not show:
        return None

    # Enrich and cache
    show = await _enrich_show_metadata(show, normalized_id)
    ttl = CACHE_TTL_1_YEAR if show.end_date else CACHE_TTL_7_DAYS
    await cache_set(cache_key, show.model_dump_json(), ttl)

    return show


async def get_episodes(show_id: str) -> list[EpisodeSchema]:
    """
    Get all episodes for a show (cached in Redis).

    Episodes are sorted by season and episode number, and enriched
    with show metadata like runtime, summaries, and episode images from TVMaze.

    For finished shows (all episodes released), cache TTL is extended to 1 year.

    Args:
        show_id: The epguides key or show identifier.

    Returns:
        List of episodes sorted by season and episode number.
    """
    from app.core.cache import cache_get, cache_set

    normalized_id = normalize_show_id(show_id)
    cache_key = f"episodes_parsed:{normalized_id}"

    # Check cache for already-parsed episodes
    if cached := await cache_get(cache_key):
        return [EpisodeSchema(**ep) for ep in json.loads(cached)]

    # Fetch raw data and runtime in parallel
    import asyncio

    raw_data, run_time_min = await asyncio.gather(
        epguides.get_episodes_data(normalized_id),
        _get_show_runtime(normalized_id),
    )

    episodes = [episode for item in raw_data if (episode := _parse_episode(item, run_time_min)) is not None]

    # Sort and assign episode numbers
    episodes.sort(key=lambda ep: (ep.season, ep.number))
    episodes = [ep.model_copy(update={"episode_number": idx}) for idx, ep in enumerate(episodes, start=1)]

    # Cache with appropriate TTL
    is_finished = episodes and all(ep.is_released for ep in episodes)
    ttl = CACHE_TTL_1_YEAR if is_finished else CACHE_TTL_7_DAYS
    await cache_set(cache_key, json.dumps([ep.model_dump(mode="json") for ep in episodes], default=str), ttl)

    return episodes


async def get_seasons(show_id: str) -> list[SeasonSchema]:
    """
    Get seasons with posters and summaries (cached in Redis).

    Cache TTL: 7 days.
    """
    import asyncio

    from app.core.cache import cache_get, cache_set

    normalized_id = normalize_show_id(show_id)
    cache_key = f"seasons:{normalized_id}"

    # Check cache
    if cached := await cache_get(cache_key):
        return [SeasonSchema(**s) for s in json.loads(cached)]

    base_url = settings.API_BASE_URL.rstrip("/")

    # Get episodes and maze_id in parallel
    episodes, maze_id = await asyncio.gather(
        get_episodes(show_id),
        epguides.get_maze_id_for_show(normalized_id),
    )

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
        show_poster, tvmaze_season_list = await asyncio.gather(
            epguides.get_show_poster(maze_id),
            epguides.get_tvmaze_seasons(maze_id),
        )

        for season_data in tvmaze_season_list:
            season_num = season_data.get("number")
            if season_num is not None:
                summary = season_data.get("summary") or ""
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary).strip()

                poster_url = epguides.extract_poster_url(season_data)
                if poster_url == epguides._DEFAULT_POSTER_URL and show_poster:
                    poster_url = show_poster

                tvmaze_seasons[season_num] = {"summary": summary, "poster_url": poster_url}

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
    await cache_set(cache_key, json.dumps([s.model_dump(mode="json") for s in seasons], default=str), CACHE_TTL_7_DAYS)

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


async def _enrich_show_metadata(show: ShowSchema, normalized_id: str) -> ShowSchema:
    """
    Enrich show with IMDB ID, poster, and derived episode data.

    Uses parallel fetching for performance.

    For finished shows (with end_date), extends cache TTL to 1 year
    since the data won't change.
    """
    import asyncio
    from collections.abc import Coroutine

    from app.core.cache import extend_cache_ttl

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
        await extend_cache_ttl("episodes", normalized_id, CACHE_TTL_1_YEAR)
        await extend_cache_ttl("episodes_parsed", normalized_id, CACHE_TTL_1_YEAR)
        await extend_cache_ttl("show_metadata", normalized_id, CACHE_TTL_1_YEAR)

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
    from app.core.cache import cache_exists, cache_hget

    # O(1) lookup from dedicated runtime index
    if cached := await cache_hget("runtime_index", normalized_id):
        return int(cached)

    # Build index if missing
    if not await cache_exists("runtime_index"):
        await _build_show_index()
        if cached := await cache_hget("runtime_index", normalized_id):
            return int(cached)

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
