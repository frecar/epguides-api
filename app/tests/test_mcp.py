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
    assert response["result"]["protocolVersion"] == "2024-11-05"
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
    assert len(response["result"]["tools"]) == 5


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
