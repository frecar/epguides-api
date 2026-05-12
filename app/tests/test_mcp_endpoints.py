"""
Tests for MCP HTTP endpoints.

Tests the HTTP interface for the MCP server.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.schemas import create_show_schema


@pytest.fixture
async def async_client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_mcp_health_check(async_client: AsyncClient):
    """Test MCP health check endpoint."""
    response = await async_client.get("/mcp/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "mcp-server"


@pytest.mark.asyncio
async def test_mcp_endpoint_initialize(async_client: AsyncClient):
    """Test MCP endpoint with initialize request."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }
    response = await async_client.post("/mcp", json=request)
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert "result" in data
    assert data["result"]["protocolVersion"] == "2025-06-18"
    assert data["result"]["serverInfo"]["name"] == "epguides-api"


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.search_shows")
async def test_mcp_endpoint_search_shows(mock_search_shows, async_client: AsyncClient):
    """Test MCP endpoint with search_shows tool call."""
    mock_shows = [
        create_show_schema(
            epguides_key="breakingbad",
            title="Breaking Bad",
        )
    ]
    mock_search_shows.return_value = mock_shows

    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "search_shows",
            "arguments": {"query": "breaking"},
        },
    }
    response = await async_client.post("/mcp", json=request)
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 2
    assert "result" in data
    assert "content" in data["result"]


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show_by_imdb_id")
async def test_mcp_endpoint_lookup_by_imdb_id(mock_lookup, async_client: AsyncClient):
    """MCP tool `lookup_by_imdb_id` returns the bridged ShowSchema."""
    mock_lookup.return_value = create_show_schema(epguides_key="breakingbad", title="Breaking Bad", imdb_id="tt0903747")
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "lookup_by_imdb_id",
            "arguments": {"imdb_id": "tt0903747"},
        },
    }
    response = await async_client.post("/mcp", json=request)
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "content" in data["result"]
    # Round-trip the JSON in the text content to confirm the bridge succeeded
    import json as _json

    payload = _json.loads(data["result"]["content"][0]["text"])
    assert payload["epguides_key"] == "breakingbad"
    assert payload["imdb_id"] == "tt0903747"


@pytest.mark.asyncio
async def test_mcp_endpoint_lookup_by_imdb_id_missing_arg(async_client: AsyncClient):
    """Empty imdb_id → invalid_params, NOT a bare exception."""
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "lookup_by_imdb_id", "arguments": {}},
    }
    response = await async_client.post("/mcp", json=request)
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
    assert "imdb_id" in data["error"]["message"]


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show_by_imdb_id")
async def test_mcp_endpoint_lookup_by_imdb_id_not_found(mock_lookup, async_client: AsyncClient):
    """Service returns None → MCP returns an error (mirrors REST's 404)."""
    mock_lookup.return_value = None
    request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "lookup_by_imdb_id", "arguments": {"imdb_id": "tt9999999"}},
    }
    response = await async_client.post("/mcp", json=request)
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
    assert "tt9999999" in data["error"]["message"]


@pytest.mark.asyncio
async def test_mcp_endpoint_invalid_json(async_client: AsyncClient):
    """Test MCP endpoint with invalid JSON."""
    response = await async_client.post(
        "/mcp",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422  # FastAPI validation error for invalid JSON
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_mcp_endpoint_missing_body(async_client: AsyncClient):
    """Test MCP endpoint with missing body."""
    response = await async_client.post("/mcp")
    assert response.status_code == 422  # FastAPI validation error for missing required body


@pytest.mark.asyncio
@patch("app.api.endpoints.mcp._mcp_server")
async def test_mcp_endpoint_internal_error(mock_mcp_server, async_client: AsyncClient):
    """Test MCP endpoint handles internal errors."""
    mock_mcp_server.handle_request.side_effect = Exception("Internal error")

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }
    response = await async_client.post("/mcp", json=request)
    assert response.status_code == 500
    data = response.json()
    assert "Internal error" in data["detail"]
