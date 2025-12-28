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
