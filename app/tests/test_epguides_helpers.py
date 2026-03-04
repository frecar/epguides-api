"""
Tests for epguides service helper functions.

Tests edge cases and behavior for internal helper functions
that parse CSV data, extract metadata, and handle TVMaze integration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import epguides


# =============================================================================
# _convert_show_id_to_title Tests
# =============================================================================


def test_convert_show_id_camel_case():
    """Test CamelCase show ID is converted to spaced title."""
    assert epguides._convert_show_id_to_title("SharkTank") == "Shark Tank"


def test_convert_show_id_already_spaced():
    """Test show ID that already has spaces is returned as-is."""
    assert epguides._convert_show_id_to_title("Shark Tank") == "Shark Tank"


def test_convert_show_id_all_lowercase_with_common_words():
    """Test lowercase show ID gets word boundaries from common words."""
    result = epguides._convert_show_id_to_title("sharktank")
    assert "shark" in result.lower()
    assert "tank" in result.lower()


def test_convert_show_id_single_word():
    """Test single-word show ID is returned unchanged."""
    assert epguides._convert_show_id_to_title("Friends") == "Friends"


# =============================================================================
# _add_word_boundaries Tests
# =============================================================================


def test_add_word_boundaries_common_words():
    """Test word boundary detection with common TV show words."""
    result = epguides._add_word_boundaries("sharktank")
    assert " " in result


def test_add_word_boundaries_prefix_the():
    """Test 'the' prefix is separated."""
    result = epguides._add_word_boundaries("theoffice")
    assert result.startswith("the ")


def test_add_word_boundaries_no_match():
    """Test string with no common word matches is returned unchanged."""
    result = epguides._add_word_boundaries("xyz")
    assert result == "xyz"


def test_add_word_boundaries_gameofthrones():
    """Test 'gameofthrones' gets reasonable word boundaries."""
    result = epguides._add_word_boundaries("gameofthrones")
    assert "game" in result.lower()
    assert "thrones" in result.lower()


def test_add_word_boundaries_avoids_false_prefix_splits():
    """Test that prefix splitting avoids words like 'there'."""
    result = epguides._add_word_boundaries("there")
    assert result == "there"


# =============================================================================
# _extract_imdb_id Tests
# =============================================================================


def test_extract_imdb_id_from_url():
    """Test IMDB ID extraction from standard URL."""
    html = '<a href="https://www.imdb.com/title/tt0903747/">IMDB</a>'
    assert epguides._extract_imdb_id(html) == "tt0903747"


def test_extract_imdb_id_from_h2_link():
    """Test IMDB ID extraction from H2 tag with link."""
    html = '<h2><a href="http://imdb.com/title/tt1234567/">Breaking Bad</a></h2>'
    assert epguides._extract_imdb_id(html) is not None


def test_extract_imdb_id_not_found():
    """Test returns None when no IMDB ID in HTML."""
    html = "<html><body>No IMDB link here</body></html>"
    assert epguides._extract_imdb_id(html) is None


# =============================================================================
# _extract_title Tests
# =============================================================================


def test_extract_title_from_h2_link():
    """Test title extraction from H2 with link."""
    html = '<h2><a href="http://imdb.com/title/tt1234567/">Breaking Bad</a></h2>'
    assert epguides._extract_title(html) == "Breaking Bad"


def test_extract_title_from_simple_h2():
    """Test title extraction from simple H2 tag."""
    html = "<h2>Game of Thrones</h2>"
    assert epguides._extract_title(html) == "Game of Thrones"


def test_extract_title_from_title_tag():
    """Test title extraction from HTML title tag as fallback."""
    html = "<title>The Office</title>"
    assert epguides._extract_title(html) == "The Office"


def test_extract_title_not_found():
    """Test returns None when no title found in HTML."""
    html = "<html><body>No title</body></html>"
    assert epguides._extract_title(html) is None


# =============================================================================
# _clean_unicode_text Tests
# =============================================================================


def test_clean_unicode_text_normal():
    """Test normal text is returned as-is."""
    response = MagicMock(spec=httpx.Response)
    response.encoding = "utf-8"
    response.text = "Normal text"
    response.content = b"Normal text"
    assert epguides._clean_unicode_text(response) == "Normal text"


def test_clean_unicode_text_with_replacement_chars():
    """Test replacement characters are cleaned."""
    response = MagicMock(spec=httpx.Response)
    response.encoding = "utf-8"
    response.text = "Text with \ufffd chars"
    response.content = b"Text with  chars"
    result = epguides._clean_unicode_text(response)
    assert "\ufffd" not in result


def test_clean_unicode_text_no_encoding():
    """Test response without encoding defaults to utf-8."""
    response = MagicMock(spec=httpx.Response)
    response.encoding = None
    response.text = "Text"
    response.content = b"Text"
    result = epguides._clean_unicode_text(response)
    assert result == "Text"
    assert response.encoding == "utf-8"


# =============================================================================
# _parse_episode_rows Tests
# =============================================================================


def test_parse_episode_rows_tvmaze_format():
    """Test parsing CSV rows in TVMaze format."""
    rows = [
        ["extra", "1", "1", "2020-01-01", "Pilot"],
        ["extra", "1", "2", "2020-01-08", "Second Episode"],
    ]
    column_map = {"season": 1, "number": 2, "release_date": 3, "title": 4}
    result = epguides._parse_episode_rows(rows, column_map)
    assert len(result) == 2
    assert result[0]["season"] == "1"
    assert result[0]["title"] == "Pilot"


def test_parse_episode_rows_empty_rows():
    """Test parsing with empty rows."""
    rows = [[], ["extra", "1", "1", "2020-01-01", "Pilot"], []]
    column_map = {"season": 1, "number": 2, "release_date": 3, "title": 4}
    result = epguides._parse_episode_rows(rows, column_map)
    assert len(result) == 1


def test_parse_episode_rows_short_rows():
    """Test parsing with rows shorter than expected column indices."""
    rows = [["only", "two"]]
    column_map = {"season": 1, "number": 2, "release_date": 3, "title": 4}
    result = epguides._parse_episode_rows(rows, column_map)
    assert len(result) == 1
    assert result[0]["season"] == "two"
    assert "title" not in result[0]


# =============================================================================
# _extract_csv_url_and_maze_id Tests
# =============================================================================


def test_extract_csv_url_tvrage_format_with_plus():
    """Test TVRage format with plus sign in rage ID."""
    html = '<a href="exportToCSV.asp?rage=123+456">Export</a>'
    url, columns, maze_id = epguides._extract_csv_url_and_maze_id(html)
    assert url is not None
    assert "rage=123+456" in url
    assert columns == epguides._TVRAGE_COLUMNS
    assert maze_id is None


def test_extract_csv_url_no_export_link():
    """Test returns None tuple when no export link found."""
    html = "<html><body>Regular page content</body></html>"
    url, columns, maze_id = epguides._extract_csv_url_and_maze_id(html)
    assert url is None
    assert columns == {}
    assert maze_id is None


# =============================================================================
# extract_poster_url Tests
# =============================================================================


def test_extract_poster_url_none_data():
    """Test poster URL extraction with None input."""
    assert epguides.extract_poster_url(None) == epguides._DEFAULT_POSTER_URL


def test_extract_poster_url_no_image_key():
    """Test poster URL extraction with no image in data."""
    assert epguides.extract_poster_url({"name": "Show"}) == epguides._DEFAULT_POSTER_URL


def test_extract_poster_url_prefers_original():
    """Test poster URL prefers original over medium."""
    data = {
        "image": {
            "original": "https://example.com/original.jpg",
            "medium": "https://example.com/medium.jpg",
        }
    }
    assert epguides.extract_poster_url(data) == "https://example.com/original.jpg"


def test_extract_poster_url_falls_back_to_medium():
    """Test poster URL falls back to medium when no original."""
    data = {"image": {"original": None, "medium": "https://example.com/medium.jpg"}}
    assert epguides.extract_poster_url(data) == "https://example.com/medium.jpg"


# =============================================================================
# parse_date_string Edge Cases
# =============================================================================


def test_parse_date_string_iso_format():
    """Test ISO date format parsing."""
    result = epguides.parse_date_string("2020-01-15")
    assert result is not None
    assert result.year == 2020
    assert result.month == 1
    assert result.day == 15


def test_parse_date_string_slash_format():
    """Test slash date format parsing."""
    result = epguides.parse_date_string("15/Jan/20")
    assert result is not None
    assert result.year == 2020


def test_parse_date_string_future_century_correction():
    """Test that far-future years are corrected by subtracting 100."""
    result = epguides.parse_date_string("01 Jan 68")
    assert result is not None
    assert result.year == 1968


# =============================================================================
# _get_show_title Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_title_from_metadata(mock_get_metadata):
    """Test title lookup from cached metadata."""
    mock_get_metadata.return_value = [
        {"directory": "SharkTank", "title": "Shark Tank"},
        {"directory": "BreakingBad", "title": "Breaking Bad"},
    ]
    result = await epguides._get_show_title("sharktank")
    assert result == "Shark Tank"


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_title_not_in_metadata(mock_get_metadata):
    """Test title fallback when not in metadata."""
    mock_get_metadata.return_value = [{"directory": "BreakingBad", "title": "Breaking Bad"}]
    result = await epguides._get_show_title("UnknownShow")
    assert result is not None
    assert result == "Unknown Show"


# =============================================================================
# _search_tvmaze_by_title Tests
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_empty_title(mock_client_class):
    """Test TVMaze search with empty title returns None."""
    result = await epguides._search_tvmaze_by_title("")
    assert result is None
    mock_client_class.assert_not_called()


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_404(mock_client_class):
    """Test TVMaze search returns None on 404."""
    mock_response = AsyncMock()
    mock_response.status_code = 404
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client
    result = await epguides._search_tvmaze_by_title("Nonexistent Show")
    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_success(mock_client_class):
    """Test TVMaze search returns show data on success."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": 123, "name": "Test Show"}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client
    result = await epguides._search_tvmaze_by_title("Test Show")
    assert result is not None
    assert result["id"] == 123


# =============================================================================
# _fetch_tvmaze_episodes Tests
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_success(mock_client_class):
    """Test fetching episodes from TVMaze."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "season": 1,
            "number": 1,
            "name": "Pilot",
            "airdate": "2020-01-01",
            "summary": "<p>First episode</p>",
            "image": {"original": "https://example.com/ep1.jpg"},
        },
    ]
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client
    result = await epguides._fetch_tvmaze_episodes("123")
    assert len(result) == 1
    assert result[0]["title"] == "Pilot"
    assert result[0]["summary"] == "First episode"
    assert result[0]["poster_url"] == "https://example.com/ep1.jpg"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_skips_incomplete(mock_client_class):
    """Test that episodes with missing required fields are skipped."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"season": 1, "number": 1, "name": "Complete", "airdate": "2020-01-01"},
        {"season": 1, "number": None, "name": "Missing Number", "airdate": "2020-01-08"},
        {"season": 1, "number": 3, "name": None, "airdate": "2020-01-15"},
    ]
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client
    result = await epguides._fetch_tvmaze_episodes("123")
    assert len(result) == 1
    assert result[0]["title"] == "Complete"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_error(mock_client_class):
    """Test TVMaze episodes fetch handles errors."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=Exception("Connection error"))
    mock_client_class.return_value = mock_client
    result = await epguides._fetch_tvmaze_episodes("123")
    assert result == []


# =============================================================================
# get_show_metadata Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_show_metadata_no_imdb_id(mock_fetch):
    """Test get_show_metadata returns None when no IMDB ID found."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>No IMDB ID here</body></html>"
    mock_fetch.return_value = mock_response
    result = await epguides.get_show_metadata("test_show")
    assert result is None


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_show_metadata_imdb_but_no_title(mock_fetch):
    """Test get_show_metadata with IMDB ID but no title."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '<a href="https://www.imdb.com/title/tt1234567/">IMDB</a>'
    mock_fetch.return_value = mock_response
    result = await epguides.get_show_metadata("test_show")
    assert result is not None
    assert result[0] == "tt1234567"
    assert result[1] == "Unknown"
