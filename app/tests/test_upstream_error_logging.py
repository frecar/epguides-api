"""Upstream fetch and parse failures log what failed, the show or TVMaze ID, the URL and the consequence."""

import inspect
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.constants import EPGUIDES_BASE_URL
from app.core.logging_config import StructuredFormatter
from app.core.metrics import UpstreamOutcome
from app.services import epguides


def _response(text: str, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.encoding = "utf-8"
    response.text = text
    return response


def _client_returning(response: MagicMock | None = None, error: Exception | None = None) -> MagicMock:
    client = AsyncMock()
    if error is not None:
        client.get.side_effect = error
    else:
        client.get.return_value = response
    client.__aenter__.return_value = client
    return MagicMock(return_value=client)


def _only_record(caplog: pytest.LogCaptureFixture, level: int) -> logging.LogRecord:
    records = [r for r in caplog.records if r.name == "app.services.epguides" and r.levelno == level]
    assert len(records) == 1, [r.getMessage() for r in records]
    return records[0]


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_catalogue_with_html_body_is_rejected_naming_missing_columns(mock_fetch, caplog):
    mock_fetch.return_value = _response("<!DOCTYPE html><html><body>maintenance</body></html>")

    with caplog.at_level(logging.ERROR), patch("app.services.epguides.record_upstream_request") as mock_record:
        result = await inspect.unwrap(epguides.get_all_shows_metadata)()

    assert result == []
    record = _only_record(caplog, logging.ERROR)
    assert f"show catalogue at {EPGUIDES_BASE_URL}/common/allshows.txt is not the expected CSV" in record.getMessage()
    assert "missing columns ['title', 'directory']" in record.getMessage()
    assert record.__dict__["outcome"] == "parse_error"
    assert record.__dict__["upstream_source"] == "epguides.com"
    mock_record.assert_called_once_with("epguides", UpstreamOutcome.PARSE_ERROR)


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_catalogue_without_directory_column_names_it(mock_fetch, caplog):
    mock_fetch.return_value = _response("title,network\nBreaking Bad,AMC\n")

    with caplog.at_level(logging.ERROR):
        result = await inspect.unwrap(epguides.get_all_shows_metadata)()

    assert result == []
    message = _only_record(caplog, logging.ERROR).getMessage()
    assert "missing columns ['directory'] (header: ['title', 'network'])" in message


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url", new_callable=AsyncMock, return_value=None)
async def test_catalogue_fetch_failure_states_consequence(mock_fetch, caplog):
    with caplog.at_level(logging.WARNING):
        assert await inspect.unwrap(epguides.get_all_shows_metadata)() == []

    record = _only_record(caplog, logging.WARNING)
    assert record.getMessage() == (
        f"epguides.com show catalogue unavailable from {EPGUIDES_BASE_URL}/common/allshows.txt; "
        "show lookups report upstream_unavailable until it loads"
    )
    assert record.__dict__["url"] == f"{EPGUIDES_BASE_URL}/common/allshows.txt"


@pytest.mark.asyncio
async def test_epguides_timeout_log_names_url_and_setting(caplog):
    url = "https://epguides.com/BreakingBad/"
    client_class = _client_returning(error=httpx.ReadTimeout("slow"))

    with caplog.at_level(logging.WARNING), patch("httpx.AsyncClient", client_class):
        assert await epguides._fetch_url(url) is None

    record = _only_record(caplog, logging.WARNING)
    assert record.getMessage().startswith("epguides.com request timed out after ")
    assert record.getMessage().endswith(f": {url} (raise HTTP_TIMEOUT_SECONDS if this persists)")
    assert (record.__dict__["url"], record.__dict__["outcome"]) == (url, "timeout")


@pytest.mark.asyncio
async def test_epguides_http_status_log_carries_status_code(caplog):
    url = "https://epguides.com/Nope/"
    request = httpx.Request("GET", url)
    error = httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request))

    with caplog.at_level(logging.WARNING), patch("httpx.AsyncClient", _client_returning(error=error)):
        assert await epguides._fetch_url(url) is None

    record = _only_record(caplog, logging.WARNING)
    assert record.getMessage() == f"epguides.com returned HTTP 404 for {url}"
    assert record.__dict__["http_status"] == 404


@pytest.mark.asyncio
async def test_epguides_connect_error_log_names_url(caplog):
    url = "https://epguides.com/BreakingBad/"

    with (
        caplog.at_level(logging.WARNING),
        patch("httpx.AsyncClient", _client_returning(error=httpx.ConnectError("dns"))),
    ):
        assert await epguides._fetch_url(url) is None

    assert _only_record(caplog, logging.WARNING).getMessage() == (
        f"epguides.com unreachable (connection or DNS failure) for {url}: dns"
    )


@pytest.mark.asyncio
async def test_unexpected_epguides_failure_logs_type_and_traceback(caplog):
    url = "https://epguides.com/BreakingBad/"

    with caplog.at_level(logging.ERROR), patch("httpx.AsyncClient", _client_returning(error=RuntimeError("boom"))):
        assert await epguides._fetch_url(url) is None

    record = _only_record(caplog, logging.ERROR)
    assert record.getMessage() == f"Unexpected RuntimeError fetching {url} from epguides.com: boom"
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_tvmaze_timeout_log_names_url(caplog):
    url = "https://api.tvmaze.com/shows/169"

    with (
        caplog.at_level(logging.WARNING),
        patch("httpx.AsyncClient", _client_returning(error=httpx.ReadTimeout("slow"))),
    ):
        assert await epguides._tvmaze_get(url) is None

    record = _only_record(caplog, logging.WARNING)
    assert record.getMessage().startswith("TVMaze request timed out after ")
    assert (record.__dict__["upstream_source"], record.__dict__["url"], record.__dict__["outcome"]) == (
        "TVMaze",
        url,
        "timeout",
    )


@pytest.mark.asyncio
async def test_tvmaze_transport_failure_names_exception_type(caplog):
    url = "https://api.tvmaze.com/shows/169"

    with (
        caplog.at_level(logging.WARNING),
        patch("httpx.AsyncClient", _client_returning(error=httpx.ConnectError("refused"))),
    ):
        assert await epguides._tvmaze_get(url) is None

    assert (
        _only_record(caplog, logging.WARNING).getMessage() == f"TVMaze request failed for {url}: ConnectError: refused"
    )


@pytest.mark.asyncio
async def test_tvmaze_off_origin_redirect_is_refused_with_target(caplog):
    url = "https://api.tvmaze.com/lookup/shows"
    response = MagicMock()
    response.url = httpx.URL("https://evil.example/shows/1")

    with caplog.at_level(logging.WARNING), patch("httpx.AsyncClient", _client_returning(response=response)):
        assert await epguides._tvmaze_get(url, follow_redirects=True) is None

    assert _only_record(caplog, logging.WARNING).getMessage() == (
        f"TVMaze {url} redirected off the API origin to https://evil.example/shows/1; refusing to follow"
    )


@pytest.mark.asyncio
@patch("app.services.epguides._tvmaze_get")
async def test_unparsable_tvmaze_episodes_log_names_maze_id(mock_get, caplog):
    response = MagicMock()
    response.json.side_effect = json.JSONDecodeError("Expecting value", "<html>", 0)
    mock_get.return_value = response

    with caplog.at_level(logging.WARNING), patch("app.services.epguides.record_upstream_request") as mock_record:
        assert await epguides._fetch_tvmaze_episodes("169") == []

    record = _only_record(caplog, logging.WARNING)
    assert record.getMessage() == (
        "TVMaze episode list payload for maze_id='169' could not be parsed: JSONDecodeError: "
        "Expecting value: line 1 column 1 (char 0); continuing without it"
    )
    assert (record.__dict__["maze_id"], record.__dict__["outcome"]) == ("169", "parse_error")
    mock_record.assert_called_once_with("tvmaze", UpstreamOutcome.PARSE_ERROR)


@pytest.mark.asyncio
@patch("app.services.epguides._tvmaze_get")
async def test_wrongly_shaped_tvmaze_search_payload_names_title(mock_get, caplog):
    response = MagicMock()
    response.json.side_effect = TypeError("unexpected payload")
    mock_get.return_value = response

    with caplog.at_level(logging.WARNING):
        assert await epguides._search_tvmaze_by_title("Breaking Bad") is None

    assert "TVMaze show search payload for title='Breaking Bad' could not be parsed" in caplog.text


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url", new_callable=AsyncMock, return_value=None)
async def test_show_page_failure_names_show_and_url(mock_fetch, caplog):
    with caplog.at_level(logging.WARNING):
        assert await inspect.unwrap(epguides.get_show_metadata)("nosuchshow") is None

    record = _only_record(caplog, logging.WARNING)
    assert record.getMessage() == (
        f"Could not fetch the epguides.com page for show 'nosuchshow' at {EPGUIDES_BASE_URL}/nosuchshow; "
        "its IMDB ID and title are unavailable"
    )
    assert record.__dict__["epguides_key"] == "nosuchshow"


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url", new_callable=AsyncMock, return_value=None)
@patch("app.services.epguides._get_show_title", new_callable=AsyncMock, return_value=None)
async def test_no_episode_source_log_names_show(mock_title, mock_fetch, caplog):
    with caplog.at_level(logging.WARNING):
        assert await inspect.unwrap(epguides.get_episodes_data)("nosuchshow") == []

    record = _only_record(caplog, logging.WARNING)
    assert record.getMessage().startswith("No episode data for show 'nosuchshow' from epguides.com")
    assert record.getMessage().endswith("it will be reported as no_episodes")
    assert record.__dict__["epguides_key"] == "nosuchshow"


def test_structured_formatter_emits_upstream_identifiers():
    record = logging.LogRecord("app.services.epguides", logging.WARNING, __file__, 1, "failed", None, None)
    record.upstream_source = "TVMaze"
    record.maze_id = "169"
    record.outcome = "parse_error"
    record.epguides_key = "breakingbad"

    payload = json.loads(StructuredFormatter().format(record))

    assert payload["upstream_source"] == "TVMaze"
    assert payload["maze_id"] == "169"
    assert payload["outcome"] == "parse_error"
    assert payload["epguides_key"] == "breakingbad"
