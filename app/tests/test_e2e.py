"""
Comprehensive end-to-end tests for Epguides API.

Tests the full stack from HTTP requests to service responses.
"""

from datetime import date
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.schemas import EpisodeSchema, create_show_schema


@pytest.fixture
async def async_client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """Test health check endpoint."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_root_redirects_to_docs(async_client: AsyncClient):
    """Test root URL redirects to documentation."""
    response = await async_client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert "/docs" in response.headers.get("location", "")


@pytest.mark.asyncio
@patch("app.services.show_service.get_shows_page")
async def test_list_shows_end_to_end(mock_get_shows_page, async_client: AsyncClient):
    """Test listing shows with pagination."""
    mock_shows = [
        create_show_schema(
            epguides_key="test1",
            title="Test Show 1",
            network="Network 1",
            imdb_id="tt1234567",
            run_time_min=60,
            start_date=date(2000, 1, 1),
            end_date=date(2001, 1, 1),
            country="USA",
            total_episodes=10,
        ),
    ]
    mock_get_shows_page.return_value = (mock_shows, 2)  # Returns (page_items, total)

    response = await async_client.get("/shows/?page=1&limit=1")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Test Show 1"
    assert data["total"] == 2
    assert data["has_next"] is True


@pytest.mark.asyncio
@patch("app.services.show_service.search_shows_fast")
async def test_search_shows_end_to_end(mock_search_shows_fast, async_client: AsyncClient):
    """Test searching shows."""
    mock_shows = [
        create_show_schema(
            epguides_key="breakingbad",
            title="Breaking Bad",
            imdb_id=None,
            network=None,
            run_time_min=None,
            start_date=None,
            end_date=None,
            country=None,
            total_episodes=None,
        )
    ]
    mock_search_shows_fast.return_value = mock_shows

    response = await async_client.get("/shows/search?query=breaking")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Breaking Bad"


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
async def test_get_show_metadata_end_to_end(mock_get_show, async_client: AsyncClient):
    """Test getting show metadata."""
    mock_show = create_show_schema(
        epguides_key="breakingbad",
        title="Breaking Bad",
        imdb_id="tt0903747",
        network="AMC",
        run_time_min=None,
        start_date=None,
        end_date=None,
        country=None,
        total_episodes=None,
    )
    mock_get_show.return_value = mock_show

    response = await async_client.get("/shows/breakingbad")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Breaking Bad"
    assert data["imdb_id"] == "tt0903747"
    assert data["network"] == "AMC"


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
async def test_get_show_not_found(mock_get_show, async_client: AsyncClient):
    """Test 404 when show doesn't exist."""
    mock_get_show.return_value = None

    response = await async_client.get("/shows/nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
async def test_get_episodes_end_to_end(mock_get_episodes, mock_get_show, async_client: AsyncClient):
    """Test getting episodes for a show."""
    mock_show = create_show_schema(
        epguides_key="breakingbad",
        title="Breaking Bad",
        imdb_id=None,
        network=None,
        run_time_min=None,
        start_date=None,
        end_date=None,
        country=None,
        total_episodes=None,
    )
    mock_get_show.return_value = mock_show

    mock_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="Pilot",
            release_date=date(2008, 1, 20),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        ),
        EpisodeSchema(
            season=1,
            number=2,
            title="Cat's in the Bag...",
            release_date=date(2008, 1, 27),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        ),
    ]
    mock_get_episodes.return_value = mock_episodes

    response = await async_client.get("/shows/breakingbad/episodes")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "Pilot"
    assert data[0]["season"] == 1
    assert data[0]["number"] == 1


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
async def test_get_episodes_with_filter(mock_get_episodes, mock_get_show, async_client: AsyncClient):
    """Test episode filtering."""
    mock_show = create_show_schema(
        epguides_key="breakingbad",
        title="Breaking Bad",
        imdb_id=None,
        network=None,
        run_time_min=None,
        start_date=None,
        end_date=None,
        country=None,
        total_episodes=None,
    )
    mock_get_show.return_value = mock_show

    all_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="Pilot",
            release_date=date(2008, 1, 20),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        ),
        EpisodeSchema(
            season=2,
            number=1,
            title="Seven Thirty-Seven",
            release_date=date(2009, 3, 8),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        ),
    ]
    mock_get_episodes.return_value = all_episodes

    response = await async_client.get("/shows/breakingbad/episodes?season=2")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["season"] == 2


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
async def test_get_show_details_end_to_end(mock_get_episodes, mock_get_show, async_client: AsyncClient):
    """Test getting full show details."""
    mock_show = create_show_schema(
        epguides_key="breakingbad",
        title="Breaking Bad",
        imdb_id=None,
        network=None,
        run_time_min=None,
        start_date=None,
        end_date=None,
        country=None,
        total_episodes=None,
    )
    mock_get_show.return_value = mock_show

    mock_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="Pilot",
            release_date=date(2008, 1, 20),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        )
    ]
    mock_get_episodes.return_value = mock_episodes

    response = await async_client.get("/shows/breakingbad?include=episodes")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Breaking Bad"
    assert "episodes" in data
    assert len(data["episodes"]) == 1


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
async def test_get_next_episode_end_to_end(mock_get_episodes, mock_get_show, async_client: AsyncClient):
    """Test getting next unreleased episode."""
    mock_show = create_show_schema(
        epguides_key="breakingbad",
        title="Breaking Bad",
        end_date=None,  # Show is not finished
    )
    mock_get_show.return_value = mock_show

    mock_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="Released",
            release_date=date(2000, 1, 1),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        ),
        EpisodeSchema(
            season=1,
            number=2,
            title="Next",
            release_date=date(2030, 1, 1),
            is_released=False,
            run_time_min=None,
            episode_number=None,
        ),
    ]
    mock_get_episodes.return_value = mock_episodes

    response = await async_client.get("/shows/breakingbad/episodes/next")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Next"
    assert data["is_released"] is False


@pytest.mark.asyncio
@patch("app.services.show_service.get_episodes")
async def test_get_latest_episode_end_to_end(mock_get_episodes, async_client: AsyncClient):
    """Test getting latest released episode."""
    mock_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="First",
            release_date=date(2000, 1, 1),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        ),
        EpisodeSchema(
            season=1,
            number=2,
            title="Last",
            release_date=date(2000, 1, 8),
            is_released=True,
            run_time_min=None,
            episode_number=None,
        ),
        EpisodeSchema(
            season=1,
            number=3,
            title="Future",
            release_date=date(2030, 1, 1),
            is_released=False,
            run_time_min=None,
            episode_number=None,
        ),
    ]
    mock_get_episodes.return_value = mock_episodes

    response = await async_client.get("/shows/breakingbad/episodes/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Last"
    assert data["is_released"] is True


@pytest.mark.asyncio
async def test_validation_errors(async_client: AsyncClient):
    """Test request validation."""
    # Invalid pagination
    response = await async_client.get("/shows/?page=0")
    assert response.status_code == 422

    # Search query too short
    response = await async_client.get("/shows/search?query=a")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_error_handling(async_client: AsyncClient):
    """Test error handling for missing resources."""
    response = await async_client.get("/shows/nonexistentshow")
    assert response.status_code == 404

    response = await async_client.get("/shows/nonexistentshow/episodes")
    assert response.status_code == 404


# =============================================================================
# LLM Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_llm_health_endpoint(async_client: AsyncClient):
    """Test LLM health check endpoint returns correct structure."""
    response = await async_client.get("/health/llm")
    assert response.status_code == 200
    data = response.json()
    assert "enabled" in data
    assert "configured" in data
    assert "api_url" in data
    assert isinstance(data["enabled"], bool)


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
@patch("app.services.llm_service.parse_natural_language_query")
async def test_nlq_parameter_calls_llm_service(
    mock_llm_parse, mock_get_episodes, mock_get_show, async_client: AsyncClient
):
    """Test that nlq parameter triggers LLM service call."""
    mock_show = create_show_schema(epguides_key="test", title="Test Show")
    mock_get_show.return_value = mock_show

    all_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="Pilot",
            release_date=date(2008, 1, 20),
            is_released=True,
            run_time_min=None,
            episode_number=1,
        ),
        EpisodeSchema(
            season=1,
            number=2,
            title="Second",
            release_date=date(2008, 1, 27),
            is_released=True,
            run_time_min=None,
            episode_number=2,
        ),
        EpisodeSchema(
            season=1,
            number=3,
            title="Finale",
            release_date=date(2008, 2, 3),
            is_released=True,
            run_time_min=None,
            episode_number=3,
        ),
    ]
    mock_get_episodes.return_value = all_episodes

    # LLM returns only the "Finale" episode
    mock_llm_parse.return_value = [
        {
            "season": 1,
            "number": 3,
            "title": "Finale",
            "release_date": "2008-02-03",
            "is_released": True,
            "run_time_min": None,
            "episode_number": 3,
        }
    ]

    response = await async_client.get("/shows/test/episodes?nlq=finale+episode")
    assert response.status_code == 200

    # Verify LLM service was called
    mock_llm_parse.assert_called_once()
    call_args = mock_llm_parse.call_args
    assert call_args[0][0] == "finale episode"  # Query
    assert len(call_args[0][1]) == 3  # All episodes passed to LLM

    # Verify filtered result
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Finale"


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
@patch("app.services.llm_service.parse_natural_language_query")
async def test_nlq_graceful_fallback_when_llm_fails(
    mock_llm_parse, mock_get_episodes, mock_get_show, async_client: AsyncClient
):
    """Test that nlq returns all episodes when LLM fails."""
    mock_show = create_show_schema(epguides_key="test", title="Test Show")
    mock_get_show.return_value = mock_show

    all_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="Pilot",
            release_date=date(2008, 1, 20),
            is_released=True,
            run_time_min=None,
            episode_number=1,
        ),
        EpisodeSchema(
            season=1,
            number=2,
            title="Second",
            release_date=date(2008, 1, 27),
            is_released=True,
            run_time_min=None,
            episode_number=2,
        ),
    ]
    mock_get_episodes.return_value = all_episodes

    # LLM returns None (failure)
    mock_llm_parse.return_value = None

    response = await async_client.get("/shows/test/episodes?nlq=some+query")
    assert response.status_code == 200

    # Should return all episodes as fallback
    data = response.json()
    assert len(data) == 2


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
@patch("app.services.llm_service.parse_natural_language_query")
async def test_nlq_combined_with_structured_filters(
    mock_llm_parse, mock_get_episodes, mock_get_show, async_client: AsyncClient
):
    """Test that structured filters are applied before nlq."""
    mock_show = create_show_schema(epguides_key="test", title="Test Show")
    mock_get_show.return_value = mock_show

    all_episodes = [
        EpisodeSchema(
            season=1,
            number=1,
            title="S1 Pilot",
            release_date=date(2008, 1, 20),
            is_released=True,
            run_time_min=None,
            episode_number=1,
        ),
        EpisodeSchema(
            season=2,
            number=1,
            title="S2 Premiere",
            release_date=date(2009, 1, 20),
            is_released=True,
            run_time_min=None,
            episode_number=2,
        ),
        EpisodeSchema(
            season=2,
            number=2,
            title="S2 Finale",
            release_date=date(2009, 1, 27),
            is_released=True,
            run_time_min=None,
            episode_number=3,
        ),
    ]
    mock_get_episodes.return_value = all_episodes

    # LLM only gets season 2 episodes (after structured filter)
    mock_llm_parse.return_value = [
        {
            "season": 2,
            "number": 2,
            "title": "S2 Finale",
            "release_date": "2009-01-27",
            "is_released": True,
            "run_time_min": None,
            "episode_number": 3,
        }
    ]

    response = await async_client.get("/shows/test/episodes?season=2&nlq=finale")
    assert response.status_code == 200

    # LLM should only receive season 2 episodes
    call_args = mock_llm_parse.call_args
    episodes_passed_to_llm = call_args[0][1]
    assert len(episodes_passed_to_llm) == 2  # Only S2 episodes
    assert all(ep["season"] == 2 for ep in episodes_passed_to_llm)

    # Result should be the filtered finale
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "S2 Finale"


# =============================================================================
# Live LLM Integration Test (only runs if LLM is configured)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (settings.LLM_ENABLED and settings.LLM_API_URL),
    reason="LLM not configured - set LLM_ENABLED=true and LLM_API_URL in .env to run this test",
)
async def test_llm_live_integration():
    """
    Live integration test that makes a real LLM API call.

    This test only runs when LLM is properly configured.
    It verifies the LLM endpoint is reachable and responds correctly.
    """

    from app.services import llm_service

    # Test data - simple episodes
    test_episodes = [
        {"season": 1, "number": 1, "title": "Pilot", "release_date": "2020-01-01"},
        {"season": 1, "number": 2, "title": "The Beginning", "release_date": "2020-01-08"},
        {"season": 1, "number": 10, "title": "Season Finale", "release_date": "2020-03-15"},
        {"season": 2, "number": 1, "title": "New Season", "release_date": "2021-01-01"},
        {"season": 2, "number": 10, "title": "Series Finale", "release_date": "2021-03-15"},
    ]

    # Make a real LLM call
    result = await llm_service.parse_natural_language_query("finale episodes", test_episodes)

    # Verify LLM responded (not None = success)
    assert result is not None, "LLM should return a result when properly configured"

    # Verify result is a list
    assert isinstance(result, list), "LLM should return a list of episodes"

    # Verify result is a subset of input (LLM filtered something)
    assert len(result) <= len(test_episodes), "LLM should return same or fewer episodes"

    # Log for visibility
    print(f"\n  LLM filtered {len(test_episodes)} episodes to {len(result)}")
    if result:
        print(f"  Returned: {[ep.get('title') for ep in result]}")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (settings.LLM_ENABLED and settings.LLM_API_URL),
    reason="LLM not configured - set LLM_ENABLED=true and LLM_API_URL in .env to run this test",
)
async def test_llm_live_api_health():
    """
    Live test that verifies the LLM API endpoint is reachable.

    This test only runs when LLM is properly configured.
    """
    import httpx

    # Try to reach the LLM API
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Most OpenAI-compatible APIs have a /models endpoint
            response = await client.get(
                f"{settings.LLM_API_URL}/models",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"} if settings.LLM_API_KEY else {},
            )
            # Accept 200 (success) or 401/403 (auth issue but endpoint exists)
            assert response.status_code in [
                200,
                401,
                403,
            ], f"LLM API should be reachable, got status {response.status_code}"
            print(f"\n  LLM API responded with status {response.status_code}")
        except httpx.ConnectError as e:
            pytest.fail(f"Could not connect to LLM API at {settings.LLM_API_URL}: {e}")
