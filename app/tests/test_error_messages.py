"""Each HTTP error names the offending show or parameter, a stable code and the next request to make."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.exceptions import (
    ErrorCode,
    ExternalServiceError,
    InvalidParameterError,
    SeasonNotFoundError,
    ShowNotFoundError,
    UpstreamSource,
)
from app.models.schemas import EpisodeSchema, create_show_schema
from app.services import show_service
from app.services.show_service import is_show_catalogue_available

_SHOW = create_show_schema(epguides_key="test", title="Test Show")


def _episode(season: int, number: int, *, released: bool = True, year: int = 2020) -> EpisodeSchema:
    return EpisodeSchema(
        season=season,
        number=number,
        title=f"S{season}E{number}",
        release_date=date(year, 1, number),
        is_released=released,
    )


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_show", new_callable=AsyncMock, return_value=None)
async def test_unknown_show_names_key_code_and_search_hint(mock_get_show, async_client: AsyncClient):
    response = await async_client.get("/shows/BreakingBadd")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "show_not_found"
    assert body["detail"] == (
        "Show not found: 'BreakingBadd'. Expected an epguides key such as 'BreakingBad' (case-insensitive, no spaces)."
    )
    assert "GET /shows/search?query=<title>" in body["hint"]
    assert body["context"] == {"epguides_key": "BreakingBadd"}
    assert body["request_id"]


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_show", new_callable=AsyncMock, return_value=None)
async def test_unknown_show_with_unreachable_catalogue_is_503_upstream_unavailable(
    mock_get_show, show_catalogue_available, async_client: AsyncClient
):
    show_catalogue_available.return_value = False

    response = await async_client.get("/shows/BreakingBad/episodes/next")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "upstream_unavailable"
    assert "epguides.com show catalogue could not be loaded" in body["detail"]
    assert "'BreakingBad'" in body["detail"]
    assert body["context"] == {"upstream_source": "epguides.com", "epguides_key": "BreakingBad"}
    assert "/health/ready" in body["hint"]


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_show", new_callable=AsyncMock, return_value=_SHOW)
@patch("app.api.endpoints.shows.show_service.get_episodes", new_callable=AsyncMock)
async def test_missing_season_lists_available_seasons(mock_get_episodes, mock_get_show, async_client: AsyncClient):
    mock_get_episodes.return_value = [_episode(1, 1), _episode(2, 1), _episode(2, 2)]

    response = await async_client.get("/shows/test/seasons/9/episodes")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "season_not_found"
    assert body["detail"] == "Season 9 not found for show 'test'. Available seasons: 1, 2."
    assert body["hint"] == "List seasons with GET /shows/test/seasons."
    assert body["context"] == {"epguides_key": "test", "season": 9, "available_seasons": [1, 2]}


@pytest.mark.asyncio
async def test_episode_filter_without_season_is_rejected_with_field_error(async_client: AsyncClient):
    response = await async_client.get("/shows/test/episodes?episode=5")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["detail"] == (
        "Invalid query parameter episode=5: the episode filter requires season, as in ?season=1&episode=5."
    )
    assert body["errors"] == [
        {
            "loc": ["query", "episode"],
            "msg": "the episode filter requires season, as in ?season=1&episode=5",
            "type": "value_error",
            "input": 5,
        }
    ]


@pytest.mark.asyncio
async def test_query_validation_error_names_field_and_offending_value(async_client: AsyncClient):
    response = await async_client.get("/shows/?page=0&limit=500")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert "query.page='0': Input should be greater than or equal to 1" in body["detail"]
    assert "query.limit='500': Input should be less than or equal to 100" in body["detail"]
    assert body["detail"].endswith("See /docs for each parameter's accepted values.")
    assert [error["loc"] for error in body["errors"]] == [["query", "page"], ["query", "limit"]]


@pytest.mark.asyncio
async def test_invalid_imdb_id_names_value_and_example(async_client: AsyncClient):
    response = await async_client.get("/shows/by-imdb/0903747")

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_imdb_id"
    assert body["detail"] == (
        "Invalid IMDB ID format: '0903747' (expected 'tt' followed by digits, for example 'tt0903747')."
    )


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_show_by_imdb_id", new_callable=AsyncMock, return_value=None)
async def test_unknown_imdb_id_explains_why_and_how_to_search(mock_lookup, async_client: AsyncClient):
    response = await async_client.get("/shows/by-imdb/tt0000001")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "imdb_id_not_found"
    assert body["detail"].startswith("No show found for IMDB ID: tt0000001. TVMaze has no record of it")
    assert body["context"] == {"imdb_id": "tt0000001"}


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_show", new_callable=AsyncMock)
async def test_finished_show_states_end_date_and_points_to_latest(mock_get_show, async_client: AsyncClient):
    mock_get_show.return_value = create_show_schema(epguides_key="bb", title="Breaking Bad", end_date=date(2013, 9, 29))

    response = await async_client.get("/shows/BreakingBad/episodes/next")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "show_finished"
    assert body["detail"] == ("Show has finished airing: 'BreakingBad' ended on 2013-09-29, so it has no next episode.")
    assert body["hint"] == "Use GET /shows/BreakingBad/episodes/latest for the final episode."


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_show", new_callable=AsyncMock, return_value=_SHOW)
@patch("app.api.endpoints.shows.show_service.get_episodes", new_callable=AsyncMock)
async def test_no_upcoming_episode_names_show_and_points_to_latest(
    mock_get_episodes, mock_get_show, async_client: AsyncClient
):
    mock_get_episodes.return_value = [_episode(1, 1)]

    response = await async_client.get("/shows/test/episodes/next")

    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "no_upcoming_episode"
    assert body["detail"].startswith("No unreleased episodes found for show 'test'")
    assert body["hint"] == "Use GET /shows/test/episodes/latest for the most recent episode."


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_show", new_callable=AsyncMock, return_value=_SHOW)
@patch("app.api.endpoints.shows.show_service.get_episodes", new_callable=AsyncMock, return_value=[])
async def test_empty_episode_list_suggests_refresh(mock_get_episodes, mock_get_show, async_client: AsyncClient):
    response = await async_client.get("/shows/test/episodes/latest")

    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "no_episodes"
    assert body["detail"].startswith("No episodes found for show 'test'")
    assert body["hint"] == "Retry with GET /shows/test/episodes?refresh=true to re-fetch from upstream."


@pytest.mark.asyncio
@patch("app.api.endpoints.shows.show_service.get_episodes", new_callable=AsyncMock)
async def test_only_future_episodes_points_to_next(mock_get_episodes, async_client: AsyncClient):
    mock_get_episodes.return_value = [_episode(1, 1, released=False, year=2099)]

    response = await async_client.get("/shows/test/episodes/latest")

    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "no_released_episode"
    assert body["detail"] == "No released episodes found for show 'test': every listed episode airs in the future."
    assert body["hint"] == "Use GET /shows/test/episodes/next for the first air date."


@pytest.mark.asyncio
async def test_unknown_route_names_method_and_path(async_client: AsyncClient):
    response = await async_client.get("/nope/nothing")

    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "route_not_found"
    assert body["detail"] == "No route matches GET /nope/nothing. See /docs for the available endpoints."


def test_error_codes_are_stable_wire_values():
    assert {code.value for code in ErrorCode} == {
        "show_not_found",
        "season_not_found",
        "no_episodes",
        "no_released_episode",
        "no_upcoming_episode",
        "show_finished",
        "invalid_imdb_id",
        "imdb_id_not_found",
        "upstream_unavailable",
        "validation_error",
        "route_not_found",
        "internal_error",
    }


def test_season_not_found_with_no_episodes_lists_none():
    error = SeasonNotFoundError("test", 1, [])

    assert error.message == "Season 1 not found for show 'test'. Available seasons: none."
    assert error.context["available_seasons"] == []


def test_external_service_error_without_source_omits_it_from_context():
    error = ExternalServiceError("Redis is unreachable at the configured REDIS_URL")

    assert error.source is None
    assert error.to_payload() == {
        "detail": "Redis is unreachable at the configured REDIS_URL",
        "code": "upstream_unavailable",
        "hint": "Retry in a few minutes; GET /health/ready reports upstream freshness.",
    }


def test_typed_errors_keep_their_cause():
    cause = TimeoutError("read timed out")
    try:
        try:
            raise cause
        except TimeoutError as err:
            message = "TVMaze timed out"
            raise ExternalServiceError(message, source=UpstreamSource.TVMAZE) from err
    except ExternalServiceError as error:
        assert error.__cause__ is cause


def test_show_not_found_and_invalid_parameter_are_client_visible():
    assert ShowNotFoundError("x").is_client_visible
    assert InvalidParameterError("episode", 1, "needs season").is_client_visible


@pytest.mark.asyncio
@patch("app.services.show_service.cache_exists", new_callable=AsyncMock, return_value=True)
async def test_catalogue_available_when_cached(mock_exists):
    assert await is_show_catalogue_available() is True


@pytest.mark.asyncio
@patch("app.services.show_service.cache_exists", new_callable=AsyncMock, return_value=False)
async def test_catalogue_unavailable_when_uncached_and_upstream_empty(mock_exists):
    with patch.object(show_service, "_get_all_shows_raw", new=AsyncMock(return_value=[])):
        assert await is_show_catalogue_available() is False


@pytest.mark.asyncio
@patch("app.services.show_service.cache_exists", new_callable=AsyncMock, return_value=False)
async def test_catalogue_available_when_upstream_fetch_succeeds(mock_exists):
    with patch.object(show_service, "_get_all_shows_raw", new=AsyncMock(return_value=[{"epguides_key": "x"}])):
        assert await is_show_catalogue_available() is True
