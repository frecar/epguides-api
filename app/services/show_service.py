"""
Core service functions for TV show operations.

This module provides pure functional interfaces for:
- Fetching and normalizing show data
- Filtering episodes
- Merging metadata from multiple sources
"""

import asyncio
import html
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import orjson

from app.core.cache import (
    TTL_1_YEAR,
    TTL_7_DAYS,
    TTL_30_DAYS,
    cache_delete,
    cache_exists,
    cache_get,
    cache_hget,
    cache_set,
    cached,
    extend_cache_ttl,
    get_redis,
)
from app.core.config import settings
from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS
from app.models.schemas import EpisodeSchema, SeasonSchema, ShowSchema, create_show_schema
from app.services import epguides

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

_DATE_PLACEHOLDER_PATTERNS = [r"^_+", r"^TBA", r"^TBD", r"^\?+", r"^N/A"]
_MONTH_YEAR_FORMATS = ["%b %Y", "%B %Y", "%b %y", "%B %y"]


async def invalidate_show_cache(normalized_id: str) -> None:
    """Invalidate all caches for a show.

    Both episode cache layers are cleared: the model-validated list
    (``episodes:``) and the raw fetched dicts (``episodes_raw:``). Clearing
    only the former would leave a stale raw layer that the schema layer
    re-derives from on the next miss, so a ``?refresh=true`` would not actually
    re-fetch episodes from upstream within the raw layer's TTL (#298).
    """
    await cache_delete(
        f"show:{normalized_id}",
        f"seasons:{normalized_id}",
        f"episodes:{normalized_id}",
        f"episodes_raw:{normalized_id}",
    )


# =============================================================================
# Public API
# =============================================================================


def normalize_show_id(show_id: str) -> str:
    """Normalize show ID: lowercase, no spaces, strip 'the' prefix."""
    normalized = show_id.lower().replace(" ", "")
    return normalized[3:] if normalized.startswith("the") else normalized


async def get_all_shows() -> list[ShowSchema]:
    """Get all shows. Cache TTL: 30 days."""
    raw = await _get_all_shows_raw()
    return [ShowSchema(**item) for item in raw]


async def get_shows_page(page: int, limit: int) -> tuple[list[ShowSchema], int]:
    """Get paginated shows efficiently (only converts page items to Pydantic)."""
    raw = await _get_all_shows_raw()
    total = len(raw)
    start = (page - 1) * limit
    end = start + limit
    page_items = [ShowSchema(**item) for item in raw[start:end]]
    return page_items, total


async def search_shows_fast(query: str) -> list[ShowSchema]:
    """Search shows efficiently (only converts matches to Pydantic)."""
    raw = await _get_all_shows_raw()
    query_lower = query.lower()
    matches = [item for item in raw if query_lower in item.get("title", "").lower()]
    return [ShowSchema(**item) for item in matches[:100]]  # Limit results


async def _get_all_shows_raw() -> list[dict[str, Any]]:
    """Get raw show data (cached as dicts, not Pydantic models)."""
    cache_key = "shows:all:raw"

    # Check cache (use orjson for faster parsing)
    cached_data = await cache_get(cache_key)
    if cached_data:
        try:
            result: list[dict[str, Any]] = orjson.loads(cached_data)
            return result
        except orjson.JSONDecodeError as e:
            # Corrupted JSON - log warning (cache cleared on deployment)
            logger.warning("Corrupted JSON in cache %s: %s", cache_key, e)

    # Fetch and cache (use orjson for faster serialization)
    raw_data = await epguides.get_all_shows_metadata()
    if not raw_data:
        logger.warning("No show data returned from epguides — upstream may be down")
        return []
    shows: list[dict[str, Any]] = [_map_csv_row_to_dict(row) for row in raw_data]
    await cache_set(cache_key, orjson.dumps(shows).decode(), TTL_30_DAYS)
    logger.debug("Cached %d shows from epguides", len(shows))
    return shows


def _map_csv_row_to_dict(row: dict[str, str]) -> dict[str, Any]:
    """Map CSV row to dict (faster than creating ShowSchema)."""
    title = _clean_title(row.get("title", ""))
    return {
        "epguides_key": row.get("directory", ""),
        "title": title,
        "imdb_id": None,
        "network": row.get("network") or None,
        "run_time_min": _parse_run_time(row.get("run time")),
        "start_date": str(_parse_date(row.get("start date"))) if _parse_date(row.get("start date")) else None,
        "end_date": str(_parse_date(row.get("end date"))) if _parse_date(row.get("end date")) else None,
        "country": row.get("country") or None,
        "total_episodes": _parse_total_episodes(row.get("number of episodes")),
        "poster_url": None,
    }


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
    return await search_shows_fast(query)


# Reverse index `imdb_id → epguides_key`. Populated lazily by `get_show`
# (every time a show is enriched with its imdb_id, we record the mapping).
# Long TTL because an imdb_id ↔ epguides_key binding is essentially static.
_IMDB_INDEX_KEY = "imdb_to_key:{imdb_id}"


async def _index_show_by_imdb(epguides_key: str, imdb_id: str | None) -> None:
    """Record `imdb_id → epguides_key` mapping in cache for reverse lookups."""
    if not imdb_id or not epguides_key:
        return
    await cache_set(_IMDB_INDEX_KEY.format(imdb_id=imdb_id), epguides_key, TTL_1_YEAR)


async def _lookup_local_by_imdb(imdb_id: str) -> ShowSchema | None:
    """Read the imdb_to_key reverse index, then load the full show."""
    epguides_key = await cache_get(_IMDB_INDEX_KEY.format(imdb_id=imdb_id))
    if not epguides_key:
        return None
    return await get_show(epguides_key)


async def get_show_by_imdb_id(imdb_id: str) -> ShowSchema | None:
    """
    Look up a show by its IMDB ID and bridge to the local epguides catalog.

    Title search ambiguity is the gap (#229): "The Office" hits both the
    UK and US versions; "Breaking Bad" hits a remake or fan edit; etc.
    IMDB ID is unambiguous, so callers with an IMDB ID upstream (Radarr,
    Sonarr, a personal media library) can bridge it to an `epguides_key`.

    Two-stage lookup:

    1. **Local reverse index first** — `imdb_to_key:{imdb_id}` cache lookup,
       populated lazily by `get_show` every time a show is enriched with
       its imdb_id. Covers any show that's been visited at least once via
       `/shows/{key}`. Fast: single Redis GET + cached `get_show` call.

    2. **TVMaze fallback** — `/lookup/shows?imdb=<id>` returns the matching
       show by IMDB ID directly, then bridges via title to the local
       catalog. Covers shows the reverse index hasn't seen yet, IF
       TVMaze has them indexed by IMDB.

    Why two stages: TVMaze doesn't index every IMDB ID. #229 follow-up
    (Chicago Fire, tt2261391) exposed this — the show is in our local
    catalog WITH the correct imdb_id, but TVMaze returns null on the
    /lookup/shows?imdb= query. The reverse index closes this gap for
    any show that's been visited via the standard /shows/{key} endpoint.

    Returns None only when both stages fail. The endpoint maps None to
    a 404.

    Args:
        imdb_id: IMDB show identifier (e.g. "tt0903747").

    Returns:
        ShowSchema bridging IMDB ID → epguides_key, or None if no bridge.
    """
    # Stage 1: local reverse index (warm shows we've already enriched)
    local = await _lookup_local_by_imdb(imdb_id)
    if local:
        # The index says this imdb_id maps to local.epguides_key; trust
        # the binding. Use the input imdb_id verbatim in case the local
        # record's imdb_id is stale or missing.
        if local.imdb_id != imdb_id:
            local = create_show_schema(
                epguides_key=local.epguides_key,
                title=local.title,
                imdb_id=imdb_id,
                network=local.network,
                run_time_min=local.run_time_min,
                start_date=local.start_date,
                end_date=local.end_date,
                country=local.country,
                total_episodes=local.total_episodes,
                poster_url=local.poster_url,
            )
        return local

    # Stage 2: TVMaze fallback for shows the index hasn't seen yet
    tvmaze = await epguides.lookup_tvmaze_by_imdb(imdb_id)
    if not tvmaze:
        return None

    title = tvmaze.get("name") or ""
    if not title:
        return None

    # Bridge TVMaze title → local epguides catalog
    by_title = await _find_show_by_title(title)
    if not by_title:
        return None

    # Populate the reverse index opportunistically so future lookups for
    # this imdb_id hit Stage 1 directly.
    await _index_show_by_imdb(by_title.epguides_key, imdb_id)

    return create_show_schema(
        epguides_key=by_title.epguides_key,
        title=by_title.title,
        imdb_id=imdb_id,
        network=by_title.network,
        run_time_min=by_title.run_time_min,
        start_date=by_title.start_date,
        end_date=by_title.end_date,
        country=by_title.country,
        total_episodes=by_title.total_episodes,
        poster_url=by_title.poster_url,
    )


async def _find_show_by_title(title: str) -> ShowSchema | None:
    """Best-effort title match against the local epguides catalog.

    Prefers an exact case-insensitive match. Falls back to a substring
    match (matching show whose title contains the input or vice versa).
    Used by `get_show_by_imdb_id` to bridge TVMaze→local; not exported.
    """
    shows = await get_all_shows()
    title_lower = title.lower().strip()
    if not title_lower:
        return None

    # Pass 1: exact case-insensitive match — the strong signal
    for show in shows:
        if show.title.lower().strip() == title_lower:
            return show

    # Pass 2: title contains query OR query contains title. Handles cases
    # like "The Office (US)" vs "The Office" where TVMaze and epguides
    # disambiguate differently. Substring match is safe here because
    # we've already narrowed to one TVMaze hit by IMDB ID.
    for show in shows:
        local_title = show.title.lower().strip()
        if title_lower in local_title or local_title in title_lower:
            return show

    return None


def _show_ttl(show: ShowSchema | None) -> int | None:
    """Return 1 year TTL for finished shows, else default."""
    return TTL_1_YEAR if show and show.end_date else None


@cached(
    "show:{show_id}",
    ttl=TTL_7_DAYS,
    model=ShowSchema,
    key_transform=normalize_show_id,
    ttl_if=_show_ttl,
)
async def _get_show_cached(show_id: str) -> ShowSchema | None:
    """Cached inner: fetch + enrich. Wrapped by `get_show` for index hygiene."""
    normalized_id = normalize_show_id(show_id)

    show = await _get_show_by_key(normalized_id)
    if not show:
        show = await _create_show_from_scrape(normalized_id)
    if not show:
        return None

    return await _enrich_show_metadata(show, normalized_id)


async def get_show(show_id: str) -> ShowSchema | None:
    """
    Get enriched show metadata. TTL: 7 days (ongoing) or 1 year (finished).

    Wraps `_get_show_cached` to ensure the `imdb_id → epguides_key` reverse
    index stays populated even on cache HITS. The previous implementation
    indexed inside the cached function body, which only ran on cache miss —
    so any show whose data was already cached had no index entry, breaking
    `/shows/by-imdb/<imdb_id>` for that show until the cache TTL expired.

    Check-first pattern avoids a redundant Redis SET on every hot call: read
    the index, write only if missing. Single Redis GET per call is cheap;
    SET only happens once per (imdb_id, epguides_key) binding lifetime.
    """
    show = await _get_show_cached(show_id)
    if show and show.imdb_id:
        existing = await cache_get(_IMDB_INDEX_KEY.format(imdb_id=show.imdb_id))
        if not existing:
            await _index_show_by_imdb(show.epguides_key, show.imdb_id)
    return show


def _episodes_ttl(episodes: list[EpisodeSchema]) -> int | None:
    """Return 1 year TTL if all episodes released (finished show)."""
    if episodes and all(ep.is_released for ep in episodes):
        return TTL_1_YEAR
    return None


@cached(
    "episodes:{show_id}",
    ttl=TTL_7_DAYS,
    model=EpisodeSchema,
    is_list=True,
    key_transform=normalize_show_id,
    ttl_if=_episodes_ttl,
)
async def get_episodes(show_id: str) -> list[EpisodeSchema]:
    """Get all episodes for a show. TTL: 7 days (ongoing) or 1 year (finished)."""
    normalized_id = normalize_show_id(show_id)

    raw_data, run_time_min = await asyncio.gather(
        epguides.get_episodes_data(normalized_id),
        _get_show_runtime(normalized_id),
    )

    episodes = [ep for item in raw_data if (ep := _parse_episode(item, run_time_min))]
    episodes.sort(key=lambda ep: (ep.season, ep.number))
    return [ep.model_copy(update={"episode_number": idx}) for idx, ep in enumerate(episodes, start=1)]


@cached("seasons:{show_id}", ttl=TTL_7_DAYS, model=SeasonSchema, is_list=True, key_transform=normalize_show_id)
async def get_seasons(show_id: str) -> list[SeasonSchema]:
    """Get seasons with posters and summaries. TTL: 7 days."""
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


async def _fetch_tvmaze_season_data(
    maze_id: str | None,
) -> tuple[dict[int, dict[str, Any]], str | None]:
    """Fetch season posters and summaries from TVMaze."""
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


# =============================================================================
# Private Helper Functions - Show Processing
# =============================================================================


async def _enrich_show_metadata(show: ShowSchema, normalized_id: str) -> ShowSchema:
    """Enrich show with IMDB ID, poster, and episode stats."""
    updates: dict[str, Any] = {}

    # Parallel fetch only what's needed
    tasks: list[Any] = []
    task_keys: list[str] = []

    if not show.imdb_id:
        tasks.append(_fetch_imdb_id(show.epguides_key))
        task_keys.append("imdb_id")

    if not show.poster_url:
        tasks.append(_get_poster_url(normalized_id))
        task_keys.append("poster_url")

    tasks.append(_calculate_episode_stats(normalized_id))
    task_keys.append("stats")

    # Execute all tasks in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Apply results (skip tasks that raised exceptions)
    for key, result in zip(task_keys, results, strict=False):
        if isinstance(result, Exception):
            logger.warning("Enrichment task '%s' failed for %s: %s", key, normalized_id, result)
            continue
        if key == "imdb_id" and result:
            updates["imdb_id"] = result
        elif key == "poster_url" and result:
            updates["poster_url"] = result
        elif key == "stats" and isinstance(result, _EpisodeStats):
            updates.update(_build_show_updates(show, result))

    # Apply all updates at once
    if updates:
        show = show.model_copy(update=updates)

    # Extend cache for finished shows
    if show.end_date:
        await extend_cache_ttl("episodes", normalized_id, TTL_1_YEAR)
        await extend_cache_ttl("show", normalized_id, TTL_1_YEAR)

    return show


async def _fetch_imdb_id(epguides_key: str) -> str | None:
    """Fetch IMDB ID for a show."""
    metadata = await epguides.get_show_metadata(epguides_key)
    if metadata and metadata[0]:
        return _parse_imdb_id(metadata[0])
    return None


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
    Calculate statistics from parsed episode data.

    Uses ``get_episodes`` (the validated, cached service layer) rather than
    calling ``epguides.get_episodes_data`` directly.  This means:

    - On a **warm** ``episodes:{id}`` cache hit: stats are derived from
      in-memory ``EpisodeSchema`` objects — no network I/O.
    - On a **cold** build: ``get_episodes`` fetches from upstream once and
      populates ``episodes:{id}``; the result is reused here without a
      second upstream round-trip.  The old implementation called
      ``get_episodes_data`` independently, so a cold show build issued two
      independent upstream fetches for the same episode list (#349).

    ``EpisodeSchema`` objects are already fully parsed and validated, so
    the field-existence checks from the raw-dict path are replaced by
    straightforward attribute reads.
    """
    episodes = await get_episodes(normalized_id)
    if not episodes:
        return None

    stats = _EpisodeStats()
    stats.valid_episode_count = len(episodes)
    stats.has_unreleased = any(not ep.is_released for ep in episodes)
    if episodes:
        stats.last_release_date = max(ep.release_date for ep in episodes)

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

        is_released = datetime.now(UTC) - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS) > release_date

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
    except (ValueError, KeyError, TypeError) as e:
        logger.debug("Failed to parse episode data: %s — %s: %s", item.get("title", "unknown"), type(e).__name__, e)
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
    except ValueError, IndexError:
        return imdb_id_raw


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
    return int(match.group(1)) if match else None


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
            parsed_dt = datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
            return parsed_dt.replace(day=1).date()
        except ValueError:
            continue

    # Try ISO format
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError, AttributeError:
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
