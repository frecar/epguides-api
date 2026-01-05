"""
Tests for MCP HTTP endpoints.

Tests the HTTP interface for the MCP server.
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.main import app
from app.models.schemas import create_show_schema


@pytest.fixture
async def async_client():
    """Async HTTP client for testing."""
    async with AsyncClient(app=app, base_url="http://test") as client:
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
