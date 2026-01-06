"""
REST API endpoints for TV show operations.

All endpoints are async and return Pydantic models for automatic validation.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.core.cache import invalidate_cache
from app.models.responses import PaginatedResponse
from app.models.schemas import EpisodeSchema, SeasonSchema, ShowDetailsSchema, ShowListSchema, ShowSchema
from app.services import llm_service, show_service

router = APIRouter()


# =============================================================================
# List & Search Endpoints
# =============================================================================


@router.get(
    "/",
    response_model=PaginatedResponse[ShowListSchema],
    summary="📋 List all shows",
)
async def list_shows(
    page: int = Query(default=1, ge=1, description="Page number", examples=[1, 2, 3]),
    limit: int = Query(default=50, ge=1, le=100, description="Items per page (max 100)", examples=[20, 50, 100]),
) -> PaginatedResponse[ShowListSchema]:
    """
    **Browse all available TV shows** with pagination.

    Returns simplified show information suitable for browsing.
    Use the individual show endpoint for full metadata (IMDB ID, runtime, etc.).

    ### Example
    ```
    GET /shows/?page=1&limit=20
    ```
    """
    page_items, total = await show_service.get_shows_page(page, limit)

    # Convert to simplified list schema
    items = [
        ShowListSchema(
            epguides_key=show.epguides_key,
            title=show.title,
            network=show.network,
            country=show.country,
            start_date=show.start_date,
            end_date=show.end_date,
        )
        for show in page_items
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        has_next=(page * limit) < total,
        has_previous=page > 1,
    )


@router.get(
    "/search",
    response_model=list[ShowListSchema],
    summary="🔍 Search shows",
)
async def search_shows(
    query: str = Query(
        ..., min_length=2, description="Search query (show title)", examples=["breaking", "game of", "office"]
    ),
) -> list[ShowListSchema]:
    """
    **Search for TV shows** by title.

    Performs case-insensitive substring matching across all show titles.

    ### Examples
    ```
    GET /shows/search?query=breaking     → Breaking Bad, Breaking Pointe, ...
    GET /shows/search?query=game of      → Game of Thrones
    GET /shows/search?query=office       → The Office (US), The Office (UK), ...
    ```
    """
    shows = await show_service.search_shows_fast(query)

    return [
        ShowListSchema(
            epguides_key=show.epguides_key,
            title=show.title,
            network=show.network,
            country=show.country,
            start_date=show.start_date,
            end_date=show.end_date,
        )
        for show in shows
    ]


# =============================================================================
# Individual Show Endpoints
# =============================================================================


@router.get(
    "/{epguides_key}",
    response_model=ShowSchema | ShowDetailsSchema,
    summary="📺 Get show metadata",
)
async def get_show_metadata(
    epguides_key: str,
    include: str | None = Query(
        default=None, description="Set to 'episodes' to include full episode list", examples=["episodes"]
    ),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
) -> ShowSchema | ShowDetailsSchema:
    """
    **Get complete metadata** for a specific TV show.

    Returns full details including IMDB ID, runtime, network, air dates, and episode count.

    ### Options
    | Parameter | Description |
    |-----------|-------------|
    | `include=episodes` | Embed the full episode list in response |
    | `refresh=true` | Bypass cache, fetch fresh data |

    ### Examples
    ```
    GET /shows/BreakingBad                     → Show metadata only
    GET /shows/BreakingBad?include=episodes    → Show + all episodes
    GET /shows/BreakingBad?refresh=true        → Force fresh data
    ```

    **Note:** The `epguides_key` is case-insensitive.
    """
    # Invalidate cache if refresh requested
    if refresh:
        normalized_key = show_service.normalize_show_id(epguides_key)
        await invalidate_cache("episodes", normalized_key)
        await invalidate_cache("show_metadata", normalized_key)
        await show_service.invalidate_show_cache(normalized_key)

    show = await show_service.get_show(epguides_key)
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Show not found: {epguides_key}",
        )

    if include == "episodes":
        episodes = await show_service.get_episodes(epguides_key)
        return ShowDetailsSchema(**show.model_dump(), episodes=episodes)

    return show


# =============================================================================
# Season Endpoints
# =============================================================================


@router.get(
    "/{epguides_key}/seasons",
    response_model=list[SeasonSchema],
    summary="📅 List seasons",
)
async def get_seasons(epguides_key: str) -> list[SeasonSchema]:
    """
    **List all seasons** for a show with poster images and summaries.

    Each season includes:
    - Season poster image from TVMaze
    - Season summary (when available)
    - Episode count and air date range
    - Link to episodes for that season

    ### Example
    ```
    GET /shows/BreakingBad/seasons
    ```
    """
    seasons = await show_service.get_seasons(epguides_key)
    if not seasons:
        # Check if show exists at all
        show = await show_service.get_show(epguides_key)
        if not show:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Show not found: {epguides_key}")
    return seasons


@router.get(
    "/{epguides_key}/seasons/{season_number}/episodes",
    response_model=list[EpisodeSchema],
    summary="📋 Get season episodes",
)
async def get_season_episodes(
    epguides_key: str,
    season_number: int,
) -> list[EpisodeSchema]:
    """
    **Get all episodes** for a specific season.

    Each episode includes a still image from the episode (from TVMaze).

    ### Example
    ```
    GET /shows/BreakingBad/seasons/1/episodes
    ```
    """
    episodes = await show_service.get_episodes(epguides_key)
    season_episodes = [ep for ep in episodes if ep.season == season_number]

    if not season_episodes:
        # Check if show exists or just no episodes for this season
        if not episodes:
            show = await show_service.get_show(epguides_key)
            if not show:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Show not found: {epguides_key}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Season {season_number} not found")

    return season_episodes


# =============================================================================
# Episode Endpoints
# =============================================================================


@router.get(
    "/{epguides_key}/episodes",
    response_model=list[EpisodeSchema],
    summary="📋 Get episodes with filtering",
    description="Get episodes for a show with structured filters and AI-powered natural language queries.",
)
async def get_show_episodes(
    epguides_key: str,
    season: int | None = Query(default=None, ge=1, description="Filter by season number", examples=[1, 2, 5]),
    episode: int | None = Query(
        default=None, ge=1, description="Filter by episode number (requires season)", examples=[1, 5, 10]
    ),
    year: int | None = Query(
        default=None, ge=1900, le=2100, description="Filter by release year", examples=[2008, 2020, 2024]
    ),
    title_search: str | None = Query(
        default=None, description="Search in episode titles", examples=["pilot", "finale", "wedding"]
    ),
    nlq: str | None = Query(
        default=None,
        description="🤖 AI-powered natural language query. Requires LLM configuration (check /health/llm).",
        examples=[
            "finale episodes",
            "pilot",
            "most intense episodes",
            "episodes where characters die",
            "season premiere",
        ],
    ),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
) -> list[EpisodeSchema]:
    """
    Get episodes for a show with optional filtering.

    ## Structured Filters (always available)

    | Parameter | Description | Example |
    |-----------|-------------|---------|
    | `season` | Filter by season number | `?season=2` |
    | `episode` | Filter by episode (requires season) | `?season=2&episode=5` |
    | `year` | Filter by release year | `?year=2008` |
    | `title_search` | Search in episode titles | `?title_search=pilot` |

    ## Natural Language Query (requires LLM)

    The `nlq` parameter uses AI to intelligently filter episodes based on your query.
    Check `/health/llm` to verify LLM is configured.

    **Examples:**
    - `?nlq=finale episodes` - Find season/series finales
    - `?nlq=pilot` - Find pilot episodes
    - `?nlq=episodes with major plot twists` - AI interprets and filters

    ## Combining Filters

    Structured filters are applied **before** the NLQ. This lets you narrow down first:
    - `?season=5&nlq=most intense` - Get season 5, then find most intense

    ## Graceful Degradation

    If LLM is not configured or fails, the `nlq` parameter is ignored and all matching episodes are returned.

    ## Cache Refresh

    Use `?refresh=true` to bypass cache and fetch fresh data. Useful when checking for new episodes.
    """
    # Invalidate cache if refresh requested
    if refresh:
        normalized_key = show_service.normalize_show_id(epguides_key)
        await invalidate_cache("episodes", normalized_key)
        await show_service.invalidate_show_cache(normalized_key)

    episodes = await show_service.get_episodes(epguides_key)

    # Apply structured filters first
    if season is not None:
        episodes = [ep for ep in episodes if ep.season == season]
        if episode is not None:
            episodes = [ep for ep in episodes if ep.number == episode]

    if year is not None:
        episodes = [ep for ep in episodes if ep.release_date.year == year]

    if title_search:
        search_lower = title_search.lower()
        episodes = [ep for ep in episodes if search_lower in ep.title.lower()]

    # Apply natural language query if provided (requires LLM)
    if nlq and episodes:
        episodes_as_dicts = [ep.model_dump() for ep in episodes]
        llm_result = await llm_service.parse_natural_language_query(nlq, episodes_as_dicts)
        if llm_result is not None:
            # LLM returned filtered results - convert back to schemas
            episodes = [EpisodeSchema(**ep) for ep in llm_result]

    # Validate show exists if no results
    if not episodes:
        show = await show_service.get_show(epguides_key)
        if not show:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Show not found: {epguides_key}",
            )

    return episodes


@router.get(
    "/{epguides_key}/episodes/next",
    response_model=EpisodeSchema,
    summary="⏭️ Get next episode",
)
async def get_next_episode(epguides_key: str) -> EpisodeSchema:
    """
    **Get the next unreleased episode** for a show.

    Perfect for tracking upcoming episodes of shows you're watching.

    ### Smart Caching
    If the cached "next episode" date has passed, the cache is **automatically refreshed**
    to ensure you always get accurate information.

    ### Response Codes
    | Code | Meaning |
    |------|---------|
    | `200` | Next episode found |
    | `404` | Show finished airing or no upcoming episodes |

    ### Example
    ```
    GET /shows/Severance/episodes/next
    ```
    """
    show = await show_service.get_show(epguides_key)
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Show not found: {epguides_key}",
        )

    # Show with end_date has finished airing
    if show.end_date:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Show has finished airing",
        )

    episodes = await show_service.get_episodes(epguides_key)
    if not episodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No episodes found",
        )

    # Find first unreleased episode with a title
    next_ep = None
    for ep in episodes:
        if not ep.is_released and ep.title:
            next_ep = ep
            break

    if not next_ep:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No unreleased episodes found",
        )

    # Smart cache: if the "next" episode date has passed, cache might be stale
    # Invalidate and refetch to get updated episode list
    if next_ep.release_date < date.today():
        normalized_key = show_service.normalize_show_id(epguides_key)
        await invalidate_cache("episodes", normalized_key)
        episodes = await show_service.get_episodes(epguides_key)

        # Find next episode again with fresh data
        for ep in episodes:
            if not ep.is_released and ep.title:
                return ep

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No unreleased episodes found",
        )

    return next_ep


@router.get(
    "/{epguides_key}/episodes/latest",
    response_model=EpisodeSchema,
    summary="⏮️ Get latest episode",
)
async def get_latest_episode(epguides_key: str) -> EpisodeSchema:
    """
    **Get the most recently released episode** for a show.

    Perfect for finding out what episode to watch next or catching up on a series.

    ### Example
    ```
    GET /shows/BreakingBad/episodes/latest
    ```

    Returns the last episode that has already aired.
    """
    episodes = await show_service.get_episodes(epguides_key)
    if not episodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No episodes found",
        )

    released = [ep for ep in episodes if ep.is_released]
    if not released:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No released episodes found",
        )

    return released[-1]
