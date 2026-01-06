"""
MCP server tests.

Tests the Model Context Protocol server implementation.
"""

from unittest.mock import patch

import pytest

from app.mcp.server import MCPServer
from app.models.schemas import create_show_schema


@pytest.fixture
def mcp_server():
    """Create MCP server instance."""
    return MCPServer()


@pytest.mark.asyncio
async def test_initialize(mcp_server):
    """Test initialize request."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "initialize",
        "params": {},
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "1"
    assert "result" in response
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["serverInfo"]["name"] == "epguides-api"


@pytest.mark.asyncio
async def test_resources_list(mcp_server):
    """Test resources list."""
    request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "resources/list",
        "params": {},
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert "result" in response
    assert "resources" in response["result"]
    assert len(response["result"]["resources"]) > 0


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_all_shows")
async def test_resource_read(mock_get_all_shows, mcp_server):
    """Test resource read."""

    mock_shows = [
        create_show_schema(
            epguides_key="test",
            title="Test Show",
        )
    ]
    mock_get_all_shows.return_value = mock_shows

    request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "resources/read",
        "params": {"uri": "epguides://shows"},
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert "result" in response
    assert "contents" in response["result"]


@pytest.mark.asyncio
async def test_tools_list(mcp_server):
    """Test tools list."""
    request = {
        "jsonrpc": "2.0",
        "id": "4",
        "method": "tools/list",
        "params": {},
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert "result" in response
    assert "tools" in response["result"]
    assert len(response["result"]["tools"]) == 6


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.search_shows")
async def test_tool_search_shows(mock_search_shows, mcp_server):
    """Test search_shows tool."""

    mock_shows = [
        create_show_schema(
            epguides_key="breakingbad",
            title="Breaking Bad",
        )
    ]
    mock_search_shows.return_value = mock_shows

    request = {
        "jsonrpc": "2.0",
        "id": "5",
        "method": "tools/call",
        "params": {
            "name": "search_shows",
            "arguments": {"query": "breaking"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert "result" in response
    assert "content" in response["result"]


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show")
async def test_tool_get_show(mock_get_show, mcp_server):
    """Test get_show tool."""

    mock_show = create_show_schema(
        epguides_key="breakingbad",
        title="Breaking Bad",
    )
    mock_get_show.return_value = mock_show

    request = {
        "jsonrpc": "2.0",
        "id": "6",
        "method": "tools/call",
        "params": {
            "name": "get_show",
            "arguments": {"epguides_key": "breakingbad"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert "result" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show")
async def test_tool_get_show_not_found(mock_get_show, mcp_server):
    """Test get_show tool with non-existent show."""
    mock_get_show.return_value = None

    request = {
        "jsonrpc": "2.0",
        "id": "7",
        "method": "tools/call",
        "params": {
            "name": "get_show",
            "arguments": {"epguides_key": "nonexistent"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert "error" in response
    assert response["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_unknown_method(mcp_server):
    """Test unknown method handling."""
    request = {
        "jsonrpc": "2.0",
        "id": "8",
        "method": "unknown/method",
        "params": {},
    }
    response = await mcp_server.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert "error" in response
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_unknown_tool(mcp_server):
    """Test unknown tool handling."""
    request = {
        "jsonrpc": "2.0",
        "id": "9",
        "method": "tools/call",
        "params": {
            "name": "unknown_tool",
            "arguments": {},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_resource_read_unknown_uri(mcp_server):
    """Test resource read with unknown URI."""
    request = {
        "jsonrpc": "2.0",
        "id": "10",
        "method": "resources/read",
        "params": {"uri": "epguides://unknown"},
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_episodes(mock_get_episodes, mcp_server):
    """Test get_episodes tool."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    mock_episodes = [
        EpisodeSchema(season=1, number=1, title="Pilot", release_date=date(2020, 1, 1), is_released=True),
    ]
    mock_get_episodes.return_value = mock_episodes

    request = {
        "jsonrpc": "2.0",
        "id": "11",
        "method": "tools/call",
        "params": {
            "name": "get_episodes",
            "arguments": {"epguides_key": "test"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "result" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_episodes_not_found(mock_get_episodes, mcp_server):
    """Test get_episodes tool with no episodes."""
    mock_get_episodes.return_value = []

    request = {
        "jsonrpc": "2.0",
        "id": "12",
        "method": "tools/call",
        "params": {
            "name": "get_episodes",
            "arguments": {"epguides_key": "nonexistent"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_next_episode(mock_get_episodes, mcp_server):
    """Test get_next_episode tool."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    mock_episodes = [
        EpisodeSchema(season=1, number=1, title="Released", release_date=date(2020, 1, 1), is_released=True),
        EpisodeSchema(season=1, number=2, title="Upcoming", release_date=date(2030, 1, 1), is_released=False),
    ]
    mock_get_episodes.return_value = mock_episodes

    request = {
        "jsonrpc": "2.0",
        "id": "13",
        "method": "tools/call",
        "params": {
            "name": "get_next_episode",
            "arguments": {"epguides_key": "test"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "result" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_next_episode_no_unreleased(mock_get_episodes, mcp_server):
    """Test get_next_episode tool with no unreleased episodes."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    mock_episodes = [
        EpisodeSchema(season=1, number=1, title="Released", release_date=date(2020, 1, 1), is_released=True),
    ]
    mock_get_episodes.return_value = mock_episodes

    request = {
        "jsonrpc": "2.0",
        "id": "14",
        "method": "tools/call",
        "params": {
            "name": "get_next_episode",
            "arguments": {"epguides_key": "test"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_latest_episode(mock_get_episodes, mcp_server):
    """Test get_latest_episode tool."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    mock_episodes = [
        EpisodeSchema(season=1, number=1, title="First", release_date=date(2020, 1, 1), is_released=True),
        EpisodeSchema(season=1, number=2, title="Latest", release_date=date(2020, 2, 1), is_released=True),
    ]
    mock_get_episodes.return_value = mock_episodes

    request = {
        "jsonrpc": "2.0",
        "id": "15",
        "method": "tools/call",
        "params": {
            "name": "get_latest_episode",
            "arguments": {"epguides_key": "test"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "result" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_latest_episode_no_released(mock_get_episodes, mcp_server):
    """Test get_latest_episode tool with no released episodes."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    mock_episodes = [
        EpisodeSchema(season=1, number=1, title="Upcoming", release_date=date(2030, 1, 1), is_released=False),
    ]
    mock_get_episodes.return_value = mock_episodes

    request = {
        "jsonrpc": "2.0",
        "id": "16",
        "method": "tools/call",
        "params": {
            "name": "get_latest_episode",
            "arguments": {"epguides_key": "test"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_seasons")
async def test_tool_get_seasons(mock_get_seasons, mcp_server):
    """Test get_seasons tool."""
    from datetime import date

    from app.models.schemas import SeasonSchema

    mock_seasons = [
        SeasonSchema(
            number=1,
            episode_count=10,
            premiere_date=date(2020, 1, 1),
            end_date=date(2020, 3, 1),
            api_episodes_url="http://example.com/episodes",
        ),
    ]
    mock_get_seasons.return_value = mock_seasons

    request = {
        "jsonrpc": "2.0",
        "id": "17",
        "method": "tools/call",
        "params": {
            "name": "get_seasons",
            "arguments": {"epguides_key": "test"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "result" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_seasons")
async def test_tool_get_seasons_not_found(mock_get_seasons, mcp_server):
    """Test get_seasons tool with no seasons."""
    mock_get_seasons.return_value = []

    request = {
        "jsonrpc": "2.0",
        "id": "18",
        "method": "tools/call",
        "params": {
            "name": "get_seasons",
            "arguments": {"epguides_key": "nonexistent"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_next_episode_no_episodes(mock_get_episodes, mcp_server):
    """Test get_next_episode tool with no episodes at all."""
    mock_get_episodes.return_value = []

    request = {
        "jsonrpc": "2.0",
        "id": "19",
        "method": "tools/call",
        "params": {
            "name": "get_next_episode",
            "arguments": {"epguides_key": "nonexistent"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_tool_get_latest_episode_no_episodes(mock_get_episodes, mcp_server):
    """Test get_latest_episode tool with no episodes at all."""
    mock_get_episodes.return_value = []

    request = {
        "jsonrpc": "2.0",
        "id": "20",
        "method": "tools/call",
        "params": {
            "name": "get_latest_episode",
            "arguments": {"epguides_key": "nonexistent"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.search_shows")
async def test_tool_call_execution_error(mock_search, mcp_server):
    """Test tools/call handles exceptions during tool execution."""
    mock_search.side_effect = Exception("Database error")

    request = {
        "jsonrpc": "2.0",
        "id": "21",
        "method": "tools/call",
        "params": {
            "name": "search_shows",
            "arguments": {"query": "test"},
        },
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response
    assert response["error"]["code"] == -32603  # Internal error


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_all_shows")
async def test_resources_read_execution_error(mock_get_all, mcp_server):
    """Test resources/read handles exceptions during execution."""
    mock_get_all.side_effect = Exception("Service error")

    request = {
        "jsonrpc": "2.0",
        "id": "22",
        "method": "resources/read",
        "params": {"uri": "epguides://shows"},
    }
    response = await mcp_server.handle_request(request)
    assert "error" in response
