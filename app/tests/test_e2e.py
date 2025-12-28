"""
Comprehensive end-to-end tests for Epguides API.

Tests the full stack from HTTP requests to service responses.
"""

from datetime import date
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.main import app
from app.models.schemas import EpisodeSchema, create_show_schema


@pytest.fixture
async def async_client():
    """Async HTTP client for testing."""
    async with AsyncClient(app=app, base_url="http://test") as client:
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
@patch("app.services.show_service.get_all_shows")
async def test_list_shows_end_to_end(mock_get_all_shows, async_client: AsyncClient):
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
        create_show_schema(
            epguides_key="test2",
            title="Test Show 2",
            network="Network 2",
            imdb_id=None,
            run_time_min=None,
            start_date=None,
            end_date=None,
            country=None,
            total_episodes=None,
        ),
    ]
    mock_get_all_shows.return_value = mock_shows

    response = await async_client.get("/shows/?page=1&limit=1")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Test Show 1"
    assert data["total"] == 2
    assert data["has_next"] is True


@pytest.mark.asyncio
@patch("app.services.show_service.search_shows")
async def test_search_shows_end_to_end(mock_search_shows, async_client: AsyncClient):
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
    mock_search_shows.return_value = mock_shows

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
