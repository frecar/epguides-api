"""MCP tool errors name the tool, the offending argument and the next tool call an LLM caller should make."""

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.exceptions import ExternalServiceError, UpstreamSource
from app.mcp.server import MCPServer
from app.models.schemas import EpisodeSchema, create_show_schema

_SHOW = create_show_schema(epguides_key="test", title="Test Show")


async def _call(name: str, arguments: object) -> dict[str, Any]:
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    response = await MCPServer().handle_request(request)
    assert "result" not in response
    error: dict[str, Any] = response["error"]
    return error


def _episode(*, released: bool) -> EpisodeSchema:
    return EpisodeSchema(season=1, number=1, title="Pilot", release_date=date(2020, 1, 1), is_released=released)


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show", new_callable=AsyncMock, return_value=None)
async def test_unknown_show_points_llm_to_search_shows(mock_get_show):
    error = await _call("get_show", {"epguides_key": "BreakingBadd"})

    assert error["code"] == -32602
    assert error["message"] == (
        "Show not found: 'BreakingBadd'. Expected an epguides key such as 'BreakingBad' (case-insensitive, no spaces). "
        "Call search_shows with the show title to find its epguides_key."
    )
    assert error["data"] == {
        "code": "show_not_found",
        "tool": "get_show",
        "hint": "Call search_shows with the show title to find its epguides_key.",
        "context": {"epguides_key": "BreakingBadd"},
    }


@pytest.mark.asyncio
async def test_missing_required_argument_names_field_and_example():
    error = await _call("get_next_episode", {})

    assert error["code"] == -32602
    assert error["message"] == (
        "Invalid arguments for tool 'get_next_episode': epguides_key: Field required. "
        'Example arguments: {"epguides_key": "BreakingBad"}. '
        "Call tools/list for the tool's inputSchema."
    )
    assert error["data"]["code"] == "validation_error"
    assert error["data"]["errors"] == [{"field": "epguides_key", "input": None, "msg": "Field required"}]


@pytest.mark.asyncio
async def test_wrongly_typed_season_is_rejected_with_offending_value():
    error = await _call("get_episodes", {"epguides_key": "test", "season": "two"})

    assert error["code"] == -32602
    assert "season='two': Input should be a valid integer" in error["message"]
    assert error["data"]["errors"][0]["field"] == "season"


@pytest.mark.asyncio
async def test_non_object_arguments_are_rejected():
    error = await _call("search_shows", "breaking")

    assert error["data"]["code"] == "validation_error"
    assert error["data"]["errors"][0]["field"] == "arguments"
    assert 'Example arguments: {"query": "breaking"}' in error["message"]


@pytest.mark.asyncio
async def test_episode_without_season_is_rejected():
    error = await _call("get_episodes", {"epguides_key": "test", "episode": 3})

    assert error["code"] == -32602
    assert error["message"].startswith("Invalid query parameter episode=3: the episode filter requires season")
    assert error["data"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_malformed_imdb_id_is_rejected_before_lookup():
    error = await _call("lookup_by_imdb_id", {"imdb_id": "0903747"})

    assert error["data"]["code"] == "invalid_imdb_id"
    assert error["message"].startswith("Invalid IMDB ID format: '0903747'")
    assert error["message"].endswith("Pass the ID from the IMDB title URL, for example 'tt0903747'.")


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show", new_callable=AsyncMock, return_value=_SHOW)
@patch("app.mcp.server.show_service.get_episodes", new_callable=AsyncMock)
async def test_no_upcoming_episode_names_show_and_suggests_latest(mock_get_episodes, mock_get_show):
    mock_get_episodes.return_value = [_episode(released=True)]

    error = await _call("get_next_episode", {"epguides_key": "test"})

    assert error["data"]["code"] == "no_upcoming_episode"
    assert "'test'" in error["message"]
    assert error["message"].endswith("Call get_latest_episode for the most recent episode.")


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes", new_callable=AsyncMock)
async def test_no_released_episode_suggests_next(mock_get_episodes):
    mock_get_episodes.return_value = [_episode(released=False)]

    error = await _call("get_latest_episode", {"epguides_key": "test"})

    assert error["data"]["code"] == "no_released_episode"
    assert error["data"]["hint"] == "Call get_next_episode for the first air date."


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show", new_callable=AsyncMock, return_value=_SHOW)
@patch("app.mcp.server.show_service.get_seasons", new_callable=AsyncMock, return_value=[])
async def test_existing_show_without_seasons_reports_no_episodes(mock_get_seasons, mock_get_show):
    error = await _call("get_seasons", {"epguides_key": "test"})

    assert error["data"]["code"] == "no_episodes"
    assert error["data"]["context"] == {"epguides_key": "test"}


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show", new_callable=AsyncMock, return_value=None)
async def test_unreachable_catalogue_is_internal_error_with_retry_hint(mock_get_show, show_catalogue_available):
    show_catalogue_available.return_value = False

    error = await _call("get_show", {"epguides_key": "test"})

    assert error["code"] == -32603
    assert error["data"]["code"] == "upstream_unavailable"
    assert error["data"]["context"] == {"upstream_source": "epguides.com", "epguides_key": "test"}
    assert error["message"].endswith("Retry in a few minutes.")


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.search_shows", new_callable=AsyncMock)
async def test_external_service_error_without_mcp_hint_keeps_message(mock_search):
    mock_search.side_effect = ExternalServiceError("TVMaze timed out", source=UpstreamSource.TVMAZE, hint=None)

    error = await _call("search_shows", {"query": "breaking"})

    assert error["code"] == -32603
    assert error["message"] == "TVMaze timed out Retry in a few minutes."


@pytest.mark.asyncio
async def test_unknown_tool_lists_available_tools():
    error = await _call("get_movie", {})

    assert error["code"] == -32601
    assert error["message"].startswith("Unknown tool: 'get_movie'. Available tools: search_shows, lookup_by_imdb_id")
    assert error["message"].endswith("Call tools/list for their argument schemas.")


@pytest.mark.asyncio
async def test_unknown_method_lists_supported_methods():
    response = await MCPServer().handle_request({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})

    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == (
        "Method not found: 'prompts/list'. Supported methods: initialize, resources/list, resources/read, "
        "tools/list, tools/call."
    )


@pytest.mark.asyncio
async def test_unknown_resource_lists_available_resources():
    response = await MCPServer().handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "epguides://movies"}}
    )

    assert response["error"]["message"] == (
        "Unknown resource: 'epguides://movies'. Available resources: epguides://shows (see resources/list)."
    )


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.search_shows", new_callable=AsyncMock, side_effect=RuntimeError("boom"))
async def test_unexpected_tool_failure_names_tool_and_exception(mock_search):
    error = await _call("search_shows", {"query": "x"})

    assert error["code"] == -32603
    assert error["message"] == "Tool execution error in 'search_shows': RuntimeError: boom. Retry the call."
    assert error["data"] == {"code": "internal_error", "tool": "search_shows"}


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show", new_callable=AsyncMock, return_value=_SHOW)
@patch("app.mcp.server.show_service.get_episodes", new_callable=AsyncMock, return_value=[])
async def test_existing_show_with_empty_episode_list_reports_no_episodes(mock_get_episodes, mock_get_show):
    error = await _call("get_episodes", {"epguides_key": "test"})

    assert error["data"]["code"] == "no_episodes"
    assert error["message"].startswith("No episodes found for show 'test'")
    assert error["message"].endswith("Retry later; the episode list may not have loaded from upstream yet.")
