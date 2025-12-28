"""
API endpoints for TV show operations.

All endpoints are async and use dependency injection for services.
"""

from fastapi import APIRouter, HTTPException, Query

from app.models.responses import PaginatedResponse
from app.models.schemas import EpisodeSchema, ShowDetailsSchema, ShowListSchema, ShowSchema
from app.services import show_service

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[ShowListSchema], summary="List all shows")
async def list_shows(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(50, ge=1, le=100, description="Number of items per page"),
):
    """
    List all available shows with pagination.

    Returns a simplified paginated list of shows with basic information:
    - Title, epguides key, network, country
    - Start/end dates
    - Links to detailed show information

    For detailed information including IMDB ID, runtime, and episode count,
    use the individual show endpoint: GET /shows/{epguides_key}
    """
    all_shows = await show_service.get_all_shows()
    total = len(all_shows)
    start = (page - 1) * limit
    end = start + limit
    items = all_shows[start:end]

    # Convert to simplified list schema
    # Derive end_date for shows on current page if missing (cached, so efficient)
    simplified_items = []
    for show in items:
        end_date = show.end_date
        # If end_date is missing, try to derive it (only for current page)
        # This is efficient because get_show() caches episode data
        if not end_date:
            try:
                updated_show = await show_service.get_show(show.epguides_key)
                if updated_show and updated_show.end_date:
                    end_date = updated_show.end_date
            except Exception:
                # If derivation fails, use original end_date (None)
                pass

        simplified_items.append(
            ShowListSchema(
                epguides_key=show.epguides_key,
                title=show.title,
                network=show.network,
                country=show.country,
                start_date=show.start_date,
                end_date=end_date,
            )
        )

    return PaginatedResponse(
        items=simplified_items,
        total=total,
        page=page,
        limit=limit,
        has_next=end < total,
        has_previous=page > 1,
    )


@router.get("/search", response_model=list[ShowListSchema], summary="Search shows")
async def search_shows(query: str = Query(..., min_length=2, alias="q", description="Search query (show title)")):
    """
    Search for shows by title.

    Performs case-insensitive substring matching on show titles.
    Returns all shows where the query appears in the title.

    Returns simplified show information. For detailed information including IMDB ID,
    runtime, and episode count, use the individual show endpoint: GET /shows/{epguides_key}

    Supports both `query` and `q` parameter names for backward compatibility.
    """
    shows = await show_service.search_shows(query)

    # Convert to simplified list schema
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


@router.get("/{epguides_key}", summary="Get show metadata")
async def get_show_metadata(
    epguides_key: str,
    include: str | None = Query(None, description="Include related resources (e.g., 'episodes')"),
):
    """
    Get metadata for a show.

    Returns show information including:
    - Title, IMDB ID, epguides URL
    - Network, runtime, country
    - Start/end dates, total episodes

    The epguides_key is case-insensitive and "the" prefix is automatically handled.

    Use `?include=episodes` to also return the full episode list in the response.
    """
    show = await show_service.get_show(epguides_key)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    # If episodes are requested, return full show details
    if include == "episodes":
        episodes = await show_service.get_episodes(epguides_key)
        return ShowDetailsSchema(**show.model_dump(), episodes=episodes)

    return show


@router.get("/{epguides_key}/episodes", response_model=list[EpisodeSchema], summary="Get episodes")
async def get_show_episodes(
    epguides_key: str,
    season: int | None = Query(None, ge=1, description="Filter by season number"),
    episode: int | None = Query(None, ge=1, description="Filter by episode number (requires season)"),
    year: int | None = Query(None, ge=1900, le=2100, description="Filter by release year"),
    title_search: str | None = Query(None, description="Search in episode titles"),
    filter: str | None = Query(None, alias="q", description="Legacy filter string (e.g., 'season 2', 's2e5', '2008')"),
):
    """
    Get episodes for a show with optional filtering.

    Supports structured filtering via query parameters:
    - `season` - Filter by season number
    - `episode` - Filter by episode number (requires season)
    - `year` - Filter by release year
    - `title_search` - Search in episode titles

    Also supports legacy `filter` string for backward compatibility:
    - `season 2` or `s2` - Filter by season
    - `s2e5` - Specific season and episode
    - `2008` - Filter by release year
    - `fly` - Search in episode titles

    Examples:
    - `/shows/BreakingBad/episodes?season=2`
    - `/shows/BreakingBad/episodes?season=2&episode=5`
    - `/shows/BreakingBad/episodes?year=2008`
    - `/shows/BreakingBad/episodes?title_search=pilot`
    """
    # Get episodes (this will fail fast if show doesn't exist)
    episodes = await show_service.get_episodes(epguides_key, filter_query=filter)

    # Apply structured filters if provided
    if season is not None:
        episodes = [ep for ep in episodes if ep.season == season]
        if episode is not None:
            episodes = [ep for ep in episodes if ep.number == episode]

    if year is not None:
        episodes = [ep for ep in episodes if ep.release_date.year == year]

    if title_search:
        search_lower = title_search.lower()
        episodes = [ep for ep in episodes if search_lower in ep.title.lower()]

    # If no episodes returned, validate show exists
    # (Empty episodes list is valid if show exists but has no episodes)
    if not episodes:
        show = await show_service.get_show(epguides_key)
        if not show:
            raise HTTPException(status_code=404, detail="Show not found")

    return episodes


@router.get("/{epguides_key}/episodes/next", response_model=EpisodeSchema, summary="Get next episode")
async def get_next_episode(epguides_key: str):
    """
    Get the next unreleased episode.

    Returns the first episode that hasn't been released yet.
    Returns 404 if the show has finished airing (has end_date and all episodes are released).
    """
    # Check if show is finished first
    show = await show_service.get_show(epguides_key)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    # If show has an end_date, it's finished - no next episode
    if show.end_date:
        raise HTTPException(status_code=404, detail="Show has finished airing")

    episodes = await show_service.get_episodes(epguides_key)
    if not episodes:
        raise HTTPException(status_code=404, detail="Episodes not found")

    for ep in episodes:
        if not ep.is_released and ep.title:
            return ep

    # All episodes are released but show doesn't have end_date yet
    # This can happen if the show just finished but end_date hasn't been derived
    raise HTTPException(status_code=404, detail="No unreleased episodes found")


@router.get("/{epguides_key}/episodes/latest", response_model=EpisodeSchema, summary="Get latest episode")
async def get_latest_episode(epguides_key: str):
    """
    Get the latest released episode.

    Returns the most recently released episode for the show.
    Useful for checking the latest episode you should have watched.
    """
    episodes = await show_service.get_episodes(epguides_key)
    if not episodes:
        raise HTTPException(status_code=404, detail="Episodes not found")

    released = [ep for ep in episodes if ep.is_released]
    if not released:
        raise HTTPException(status_code=404, detail="No released episodes found")

    return released[-1]
