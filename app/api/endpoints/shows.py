"""
REST API endpoints for TV show operations.

All endpoints are async and return Pydantic models for automatic validation.
"""

from fastapi import APIRouter, HTTPException, Query, status

from app.models.responses import PaginatedResponse
from app.models.schemas import EpisodeSchema, ShowDetailsSchema, ShowListSchema, ShowSchema
from app.services import llm_service, show_service

router = APIRouter()


# =============================================================================
# List & Search Endpoints
# =============================================================================


@router.get(
    "/",
    response_model=PaginatedResponse[ShowListSchema],
    summary="List all shows",
)
async def list_shows(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=50, ge=1, le=100, description="Items per page"),
) -> PaginatedResponse[ShowListSchema]:
    """
    List all available shows with pagination.

    Returns simplified show information suitable for browsing.
    For detailed metadata (IMDB ID, runtime, episode count),
    use the individual show endpoint.
    """
    all_shows = await show_service.get_all_shows()

    total = len(all_shows)
    start = (page - 1) * limit
    end = start + limit
    page_items = all_shows[start:end]

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
        has_next=end < total,
        has_previous=page > 1,
    )


@router.get(
    "/search",
    response_model=list[ShowListSchema],
    summary="Search shows",
)
async def search_shows(
    query: str = Query(..., min_length=2, description="Search query (show title)"),
) -> list[ShowListSchema]:
    """
    Search for shows by title.

    Performs case-insensitive substring matching.
    Returns simplified show information.
    """
    shows = await show_service.search_shows(query)

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
    summary="Get show metadata",
)
async def get_show_metadata(
    epguides_key: str,
    include: str | None = Query(default=None, description="Include 'episodes' for full episode list"),
) -> ShowSchema | ShowDetailsSchema:
    """
    Get complete metadata for a show.

    Returns full show details including IMDB ID, runtime, and episode count.
    The epguides_key is case-insensitive.

    Use `?include=episodes` to embed the full episode list in the response.
    """
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
# Episode Endpoints
# =============================================================================


@router.get(
    "/{epguides_key}/episodes",
    response_model=list[EpisodeSchema],
    summary="Get episodes with filtering",
    description="Get episodes for a show with optional structured filters and AI-powered natural language queries.",
)
async def get_show_episodes(
    epguides_key: str,
    season: int | None = Query(default=None, ge=1, description="Filter by season number"),
    episode: int | None = Query(default=None, ge=1, description="Filter by episode number (requires season)"),
    year: int | None = Query(default=None, ge=1900, le=2100, description="Filter by release year"),
    title_search: str | None = Query(default=None, description="Search in episode titles (case-insensitive)"),
    nlq: str | None = Query(
        default=None,
        description="Natural language query - use AI to filter episodes. Requires LLM to be configured. "
        "Examples: 'finale episodes', 'pilot', 'episodes with cliffhangers'",
        examples=["finale episodes", "pilot", "episodes where characters die", "season premiere"],
    ),
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
    """
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
    summary="Get next episode",
)
async def get_next_episode(epguides_key: str) -> EpisodeSchema:
    """
    Get the next unreleased episode.

    Returns 404 if the show has finished airing or has no upcoming episodes.
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
    for ep in episodes:
        if not ep.is_released and ep.title:
            return ep

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No unreleased episodes found",
    )


@router.get(
    "/{epguides_key}/episodes/latest",
    response_model=EpisodeSchema,
    summary="Get latest episode",
)
async def get_latest_episode(epguides_key: str) -> EpisodeSchema:
    """
    Get the most recently released episode.

    Useful for checking the latest episode to watch.
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
