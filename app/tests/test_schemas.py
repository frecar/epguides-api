"""
Tests for Pydantic schemas and model validation.

Tests computed fields, factory functions, validation constraints,
and serialization behavior for all schema types.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.responses import PaginatedResponse
from app.models.schemas import (
    EpisodeSchema,
    SeasonSchema,
    ShowDetailsSchema,
    ShowListSchema,
    ShowSchema,
    create_show_schema,
)


# =============================================================================
# EpisodeSchema Tests
# =============================================================================


def test_episode_schema_valid():
    """Test creating a valid episode schema."""
    ep = EpisodeSchema(
        number=1,
        season=1,
        title="Pilot",
        release_date=date(2020, 1, 15),
        is_released=True,
    )
    assert ep.number == 1
    assert ep.season == 1
    assert ep.title == "Pilot"
    assert ep.release_date == date(2020, 1, 15)
    assert ep.is_released is True
    assert ep.run_time_min is None
    assert ep.episode_number is None
    assert ep.summary is None
    assert ep.poster_url is None


def test_episode_schema_with_all_fields():
    """Test episode schema with all optional fields."""
    ep = EpisodeSchema(
        number=5,
        season=2,
        title="The One Where...",
        release_date=date(2021, 3, 10),
        is_released=True,
        run_time_min=45,
        episode_number=15,
        summary="A great episode.",
        poster_url="https://example.com/ep.jpg",
    )
    assert ep.run_time_min == 45
    assert ep.episode_number == 15
    assert ep.summary == "A great episode."
    assert ep.poster_url == "https://example.com/ep.jpg"


def test_episode_schema_season_zero_for_specials():
    """Test that season 0 is valid (for specials)."""
    ep = EpisodeSchema(
        number=1,
        season=0,
        title="Special",
        release_date=date(2020, 12, 25),
        is_released=True,
    )
    assert ep.season == 0


def test_episode_schema_rejects_negative_number():
    """Test that negative episode number is rejected."""
    with pytest.raises(ValidationError):
        EpisodeSchema(
            number=0,
            season=1,
            title="Invalid",
            release_date=date(2020, 1, 1),
            is_released=True,
        )


def test_episode_schema_rejects_negative_season():
    """Test that negative season is rejected."""
    with pytest.raises(ValidationError):
        EpisodeSchema(
            number=1,
            season=-1,
            title="Invalid",
            release_date=date(2020, 1, 1),
            is_released=True,
        )


def test_episode_schema_rejects_empty_title():
    """Test that empty title is rejected."""
    with pytest.raises(ValidationError):
        EpisodeSchema(
            number=1,
            season=1,
            title="",
            release_date=date(2020, 1, 1),
            is_released=True,
        )


def test_episode_schema_rejects_zero_runtime():
    """Test that zero runtime is rejected (must be >= 1)."""
    with pytest.raises(ValidationError):
        EpisodeSchema(
            number=1,
            season=1,
            title="Test",
            release_date=date(2020, 1, 1),
            is_released=True,
            run_time_min=0,
        )


# =============================================================================
# SeasonSchema Tests
# =============================================================================


def test_season_schema_valid():
    """Test creating a valid season schema."""
    season = SeasonSchema(
        number=1,
        episode_count=10,
        api_episodes_url="http://localhost:3000/shows/test/seasons/1/episodes",
    )
    assert season.number == 1
    assert season.episode_count == 10
    assert season.premiere_date is None
    assert season.end_date is None
    assert season.poster_url is None
    assert season.summary is None


def test_season_schema_with_all_fields():
    """Test season schema with all optional fields."""
    season = SeasonSchema(
        number=2,
        episode_count=8,
        premiere_date=date(2021, 1, 10),
        end_date=date(2021, 3, 5),
        poster_url="https://example.com/s2.jpg",
        summary="The second season.",
        api_episodes_url="http://localhost:3000/shows/test/seasons/2/episodes",
    )
    assert season.premiere_date == date(2021, 1, 10)
    assert season.end_date == date(2021, 3, 5)
    assert season.poster_url == "https://example.com/s2.jpg"
    assert season.summary == "The second season."


def test_season_schema_zero_episodes():
    """Test season with zero episodes is valid."""
    season = SeasonSchema(
        number=0,
        episode_count=0,
        api_episodes_url="http://localhost:3000/shows/test/seasons/0/episodes",
    )
    assert season.episode_count == 0


def test_season_schema_rejects_negative_episode_count():
    """Test that negative episode count is rejected."""
    with pytest.raises(ValidationError):
        SeasonSchema(
            number=1,
            episode_count=-1,
            api_episodes_url="http://localhost:3000/shows/test/seasons/1/episodes",
        )


# =============================================================================
# ShowListSchema Tests
# =============================================================================


def test_show_list_schema_computed_fields():
    """Test computed URL fields on ShowListSchema."""
    show = ShowListSchema(
        epguides_key="BreakingBad",
        title="Breaking Bad",
    )
    assert "BreakingBad" in show.external_epguides_url
    assert "epguides.com" in show.external_epguides_url
    assert "BreakingBad" in show.api_self_url
    assert "/shows/" in show.api_self_url


def test_show_list_schema_with_metadata():
    """Test ShowListSchema with optional metadata."""
    show = ShowListSchema(
        epguides_key="BreakingBad",
        title="Breaking Bad",
        network="AMC",
        country="US",
        start_date=date(2008, 1, 20),
        end_date=date(2013, 9, 29),
    )
    assert show.network == "AMC"
    assert show.country == "US"
    assert show.start_date == date(2008, 1, 20)
    assert show.end_date == date(2013, 9, 29)


# =============================================================================
# ShowSchema Tests
# =============================================================================


def test_show_schema_computed_fields():
    """Test all computed URL fields on ShowSchema."""
    show = ShowSchema(
        epguides_key="BreakingBad",
        title="Breaking Bad",
        imdb_id="tt0903747",
    )
    assert "BreakingBad" in show.external_epguides_url
    assert "tt0903747" in show.external_imdb_url
    assert "imdb.com" in show.external_imdb_url
    assert "/shows/BreakingBad" in show.api_self_url
    assert "/shows/BreakingBad/seasons" in show.api_seasons_url
    assert "/shows/BreakingBad/episodes" in show.api_episodes_url
    assert "/shows/BreakingBad/episodes/next" in show.api_next_episode_url
    assert "/shows/BreakingBad/episodes/latest" in show.api_latest_episode_url


def test_show_schema_imdb_url_none_without_id():
    """Test external_imdb_url is None when no IMDB ID."""
    show = ShowSchema(
        epguides_key="TestShow",
        title="Test Show",
    )
    assert show.external_imdb_url is None


def test_show_schema_with_all_optional_fields():
    """Test ShowSchema with all optional fields populated."""
    show = ShowSchema(
        epguides_key="BreakingBad",
        title="Breaking Bad",
        imdb_id="tt0903747",
        network="AMC",
        run_time_min=60,
        start_date=date(2008, 1, 20),
        end_date=date(2013, 9, 29),
        country="US",
        total_episodes=62,
        poster_url="https://example.com/poster.jpg",
    )
    assert show.network == "AMC"
    assert show.run_time_min == 60
    assert show.total_episodes == 62
    assert show.poster_url == "https://example.com/poster.jpg"


def test_show_schema_rejects_zero_runtime():
    """Test that zero runtime is rejected."""
    with pytest.raises(ValidationError):
        ShowSchema(
            epguides_key="Test",
            title="Test",
            run_time_min=0,
        )


def test_show_schema_rejects_negative_total_episodes():
    """Test that negative total episodes is rejected."""
    with pytest.raises(ValidationError):
        ShowSchema(
            epguides_key="Test",
            title="Test",
            total_episodes=-1,
        )


# =============================================================================
# ShowDetailsSchema Tests
# =============================================================================


def test_show_details_schema_inherits_computed_fields():
    """Test ShowDetailsSchema inherits computed fields from ShowSchema."""
    show = ShowDetailsSchema(
        epguides_key="BreakingBad",
        title="Breaking Bad",
        imdb_id="tt0903747",
        episodes=[
            EpisodeSchema(
                number=1,
                season=1,
                title="Pilot",
                release_date=date(2008, 1, 20),
                is_released=True,
            ),
        ],
    )
    assert show.external_imdb_url is not None
    assert len(show.episodes) == 1
    assert show.episodes[0].title == "Pilot"


def test_show_details_schema_empty_episodes():
    """Test ShowDetailsSchema with empty episodes list."""
    show = ShowDetailsSchema(
        epguides_key="NewShow",
        title="New Show",
        episodes=[],
    )
    assert show.episodes == []


# =============================================================================
# create_show_schema Factory Tests
# =============================================================================


def test_create_show_schema_minimal():
    """Test factory with only required fields."""
    show = create_show_schema(epguides_key="test", title="Test Show")
    assert show.epguides_key == "test"
    assert show.title == "Test Show"
    assert show.imdb_id is None
    assert show.network is None
    assert show.run_time_min is None
    assert show.start_date is None
    assert show.end_date is None
    assert show.country is None
    assert show.total_episodes is None
    assert show.poster_url is None


def test_create_show_schema_all_fields():
    """Test factory with all optional fields."""
    show = create_show_schema(
        epguides_key="bb",
        title="Breaking Bad",
        imdb_id="tt0903747",
        network="AMC",
        run_time_min=60,
        start_date=date(2008, 1, 20),
        end_date=date(2013, 9, 29),
        country="US",
        total_episodes=62,
        poster_url="https://example.com/poster.jpg",
    )
    assert show.imdb_id == "tt0903747"
    assert show.network == "AMC"
    assert show.run_time_min == 60
    assert show.start_date == date(2008, 1, 20)
    assert show.end_date == date(2013, 9, 29)
    assert show.country == "US"
    assert show.total_episodes == 62
    assert show.poster_url == "https://example.com/poster.jpg"


def test_create_show_schema_returns_show_schema():
    """Test factory returns a ShowSchema instance."""
    show = create_show_schema(epguides_key="test", title="Test")
    assert isinstance(show, ShowSchema)


def test_create_show_schema_computed_fields_work():
    """Test computed fields work on factory-created instances."""
    show = create_show_schema(
        epguides_key="TestShow",
        title="Test Show",
        imdb_id="tt1234567",
    )
    assert "TestShow" in show.api_self_url
    assert "tt1234567" in show.external_imdb_url


# =============================================================================
# PaginatedResponse Tests
# =============================================================================


def test_paginated_response_basic():
    """Test basic PaginatedResponse creation."""
    response = PaginatedResponse(
        items=["a", "b", "c"],
        total=10,
        page=1,
        limit=3,
        has_next=True,
        has_previous=False,
    )
    assert response.items == ["a", "b", "c"]
    assert response.total == 10
    assert response.page == 1
    assert response.limit == 3
    assert response.has_next is True
    assert response.has_previous is False


def test_paginated_response_empty_items():
    """Test PaginatedResponse with empty items list."""
    response = PaginatedResponse(
        items=[],
        total=0,
        page=1,
        limit=10,
        has_next=False,
        has_previous=False,
    )
    assert response.items == []
    assert response.total == 0


def test_paginated_response_last_page():
    """Test PaginatedResponse on last page."""
    response = PaginatedResponse(
        items=["x"],
        total=11,
        page=2,
        limit=10,
        has_next=False,
        has_previous=True,
    )
    assert response.has_next is False
    assert response.has_previous is True


def test_paginated_response_rejects_zero_page():
    """Test PaginatedResponse rejects page=0."""
    with pytest.raises(ValidationError):
        PaginatedResponse(
            items=[],
            total=0,
            page=0,
            limit=10,
            has_next=False,
            has_previous=False,
        )


def test_paginated_response_rejects_zero_limit():
    """Test PaginatedResponse rejects limit=0."""
    with pytest.raises(ValidationError):
        PaginatedResponse(
            items=[],
            total=0,
            page=1,
            limit=0,
            has_next=False,
            has_previous=False,
        )


def test_paginated_response_rejects_negative_total():
    """Test PaginatedResponse rejects negative total."""
    with pytest.raises(ValidationError):
        PaginatedResponse(
            items=[],
            total=-1,
            page=1,
            limit=10,
            has_next=False,
            has_previous=False,
        )


def test_paginated_response_serialization():
    """Test PaginatedResponse serializes correctly."""
    response = PaginatedResponse(
        items=[{"key": "value"}],
        total=1,
        page=1,
        limit=10,
        has_next=False,
        has_previous=False,
    )
    data = response.model_dump()
    assert data["items"] == [{"key": "value"}]
    assert data["total"] == 1
    assert data["page"] == 1


# =============================================================================
# Schema Serialization Tests
# =============================================================================


def test_show_schema_json_serialization():
    """Test ShowSchema JSON serialization includes computed fields."""
    show = create_show_schema(
        epguides_key="test",
        title="Test Show",
        imdb_id="tt1234567",
    )
    data = show.model_dump()
    assert "external_epguides_url" in data
    assert "external_imdb_url" in data
    assert "api_self_url" in data
    assert "api_seasons_url" in data
    assert "api_episodes_url" in data
    assert "api_next_episode_url" in data
    assert "api_latest_episode_url" in data


def test_episode_schema_serialization():
    """Test EpisodeSchema serializes all fields."""
    ep = EpisodeSchema(
        number=1,
        season=1,
        title="Pilot",
        release_date=date(2020, 1, 15),
        is_released=True,
        run_time_min=45,
        summary="Test summary",
    )
    data = ep.model_dump()
    assert data["number"] == 1
    assert data["title"] == "Pilot"
    assert data["run_time_min"] == 45
    assert data["summary"] == "Test summary"
    assert data["release_date"] == date(2020, 1, 15)
