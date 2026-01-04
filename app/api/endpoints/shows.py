"""
REST API endpoints for TV show operations.

All endpoints are async and return Pydantic models for automatic validation.
"""

from fastapi import APIRouter, HTTPException, Query, status

from app.models.responses import PaginatedResponse
from app.models.schemas import EpisodeSchema, ShowDetailsSchema, ShowListSchema, ShowSchema
from app.services import show_service

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
    summary="Get episodes",
)
async def get_show_episodes(
    epguides_key: str,
    season: int | None = Query(default=None, ge=1, description="Filter by season"),
    episode: int | None = Query(default=None, ge=1, description="Filter by episode (requires season)"),
    year: int | None = Query(default=None, ge=1900, le=2100, description="Filter by release year"),
    title_search: str | None = Query(default=None, description="Search in episode titles"),
) -> list[EpisodeSchema]:
    """
    Get episodes for a show with optional filtering.

    Filter options:
    - `season`: Filter by season number
    - `episode`: Filter by episode number (requires season)
    - `year`: Filter by release year
    - `title_search`: Search in episode titles

    Examples:
    - `/shows/BreakingBad/episodes?season=2`
    - `/shows/BreakingBad/episodes?year=2008`
    """
    episodes = await show_service.get_episodes(epguides_key)

    # Apply filters
    if season is not None:
        episodes = [ep for ep in episodes if ep.season == season]
        if episode is not None:
            episodes = [ep for ep in episodes if ep.number == episode]

    if year is not None:
        episodes = [ep for ep in episodes if ep.release_date.year == year]

    if title_search:
        search_lower = title_search.lower()
        episodes = [ep for ep in episodes if search_lower in ep.title.lower()]

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
