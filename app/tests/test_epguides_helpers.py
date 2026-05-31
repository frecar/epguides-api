"""
Tests for epguides service helper functions.

Tests edge cases and behavior for internal helper functions
that parse CSV data, extract metadata, and handle TVMaze integration.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from prometheus_client import Histogram

from app.core.metrics import UPSTREAM_REQUESTS, UPSTREAM_RESPONSE_AGE
from app.services import epguides


def _histo_count(histogram: Histogram, **labels: Any) -> float:
    """Return the current observation count for a labeled histogram via collect()."""
    target_name = histogram._name + "_count"
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name == target_name and all(sample.labels.get(k) == v for k, v in labels.items()):
                return sample.value
    return 0.0


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
    """A row shorter than the column indices (here ``number`` is out of range
    and ``season`` is the non-numeric token ``"two"``) is skipped, not kept:
    it has no valid numeric season/number, so it isn't a real episode (#298).
    Previously such partial/garbage rows were surfaced, which is the class of
    bug that let HTML fragments reach EpisodeSchema."""
    rows = [["only", "two"]]
    column_map = {"season": 1, "number": 2, "release_date": 3, "title": 4}
    result = epguides._parse_episode_rows(rows, column_map)
    assert result == []


def test_parse_episode_rows_short_row_keeps_numeric_partial():
    """A short row that still has numeric season + number is kept even when
    later columns (title) are missing — the numeric guard gates on the
    episode-identity columns only, not on completeness."""
    rows = [["x", "1", "2"]]  # season=col1="1", number=col2="2", title=col4 missing
    column_map = {"season": 1, "number": 2, "release_date": 3, "title": 4}
    result = epguides._parse_episode_rows(rows, column_map)
    assert len(result) == 1
    assert result[0]["season"] == "1"
    assert result[0]["number"] == "2"
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


# =============================================================================
# Upstream Metrics — _fetch_url instrumentation
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_url_records_epguides_success(mock_client_class):
    """_fetch_url increments epguides success counter and records latency."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    before_count = UPSTREAM_REQUESTS.labels(source="epguides", outcome="success")._value.get()
    before_age = _histo_count(UPSTREAM_RESPONSE_AGE, source="epguides")

    result = await epguides._fetch_url("https://epguides.com/test")

    assert result is mock_response
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="success")._value.get() == before_count + 1
    assert _histo_count(UPSTREAM_RESPONSE_AGE, source="epguides") == before_age + 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_url_records_epguides_timeout(mock_client_class):
    """_fetch_url increments epguides timeout counter on TimeoutException."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_client_class.return_value = mock_client

    before = UPSTREAM_REQUESTS.labels(source="epguides", outcome="timeout")._value.get()

    result = await epguides._fetch_url("https://epguides.com/test")

    assert result is None
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="timeout")._value.get() == before + 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_url_records_epguides_http_error(mock_client_class):
    """_fetch_url increments epguides http_error counter on non-2xx response."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response)
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    before = UPSTREAM_REQUESTS.labels(source="epguides", outcome="http_error")._value.get()

    result = await epguides._fetch_url("https://epguides.com/test")

    assert result is None
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="http_error")._value.get() == before + 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_url_records_epguides_connect_error(mock_client_class):
    """_fetch_url increments epguides http_error counter on ConnectError."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("unreachable"))
    mock_client_class.return_value = mock_client

    before = UPSTREAM_REQUESTS.labels(source="epguides", outcome="http_error")._value.get()

    result = await epguides._fetch_url("https://epguides.com/test")

    assert result is None
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="http_error")._value.get() == before + 1


# =============================================================================
# Upstream Metrics — _tvmaze_get instrumentation
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_tvmaze_get_records_success(mock_client_class):
    """_tvmaze_get increments tvmaze success counter and records latency on 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    before_count = UPSTREAM_REQUESTS.labels(source="tvmaze", outcome="success")._value.get()
    before_age = _histo_count(UPSTREAM_RESPONSE_AGE, source="tvmaze")

    result = await epguides._tvmaze_get("https://api.tvmaze.com/shows/123")

    assert result is mock_response
    assert UPSTREAM_REQUESTS.labels(source="tvmaze", outcome="success")._value.get() == before_count + 1
    assert _histo_count(UPSTREAM_RESPONSE_AGE, source="tvmaze") == before_age + 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_tvmaze_get_records_http_error_on_non_200(mock_client_class):
    """_tvmaze_get increments tvmaze http_error counter on non-200 status."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    before = UPSTREAM_REQUESTS.labels(source="tvmaze", outcome="http_error")._value.get()

    result = await epguides._tvmaze_get("https://api.tvmaze.com/shows/99999")

    assert result is None
    assert UPSTREAM_REQUESTS.labels(source="tvmaze", outcome="http_error")._value.get() == before + 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_tvmaze_get_records_timeout(mock_client_class):
    """_tvmaze_get increments tvmaze timeout counter on TimeoutException."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_client_class.return_value = mock_client

    before = UPSTREAM_REQUESTS.labels(source="tvmaze", outcome="timeout")._value.get()

    result = await epguides._tvmaze_get("https://api.tvmaze.com/shows/123")

    assert result is None
    assert UPSTREAM_REQUESTS.labels(source="tvmaze", outcome="timeout")._value.get() == before + 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_tvmaze_get_passes_kwargs_to_client(mock_client_class):
    """_tvmaze_get forwards **kwargs (e.g. params=) to httpx client.get."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    await epguides._tvmaze_get("https://api.tvmaze.com/singlesearch/shows", params={"q": "test"})

    mock_client.get.assert_called_once_with("https://api.tvmaze.com/singlesearch/shows", params={"q": "test"})


# =============================================================================
# Upstream Metrics — fetch_csv parse_error recording
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_fetch_csv_records_parse_error(mock_fetch):
    """fetch_csv increments epguides parse_error counter when CSV is malformed."""
    mock_response = MagicMock()
    mock_response.encoding = "utf-8"
    mock_response.text = "valid,header\n"
    mock_response.content = b"valid,header\n"

    import csv

    mock_fetch.return_value = mock_response

    before = UPSTREAM_REQUESTS.labels(source="epguides", outcome="parse_error")._value.get()

    # Patch csv.reader to raise csv.Error to simulate a malformed CSV
    with patch("csv.reader", side_effect=csv.Error("malformed")):
        result = await epguides.fetch_csv("https://epguides.com/data.csv")

    assert result == []
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="parse_error")._value.get() == before + 1


# =============================================================================
# TVMaze JSON parse-error branches (defensive — covers each except Exception)
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_handles_json_parse_error(mock_client_class):
    """_search_tvmaze_by_title returns None when response.json() raises."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("invalid json")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await epguides._search_tvmaze_by_title("Broken JSON Show")
    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_handles_json_parse_error(mock_client_class):
    """_fetch_tvmaze_episodes returns [] when response.json() raises."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("invalid json")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await epguides._fetch_tvmaze_episodes("123")
    assert result == []


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_merge_tvmaze_episode_data_returns_input_on_json_parse_error(mock_client_class):
    """_merge_tvmaze_episode_data returns input episodes unchanged when TVMaze JSON fails."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("invalid json")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    episodes = [{"season": "1", "number": "1", "title": "Pilot", "release_date": "2020-01-01"}]
    result = await epguides._merge_tvmaze_episode_data(episodes, "123")
    assert result == episodes


@pytest.mark.asyncio
@patch("app.core.cache.cache_set", new_callable=AsyncMock)
@patch("app.core.cache.cache_get", new_callable=AsyncMock, return_value=None)
@patch("httpx.AsyncClient")
async def test_get_tvmaze_show_data_handles_json_parse_error(mock_client_class, _mock_get, _mock_set):
    """get_tvmaze_show_data returns None when response.json() raises."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("invalid json")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_show_data("badjson_show")
    assert result is None


@pytest.mark.asyncio
@patch("app.core.cache.cache_set", new_callable=AsyncMock)
@patch("app.core.cache.cache_get", new_callable=AsyncMock, return_value=None)
@patch("httpx.AsyncClient")
async def test_get_tvmaze_seasons_handles_json_parse_error(mock_client_class, _mock_get, _mock_set):
    """get_tvmaze_seasons returns [] when response.json() raises."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("invalid json")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_seasons("badjson_show")
    assert result == []


# =============================================================================
# lookup_tvmaze_by_imdb (#229)
# =============================================================================


@pytest.mark.asyncio
async def test_lookup_tvmaze_by_imdb_empty_input_short_circuits():
    """No upstream call for empty imdb_id — saves a known-bad request."""
    assert await epguides.lookup_tvmaze_by_imdb("") is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_lookup_tvmaze_by_imdb_happy_path(mock_client_class):
    """TVMaze lookup returns the parsed JSON on 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"name": "Breaking Bad", "externals": {"imdb": "tt0903747"}}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await epguides.lookup_tvmaze_by_imdb("tt0903747")
    assert result == {"name": "Breaking Bad", "externals": {"imdb": "tt0903747"}}


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_lookup_tvmaze_by_imdb_returns_none_on_non_200(mock_client_class):
    """404 / 500 / etc → None. The wrapper _tvmaze_get already returns None
    on non-200; this checks the helper composes correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    assert await epguides.lookup_tvmaze_by_imdb("tt9999999") is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_lookup_tvmaze_by_imdb_returns_none_on_parse_error(mock_client_class):
    """response.json() raising should be caught — defensive against weird
    upstream payloads."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("not json")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    assert await epguides.lookup_tvmaze_by_imdb("tt0903747") is None


# =============================================================================
# fetch_csv — empty-body detection (#253)
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_fetch_csv_treats_empty_body_as_upstream_unavailable(mock_fetch):
    """HTTP 200 with a zero-byte body — the epguides CSV endpoint's
    documented sick-mode (issue #253) — must return [] and record an
    ``empty_response`` outcome so we can dashboard it. Returning [] is
    what makes the caller fall through to the TVMaze fallback."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.encoding = "utf-8"
    mock_response.text = ""
    mock_response.content = b""
    mock_fetch.return_value = mock_response

    before = UPSTREAM_REQUESTS.labels(source="epguides", outcome="empty_response")._value.get()

    result = await epguides.fetch_csv("https://epguides.com/common/exportToCSVmaze.asp?maze=999")

    assert result == []
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="empty_response")._value.get() == before + 1


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_fetch_csv_treats_whitespace_only_body_as_empty(mock_fetch):
    """Whitespace-only body (e.g. just a trailing newline) is also treated
    as empty — csv.reader would otherwise return [] with no signal that
    the upstream is actually sick."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.encoding = "utf-8"
    mock_response.text = "\n   \n\t"
    mock_response.content = b"\n   \n\t"
    mock_fetch.return_value = mock_response

    before = UPSTREAM_REQUESTS.labels(source="epguides", outcome="empty_response")._value.get()

    result = await epguides.fetch_csv("https://epguides.com/common/exportToCSVmaze.asp?maze=999")

    assert result == []
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="empty_response")._value.get() == before + 1


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_fetch_csv_records_timeout_only_via_fetch_url(mock_fetch):
    """The 'silent hang' upstream behaviour shows up as an httpx
    TimeoutException inside `_fetch_url`, which then returns None.
    fetch_csv must not record an additional empty_response in that path —
    the timeout counter is already incremented by `_fetch_url`. This pins
    the contract so we don't double-count."""
    mock_fetch.return_value = None  # simulates the timeout path

    before_empty = UPSTREAM_REQUESTS.labels(source="epguides", outcome="empty_response")._value.get()

    result = await epguides.fetch_csv("https://epguides.com/common/exportToCSVmaze.asp?maze=999")

    assert result == []
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="empty_response")._value.get() == before_empty


# =============================================================================
# fetch_csv — HTML-masquerading-as-CSV detection (#298)
# =============================================================================

# The actual page-head fragment that, parsed as CSV, leaked
# ' user-scalable=yes">' into the episode-number column and broke caching for
# dozens of shows. Kept verbatim as the regression fixture.
_VIEWPORT_HTML_BODY = (
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, '
    'user-scalable=yes">\n'
    "<title>Some Show (a Titles &amp; Air Dates Guide)</title>\n"
    "</head>\n"
    "<body></body>\n"
    "</html>\n"
)


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_fetch_csv_rejects_html_body_masquerading_as_csv(mock_fetch):
    """HTTP 200 returning the HTML show page (or an error page) instead of
    CSV — the exact source of #298. Without this guard csv.reader parses the
    markup line-by-line and the viewport meta tag's ``user-scalable=yes">``
    fragment lands in the episode-number column, failing EpisodeSchema and
    dropping the show's episodes. Must return [] (→ TVMaze fallback) and
    record a ``parse_error`` outcome — never surface the HTML rows."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.encoding = "utf-8"
    mock_response.text = _VIEWPORT_HTML_BODY
    mock_response.content = _VIEWPORT_HTML_BODY.encode()
    mock_fetch.return_value = mock_response

    before = UPSTREAM_REQUESTS.labels(source="epguides", outcome="parse_error")._value.get()

    result = await epguides.fetch_csv("https://epguides.com/common/exportToCSVmaze.asp?maze=999")

    assert result == []
    assert UPSTREAM_REQUESTS.labels(source="epguides", outcome="parse_error")._value.get() == before + 1


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_fetch_csv_parses_valid_csv_normally(mock_fetch):
    """Sanity counterpart: a real CSV body is parsed into rows and is NOT
    misclassified as HTML by the masquerade guard."""
    csv_body = "number,season,airdate\n1,1,2024-01-01\n2,1,2024-01-08\n"
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.encoding = "utf-8"
    mock_response.text = csv_body
    mock_response.content = csv_body.encode()
    mock_fetch.return_value = mock_response

    result = await epguides.fetch_csv("https://epguides.com/common/exportToCSVmaze.asp?maze=999")

    assert result == [["number", "season", "airdate"], ["1", "1", "2024-01-01"], ["2", "1", "2024-01-08"]]


def test_looks_like_html_detects_document_markers():
    """Leading markup markers identify an HTML body, case-insensitively and
    after a BOM / leading whitespace."""
    assert epguides._looks_like_html("<!DOCTYPE html>\n<html></html>")
    assert epguides._looks_like_html("<html><head></head></html>")
    assert epguides._looks_like_html("  \n\t<meta name='viewport'>")
    assert epguides._looks_like_html("﻿<!doctype HTML>")  # UTF-8 BOM prefix
    assert epguides._looks_like_html("<?xml version='1.0'?>")


def test_looks_like_html_allows_csv_with_angle_brackets():
    """A legitimate CSV row whose title cell contains angle brackets must NOT
    be misclassified as HTML — only the *leading* token is inspected, and real
    CSV starts with a number/header, not a markup marker."""
    assert not epguides._looks_like_html('1,1,2024-01-01,"3 < 4: The Reckoning"')
    assert not epguides._looks_like_html("number,season,airdate,title")
    assert not epguides._looks_like_html("")


# =============================================================================
# _parse_episode_rows — numeric season/number validation (#298)
# =============================================================================


def test_parse_episode_rows_skips_html_fragment_number():
    """A row whose ``number`` column holds an HTML fragment (the #298 leak,
    e.g. ' user-scalable=yes">') is skipped, not surfaced — markup never
    reaches EpisodeSchema. The clean episode row beside it is kept."""
    rows = [
        ["number", "season", "airdate", "", "", "title"],  # header — non-numeric
        [' user-scalable=yes">', "1", "01 Jan 24", "", "", "junk"],  # the #298 leak
        ["1", "1", "01 Jan 24", "", "", "Real Episode"],  # legit
    ]
    column_map = {"season": 1, "number": 0, "release_date": 2, "title": 5}

    result = epguides._parse_episode_rows(rows, column_map)

    assert len(result) == 1
    assert result[0]["number"] == "1"
    assert result[0]["title"] == "Real Episode"


def test_parse_episode_rows_keeps_season_zero_specials():
    """Specials use season 0 (EpisodeSchema allows season ge=0); the numeric
    guard must keep them, not treat 0 as falsy/invalid."""
    rows = [
        ["0", "1", "01 Jan 24", "", "", "Special"],
    ]
    column_map = {"season": 0, "number": 1, "release_date": 2, "title": 5}

    result = epguides._parse_episode_rows(rows, column_map)

    assert len(result) == 1
    assert result[0]["season"] == "0"


def test_parse_episode_rows_skips_non_numeric_season():
    """A non-numeric season token (e.g. stray markup) skips the row."""
    rows = [
        ["<body>", "1", "01 Jan 24", "", "", "junk"],
        ["2", "3", "08 Jan 24", "", "", "Good"],
    ]
    column_map = {"season": 0, "number": 1, "release_date": 2, "title": 5}

    result = epguides._parse_episode_rows(rows, column_map)

    assert len(result) == 1
    assert result[0]["title"] == "Good"


def test_is_integer_token_variants():
    """_is_integer_token accepts plain/signed/whitespace integers and ints;
    rejects markup, floats, and empty strings."""
    assert epguides._is_integer_token("1")
    assert epguides._is_integer_token("0")
    assert epguides._is_integer_token("  42 ")
    assert epguides._is_integer_token("+1")
    assert epguides._is_integer_token("-3")
    assert epguides._is_integer_token(7)
    assert not epguides._is_integer_token(' user-scalable=yes">')
    assert not epguides._is_integer_token("")
    assert not epguides._is_integer_token("1.5")
    assert not epguides._is_integer_token(None)
    assert not epguides._is_integer_token(["1"])


# =============================================================================
# get_episodes_data — sick-CSV fallback paths (#253)
# =============================================================================


@pytest.mark.asyncio
@patch("app.core.cache.cache_set", new_callable=AsyncMock)
@patch("app.core.cache.cache_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.epguides._fetch_tvmaze_episodes")
@patch("app.services.epguides._search_tvmaze_by_title")
@patch("app.services.epguides._get_show_title")
@patch("app.services.epguides.fetch_csv")
@patch("app.services.epguides._fetch_url")
async def test_get_episodes_data_silent_hang_falls_back_via_show_page_maze_id(
    mock_fetch_url,
    mock_fetch_csv,
    mock_get_title,
    mock_search,
    mock_episodes,
    _mock_cache_get,
    _mock_cache_set,
):
    """Reproduces issue #253: show page returns HTML with a usable
    maze_id, but the CSV endpoint silently hangs (httpx times out →
    _fetch_url returns None → fetch_csv returns []). The fallback must
    engage and prefer the maze_id we already scraped from the show page
    over the fuzzy title-based TVMaze search."""
    # Show page itself succeeds — returns HTML with a TVMaze export link
    show_page_resp = MagicMock()
    show_page_resp.status_code = 200
    show_page_resp.text = '<html><body><a href="exportToCSVmaze.asp?maze=12345">Export CSV</a></body></html>'
    mock_fetch_url.return_value = show_page_resp

    # CSV fetch hangs / times out / returns empty — simulates #253
    mock_fetch_csv.return_value = []

    # TVMaze fallback succeeds via the maze_id scraped from the show page
    mock_episodes.return_value = [
        {
            "season": "1",
            "number": "1",
            "title": "Pilot",
            "release_date": "2020-01-01",
            "summary": "",
            "poster_url": "",
        }
    ]

    result = await epguides.get_episodes_data("silent_hang_maze_show")

    assert len(result) == 1
    assert result[0]["title"] == "Pilot"
    # The maze_id was scraped from the show page — no title-based search needed.
    mock_episodes.assert_called_once_with("12345")
    mock_search.assert_not_called()
    mock_get_title.assert_not_called()


@pytest.mark.asyncio
@patch("app.core.cache.cache_set", new_callable=AsyncMock)
@patch("app.core.cache.cache_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.epguides._fetch_tvmaze_episodes")
@patch("app.services.epguides._search_tvmaze_by_title")
@patch("app.services.epguides._get_show_title")
@patch("app.services.epguides.fetch_csv")
@patch("app.services.epguides._fetch_url")
async def test_get_episodes_data_silent_hang_falls_back_via_title_when_no_maze_id(
    mock_fetch_url,
    mock_fetch_csv,
    mock_get_title,
    mock_search,
    mock_episodes,
    _mock_cache_get,
    _mock_cache_set,
):
    """If the show page is reachable but offers no maze_id (legacy TVRage
    format), and the TVRage CSV endpoint hangs, the fallback must still
    engage via the title-based TVMaze search."""
    show_page_resp = MagicMock()
    show_page_resp.status_code = 200
    show_page_resp.text = '<html><body><a href="exportToCSV.asp?rage=99">Export CSV</a></body></html>'
    mock_fetch_url.return_value = show_page_resp

    mock_fetch_csv.return_value = []  # CSV hangs / empty body

    mock_get_title.return_value = "Test Show"
    mock_search.return_value = {"id": 67890, "name": "Test Show"}
    mock_episodes.return_value = [
        {
            "season": "1",
            "number": "1",
            "title": "Pilot",
            "release_date": "2020-01-01",
            "summary": "",
            "poster_url": "",
        }
    ]

    result = await epguides.get_episodes_data("silent_hang_legacy_show")

    assert len(result) == 1
    mock_search.assert_called_once_with("Test Show")
    mock_episodes.assert_called_once_with("67890")


# =============================================================================
# get_episodes_data — raw cache key isolation (#298)
# =============================================================================


@pytest.mark.asyncio
@patch("app.core.cache.cache_set", new_callable=AsyncMock)
@patch("app.core.cache.cache_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.epguides._fetch_url", new_callable=AsyncMock, return_value=None)
async def test_get_episodes_data_uses_distinct_raw_cache_key(_mock_fetch_url, mock_cache_get, _mock_cache_set):
    """The raw (unvalidated) episode-dict cache must live under a DISTINCT
    key namespace from the model-validated ``episodes:`` cache (#298).

    Sharing the ``episodes:`` prefix let a raw dict — e.g. one carrying an
    HTML fragment in ``number`` — be read back through the EpisodeSchema cache
    and fail validation, dropping the whole show. The raw layer must key on
    ``episodes_raw:`` so the two namespaces can never cross-contaminate."""
    # _fetch_url returns None → empty result; nothing is written, so assert the
    # READ key namespace via cache_get instead. (The fallback path also reads
    # the shows-metadata cache, so cache_get fires more than once — assert the
    # raw episode key is the one probed for this show, and the schema key never.)
    await epguides.get_episodes_data("somekey")

    read_keys = [call.args[0] for call in mock_cache_get.await_args_list]
    assert "episodes_raw:somekey" in read_keys
    assert "episodes:somekey" not in read_keys
