"""
Unit tests for service functions.

Tests business logic independently of HTTP layer.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS
from app.services import epguides, show_service


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_all_shows(mock_get_metadata):
    """Test retrieving all shows."""
    mock_data = [
        {
            "directory": "BreakingBad",
            "title": "Breaking Bad",
            "network": "AMC",
            "run time": "60 min",
        }
    ]
    mock_get_metadata.return_value = mock_data

    shows = await show_service.get_all_shows()
    assert len(shows) == 1
    assert shows[0].title == "Breaking Bad"
    assert shows[0].epguides_key == "BreakingBad"


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_search_shows(mock_get_metadata):
    """Test searching shows."""
    mock_data = [
        {
            "directory": "bb",
            "title": "Breaking Bad",
            "network": "AMC",
            "run time": "60 min",
        },
        {
            "directory": "got",
            "title": "Game of Thrones",
            "network": "HBO",
            "run time": "60 min",
        },
    ]
    mock_get_metadata.return_value = mock_data

    results = await show_service.search_shows("breaking")
    assert len(results) == 1
    assert results[0].title == "Breaking Bad"


def test_parse_date_string():
    """Test date parsing with various formats."""
    # Test standard format
    result = epguides.parse_date_string("20 Jan 08")
    assert result is not None
    assert result.year == 2008

    # Test alternative format
    result = epguides.parse_date_string("20/Jan/08")
    assert result is not None

    # Test invalid date
    result = epguides.parse_date_string("invalid")
    assert result is None

    # Test empty string
    result = epguides.parse_date_string("")
    assert result is None


def test_normalize_show_id():
    """Test show ID normalization."""
    assert show_service.normalize_show_id("BreakingBad") == "breakingbad"
    assert show_service.normalize_show_id("The Breaking Bad") == "breakingbad"
    assert show_service.normalize_show_id("THE OFFICE") == "office"


def test_parse_imdb_id():
    """Test IMDB ID parsing."""
    assert show_service._parse_imdb_id("tt0903747") == "tt0903747"
    assert show_service._parse_imdb_id("tt123456") == "tt0123456"  # Padded
    assert show_service._parse_imdb_id("invalid") == "invalid"


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_does_not_set_end_date_with_unreleased_episodes(mock_get_metadata, mock_get_episodes_data):
    """Test that get_show does NOT set end_date when there are unreleased episodes."""
    from datetime import datetime, timedelta

    from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS

    # Mock show data from epguides
    mock_get_metadata.return_value = [
        {
            "directory": "fallout",
            "title": "Fallout",
            "network": "Amazon",
            "run time": "60 min",
        }
    ]

    # Create episode data with:
    # - Some released episodes (old dates)
    # - Some unreleased episodes (future dates)
    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS)
    old_date = (threshold - timedelta(days=30)).strftime("%d %b %y")
    future_date = (datetime.now() + timedelta(days=30)).strftime("%d %b %y")

    mock_episodes_data = [
        {
            "season": 1,
            "number": 1,
            "title": "Released Episode",
            "release_date": old_date,
        },
        {
            "season": 1,
            "number": 2,
            "title": "Unreleased Episode",
            "release_date": future_date,
        },
    ]
    mock_get_episodes_data.return_value = mock_episodes_data

    result = await show_service.get_show("fallout")

    # Should NOT have end_date set because there are unreleased episodes
    assert result is not None
    assert result.end_date is None


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_sets_end_date_when_all_episodes_released(mock_get_metadata, mock_get_episodes_data):
    """Test that get_show DOES set end_date when all episodes are released."""
    from datetime import datetime, timedelta

    from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS

    # Mock show data from epguides
    mock_get_metadata.return_value = [
        {
            "directory": "finishedshow",
            "title": "Finished Show",
            "network": "Netflix",
            "run time": "60 min",
        }
    ]

    # Create episode data with all episodes released (old dates)
    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS)
    old_date_1 = (threshold - timedelta(days=60)).strftime("%d %b %y")
    old_date_2 = (threshold - timedelta(days=30)).strftime("%d %b %y")  # Last episode

    mock_episodes_data = [
        {
            "season": 1,
            "number": 1,
            "title": "First Episode",
            "release_date": old_date_1,
        },
        {
            "season": 1,
            "number": 2,
            "title": "Last Episode",
            "release_date": old_date_2,
        },
    ]
    mock_get_episodes_data.return_value = mock_episodes_data

    result = await show_service.get_show("finishedshow")

    # Should have end_date set to the last episode's release date
    assert result is not None
    assert result.end_date is not None
    # Verify it's the last episode's date (old_date_2)
    expected_date = epguides.parse_date_string(old_date_2)
    assert expected_date is not None
    assert result.end_date == expected_date.date()


# =============================================================================
# Episode Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_episodes_returns_sorted_list(mock_get_metadata, mock_get_episodes):
    """Test that episodes are returned sorted by season and episode number."""
    mock_get_metadata.return_value = [{"directory": "test", "title": "Test Show"}]

    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS + 1)
    old_date = threshold.strftime("%d %b %y")

    # Episodes in wrong order
    mock_get_episodes.return_value = [
        {"season": 2, "number": 1, "title": "S2E1", "release_date": old_date},
        {"season": 1, "number": 2, "title": "S1E2", "release_date": old_date},
        {"season": 1, "number": 1, "title": "S1E1", "release_date": old_date},
    ]

    episodes = await show_service.get_episodes("test")

    assert len(episodes) == 3
    assert episodes[0].season == 1 and episodes[0].number == 1
    assert episodes[1].season == 1 and episodes[1].number == 2
    assert episodes[2].season == 2 and episodes[2].number == 1


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_episodes_assigns_episode_numbers(mock_get_metadata, mock_get_episodes):
    """Test that episode_number is assigned correctly."""
    mock_get_metadata.return_value = [{"directory": "test", "title": "Test Show"}]

    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS + 1)
    old_date = threshold.strftime("%d %b %y")

    mock_get_episodes.return_value = [
        {"season": 1, "number": 1, "title": "Pilot", "release_date": old_date},
        {"season": 1, "number": 2, "title": "Second", "release_date": old_date},
    ]

    episodes = await show_service.get_episodes("test")

    assert episodes[0].episode_number == 1
    assert episodes[1].episode_number == 2


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
async def test_get_episodes_filters_invalid_entries(mock_get_episodes):
    """Test that episodes with missing fields are filtered out."""
    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS + 1)
    old_date = threshold.strftime("%d %b %y")

    mock_get_episodes.return_value = [
        {"season": 1, "number": 1, "title": "Valid", "release_date": old_date},
        {"season": 1, "number": None, "title": "No Number", "release_date": old_date},
        {"season": None, "number": 2, "title": "No Season", "release_date": old_date},
        {"season": 1, "number": 3, "title": "", "release_date": old_date},  # Empty title
        {"season": 1, "number": 4, "title": "No Date", "release_date": ""},
    ]

    episodes = await show_service.get_episodes("test")

    assert len(episodes) == 1
    assert episodes[0].title == "Valid"


# =============================================================================
# Cache Invalidation Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.core.cache.get_redis")
async def test_invalidate_show_cache(mock_get_redis):
    """Test that cache invalidation calls Redis delete."""
    mock_redis = AsyncMock()
    mock_get_redis.return_value = mock_redis

    await show_service.invalidate_show_cache("breakingbad")

    mock_redis.delete.assert_called_once()
    # Verify the keys being deleted
    call_args = mock_redis.delete.call_args[0]
    assert "show:breakingbad" in call_args
    assert "seasons:breakingbad" in call_args


# =============================================================================
# Edge Cases
# =============================================================================


def test_normalize_show_id_edge_cases():
    """Test show ID normalization edge cases."""
    # Mixed case with spaces
    assert show_service.normalize_show_id("The Office") == "office"
    assert show_service.normalize_show_id("THE OFFICE") == "office"

    # No "the" prefix
    assert show_service.normalize_show_id("Friends") == "friends"

    # Multiple spaces
    assert show_service.normalize_show_id("Game of Thrones") == "gameofthrones"


def test_parse_date_string_edge_cases():
    """Test date parsing edge cases."""
    # Various valid formats
    assert epguides.parse_date_string("01 Jan 20") is not None
    assert epguides.parse_date_string("31/Dec/99") is not None

    # Invalid inputs
    assert epguides.parse_date_string(None) is None
    assert epguides.parse_date_string("") is None
    assert epguides.parse_date_string("not a date") is None
    assert epguides.parse_date_string("2024-13-45") is None  # Invalid date


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_search_shows_case_insensitive(mock_get_metadata):
    """Test that search is case-insensitive."""
    mock_get_metadata.return_value = [
        {"directory": "bb", "title": "Breaking Bad"},
        {"directory": "got", "title": "Game of Thrones"},
    ]

    # Search with different cases
    results1 = await show_service.search_shows("BREAKING")
    results2 = await show_service.search_shows("breaking")
    results3 = await show_service.search_shows("Breaking")

    assert len(results1) == 1
    assert len(results2) == 1
    assert len(results3) == 1
    assert results1[0].title == results2[0].title == results3[0].title


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_search_shows_no_results(mock_get_metadata):
    """Test search with no matching results."""
    mock_get_metadata.return_value = [
        {"directory": "bb", "title": "Breaking Bad"},
    ]

    results = await show_service.search_shows("nonexistent")

    assert len(results) == 0


# =============================================================================
# Corrupted Cache Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
async def test_corrupted_cache_html_returns_fresh_data(mock_cache_set, mock_cache_get, mock_get_metadata):
    """Test that corrupted HTML cache data is handled gracefully."""
    # Simulate corrupted cache with HTML content (like what caused the 500)
    mock_cache_get.return_value = '<html><meta name="viewport" content="width=device-width"></html>'
    mock_get_metadata.return_value = [
        {"directory": "BreakingBad", "title": "Breaking Bad", "network": "AMC"},
    ]

    # Should not raise, should return fresh data
    shows = await show_service.get_all_shows()

    assert len(shows) == 1
    assert shows[0].title == "Breaking Bad"


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
async def test_corrupted_cache_invalid_json_returns_fresh_data(mock_cache_set, mock_cache_get, mock_get_metadata):
    """Test that invalid JSON cache data is handled gracefully."""
    # Simulate corrupted cache with invalid JSON
    mock_cache_get.return_value = "not valid json {{"
    mock_get_metadata.return_value = [
        {"directory": "GOT", "title": "Game of Thrones", "network": "HBO"},
    ]

    # Should not raise, should return fresh data
    shows = await show_service.get_all_shows()

    assert len(shows) == 1
    assert shows[0].title == "Game of Thrones"
