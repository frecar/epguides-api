"""
Unit tests for service functions.

Tests business logic independently of HTTP layer.
"""

from unittest.mock import patch

import pytest

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
@patch("app.services.show_service.get_all_shows")
async def test_search_shows(mock_get_all):
    """Test searching shows."""
    from app.models.schemas import create_show_schema

    mock_shows = [
        create_show_schema(epguides_key="bb", title="Breaking Bad"),
        create_show_schema(epguides_key="got", title="Game of Thrones"),
    ]
    mock_get_all.return_value = mock_shows

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
    assert show_service.parse_imdb_id("tt0903747") == "tt0903747"
    assert show_service.parse_imdb_id("tt123456") == "tt0123456"  # Padded
    assert show_service.parse_imdb_id("invalid") == "invalid"


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.show_service.get_all_shows")
async def test_get_show_does_not_set_end_date_with_unreleased_episodes(mock_get_all, mock_get_episodes_data):
    """Test that get_show does NOT set end_date when there are unreleased episodes."""
    from datetime import datetime, timedelta

    from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS
    from app.models.schemas import create_show_schema

    # Create a show without end_date
    mock_show = create_show_schema(
        epguides_key="fallout",
        title="Fallout",
        end_date=None,
    )
    mock_get_all.return_value = [mock_show]

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
@patch("app.services.show_service.get_all_shows")
async def test_get_show_sets_end_date_when_all_episodes_released(mock_get_all, mock_get_episodes_data):
    """Test that get_show DOES set end_date when all episodes are released."""
    from datetime import datetime, timedelta

    from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS
    from app.models.schemas import create_show_schema

    # Create a show without end_date
    mock_show = create_show_schema(
        epguides_key="finishedshow",
        title="Finished Show",
        end_date=None,
    )
    mock_get_all.return_value = [mock_show]

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
