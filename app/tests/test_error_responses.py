"""
Tests for API error response format and edge cases.

Covers error format consistency, pagination boundaries, combined filters,
NLQ graceful degradation, and season/episode edge cases not covered
by the main test_endpoints.py suite.
"""

from datetime import date
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.models.schemas import EpisodeSchema, create_show_schema

# =============================================================================
# Error Response Format Consistency
# =============================================================================


class TestErrorResponseFormat:
    """All error responses must include 'detail' and 'request_id' fields."""

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    async def test_404_show_has_detail_and_request_id(self, mock_get_show, async_client: AsyncClient):
        """404 from show endpoint includes detail and request_id."""
        mock_get_show.return_value = None
        response = await async_client.get("/shows/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "request_id" in data
        assert isinstance(data["detail"], str)

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    @patch("app.services.show_service.get_episodes")
    async def test_404_next_episode_has_detail_and_request_id(
        self, mock_get_episodes, mock_get_show, async_client: AsyncClient
    ):
        """404 from next episode endpoint includes detail and request_id."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test", end_date=date(2020, 1, 1))
        response = await async_client.get("/shows/test/episodes/next")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "request_id" in data

    @pytest.mark.asyncio
    async def test_422_validation_has_errors_and_request_id(self, async_client: AsyncClient):
        """422 validation error includes errors list and request_id."""
        response = await async_client.get("/shows/search?query=x")
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data
        assert "request_id" in data
        assert isinstance(data["errors"], list)
        assert len(data["errors"]) > 0


# =============================================================================
# Pagination Edge Cases
# =============================================================================


class TestPaginationEdgeCases:
    @pytest.mark.asyncio
    @patch("app.services.show_service.get_shows_page")
    async def test_last_page_has_next_false(self, mock_get_shows_page, async_client: AsyncClient):
        """Last page should have has_next=False."""
        mock_get_shows_page.return_value = (
            [create_show_schema(epguides_key="last", title="Last Show")],
            3,
        )
        response = await async_client.get("/shows/?page=3&limit=1")
        assert response.status_code == 200
        data = response.json()
        assert data["has_next"] is False
        assert data["has_previous"] is True

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_shows_page")
    async def test_empty_page_beyond_total(self, mock_get_shows_page, async_client: AsyncClient):
        """Page beyond total returns empty items."""
        mock_get_shows_page.return_value = ([], 5)
        response = await async_client.get("/shows/?page=100&limit=50")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 5
        assert data["has_previous"] is True

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_shows_page")
    async def test_first_page_has_previous_false(self, mock_get_shows_page, async_client: AsyncClient):
        """First page should have has_previous=False."""
        mock_get_shows_page.return_value = (
            [create_show_schema(epguides_key="a", title="Show A")],
            10,
        )
        response = await async_client.get("/shows/?page=1&limit=1")
        assert response.status_code == 200
        data = response.json()
        assert data["has_previous"] is False
        assert data["has_next"] is True

    @pytest.mark.asyncio
    async def test_negative_page_rejected(self, async_client: AsyncClient):
        """Negative page number is rejected with 422."""
        response = await async_client.get("/shows/?page=-1")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_exceeding_max_rejected(self, async_client: AsyncClient):
        """Limit above max (100) is rejected with 422."""
        response = await async_client.get("/shows/?limit=101")
        assert response.status_code == 422


# =============================================================================
# Search Edge Cases
# =============================================================================


class TestSearchEdgeCases:
    @pytest.mark.asyncio
    async def test_search_missing_query_param(self, async_client: AsyncClient):
        """Missing query parameter returns 422."""
        response = await async_client.get("/shows/search")
        assert response.status_code == 422

    @pytest.mark.asyncio
    @patch("app.services.show_service.search_shows_fast")
    async def test_search_no_results(self, mock_search, async_client: AsyncClient):
        """Search with no matches returns empty list."""
        mock_search.return_value = []
        response = await async_client.get("/shows/search?query=zzzznonexistent")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    @patch("app.services.show_service.search_shows_fast")
    async def test_search_exact_min_length(self, mock_search, async_client: AsyncClient):
        """Search with exactly 2 characters (min_length) is accepted."""
        mock_search.return_value = []
        response = await async_client.get("/shows/search?query=bb")
        assert response.status_code == 200


# =============================================================================
# Episode Filter Combinations
# =============================================================================


class TestEpisodeFilterCombinations:
    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    @patch("app.services.show_service.get_episodes")
    async def test_season_and_year_combined_filter(self, mock_get_episodes, mock_get_show, async_client: AsyncClient):
        """Combining season and year filters narrows results correctly."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test")
        mock_get_episodes.return_value = [
            EpisodeSchema(
                season=1,
                number=1,
                title="S1E1",
                release_date=date(2020, 3, 1),
                is_released=True,
            ),
            EpisodeSchema(
                season=1,
                number=2,
                title="S1E2",
                release_date=date(2021, 3, 1),
                is_released=True,
            ),
            EpisodeSchema(
                season=2,
                number=1,
                title="S2E1",
                release_date=date(2021, 3, 15),
                is_released=True,
            ),
        ]
        response = await async_client.get("/shows/test/episodes?season=1&year=2021")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "S1E2"

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    @patch("app.services.show_service.get_episodes")
    async def test_title_search_case_insensitive(self, mock_get_episodes, mock_get_show, async_client: AsyncClient):
        """Title search is case-insensitive."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test")
        mock_get_episodes.return_value = [
            EpisodeSchema(
                season=1,
                number=1,
                title="THE PILOT",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
            EpisodeSchema(
                season=1,
                number=2,
                title="Something Else",
                release_date=date(2020, 1, 8),
                is_released=True,
            ),
        ]
        response = await async_client.get("/shows/test/episodes?title_search=pilot")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "THE PILOT"

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    @patch("app.services.show_service.get_episodes")
    async def test_filters_return_empty_for_existing_show(
        self, mock_get_episodes, mock_get_show, async_client: AsyncClient
    ):
        """Filters that match nothing on existing show return empty list."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test")
        mock_get_episodes.return_value = [
            EpisodeSchema(
                season=1,
                number=1,
                title="Pilot",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
        ]
        response = await async_client.get("/shows/test/episodes?year=1999")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_episode_filter_invalid_season(self, async_client: AsyncClient):
        """Season must be >= 1."""
        response = await async_client.get("/shows/test/episodes?season=0")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_episode_filter_invalid_year(self, async_client: AsyncClient):
        """Year outside valid range is rejected."""
        response = await async_client.get("/shows/test/episodes?year=1899")
        assert response.status_code == 422


# =============================================================================
# NLQ Graceful Degradation
# =============================================================================


class TestNLQGracefulDegradation:
    @pytest.mark.asyncio
    @patch("app.services.llm_service.parse_natural_language_query")
    @patch("app.services.show_service.get_episodes")
    async def test_nlq_failure_returns_all_episodes(self, mock_get_episodes, mock_llm, async_client: AsyncClient):
        """When LLM returns None (failure), all episodes are returned."""
        episodes = [
            EpisodeSchema(
                season=1,
                number=1,
                title="Pilot",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
            EpisodeSchema(
                season=1,
                number=2,
                title="Second",
                release_date=date(2020, 1, 8),
                is_released=True,
            ),
        ]
        mock_get_episodes.return_value = episodes
        mock_llm.return_value = None

        response = await async_client.get("/shows/test/episodes?nlq=best+episodes")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    @patch("app.services.llm_service.parse_natural_language_query")
    @patch("app.services.show_service.get_episodes")
    async def test_nlq_with_season_filter_prefilters(self, mock_get_episodes, mock_llm, async_client: AsyncClient):
        """NLQ is applied after structured filters."""
        episodes = [
            EpisodeSchema(
                season=1,
                number=1,
                title="S1 Pilot",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
            EpisodeSchema(
                season=2,
                number=1,
                title="S2 Opener",
                release_date=date(2021, 1, 1),
                is_released=True,
            ),
        ]
        mock_get_episodes.return_value = episodes
        mock_llm.return_value = None

        response = await async_client.get("/shows/test/episodes?season=1&nlq=anything")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["season"] == 1


# =============================================================================
# Season Endpoint Edge Cases
# =============================================================================


class TestSeasonEndpointEdgeCases:
    @pytest.mark.asyncio
    @patch("app.services.show_service.get_seasons")
    async def test_seasons_empty_for_existing_show(self, mock_get_seasons, async_client: AsyncClient):
        """Show with no seasons returns empty list when show exists."""
        mock_get_seasons.return_value = []
        with patch("app.services.show_service.get_show") as mock_get_show:
            mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test")
            response = await async_client.get("/shows/test/seasons")
            assert response.status_code == 200
            assert response.json() == []

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_episodes")
    @patch("app.services.show_service.get_show")
    async def test_season_episodes_nonexistent_season_existing_show(
        self, mock_get_show, mock_get_episodes, async_client: AsyncClient
    ):
        """Non-existent season on existing show returns 404."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test")
        mock_get_episodes.return_value = [
            EpisodeSchema(
                season=1,
                number=1,
                title="Pilot",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
        ]
        response = await async_client.get("/shows/test/seasons/5/episodes")
        assert response.status_code == 404
        assert "Season 5 not found" in response.json()["detail"]


# =============================================================================
# Next/Latest Episode Edge Cases
# =============================================================================


class TestNextLatestEpisodeEdgeCases:
    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    @patch("app.services.show_service.get_episodes")
    async def test_next_episode_multiple_unreleased_returns_first(
        self, mock_get_episodes, mock_get_show, async_client: AsyncClient
    ):
        """Multiple unreleased episodes: /next returns the first."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test")
        mock_get_episodes.return_value = [
            EpisodeSchema(
                season=1,
                number=1,
                title="Released",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
            EpisodeSchema(
                season=2,
                number=1,
                title="First Unreleased",
                release_date=date(2030, 1, 1),
                is_released=False,
            ),
            EpisodeSchema(
                season=2,
                number=2,
                title="Second Unreleased",
                release_date=date(2030, 2, 1),
                is_released=False,
            ),
        ]
        response = await async_client.get("/shows/test/episodes/next")
        assert response.status_code == 200
        assert response.json()["title"] == "First Unreleased"

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_episodes")
    async def test_latest_episode_returns_last_released(self, mock_get_episodes, async_client: AsyncClient):
        """Latest endpoint returns the last released episode."""
        mock_get_episodes.return_value = [
            EpisodeSchema(
                season=1,
                number=1,
                title="First",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
            EpisodeSchema(
                season=1,
                number=2,
                title="Latest Released",
                release_date=date(2020, 1, 8),
                is_released=True,
            ),
            EpisodeSchema(
                season=2,
                number=1,
                title="Upcoming",
                release_date=date(2030, 1, 1),
                is_released=False,
            ),
        ]
        response = await async_client.get("/shows/test/episodes/latest")
        assert response.status_code == 200
        assert response.json()["title"] == "Latest Released"


# =============================================================================
# Show Details with Include Parameter
# =============================================================================


class TestShowDetailsInclude:
    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    async def test_include_episodes_show_not_found(self, mock_get_show, async_client: AsyncClient):
        """include=episodes on non-existent show returns 404."""
        mock_get_show.return_value = None
        response = await async_client.get("/shows/nonexistent?include=episodes")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    @patch("app.services.show_service.get_episodes")
    async def test_include_episodes_returns_embedded_list(
        self, mock_get_episodes, mock_get_show, async_client: AsyncClient
    ):
        """include=episodes embeds episode list in show response."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test Show")
        mock_get_episodes.return_value = [
            EpisodeSchema(
                season=1,
                number=1,
                title="Pilot",
                release_date=date(2020, 1, 1),
                is_released=True,
            ),
        ]
        response = await async_client.get("/shows/test?include=episodes")
        assert response.status_code == 200
        data = response.json()
        assert "episodes" in data
        assert len(data["episodes"]) == 1
        assert data["title"] == "Test Show"

    @pytest.mark.asyncio
    @patch("app.services.show_service.get_show")
    async def test_include_invalid_value_returns_show_only(self, mock_get_show, async_client: AsyncClient):
        """include=invalid just returns the show without episodes."""
        mock_get_show.return_value = create_show_schema(epguides_key="test", title="Test Show")
        response = await async_client.get("/shows/test?include=invalid")
        assert response.status_code == 200
        data = response.json()
        assert "episodes" not in data
        assert data["title"] == "Test Show"
