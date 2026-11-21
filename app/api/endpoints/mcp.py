"""
MCP (Model Context Protocol) HTTP endpoints.

Exposes MCP server functionality over HTTP for network access.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, status
from fastapi.responses import JSONResponse

from app.mcp.server import MCPServer
from app.models.mcp_schemas import JSONRPCRequest

logger = logging.getLogger(__name__)

router = APIRouter()

_mcp_server = MCPServer()


@router.post(
    "/mcp",
    summary="🤖 MCP JSON-RPC endpoint",
    response_model_exclude_none=True,
    response_description="JSON-RPC 2.0 response",
)
async def mcp_endpoint(
    request: Annotated[
        JSONRPCRequest,
        Body(
            openapi_examples={
                "initialize": {
                    "summary": "Get the protocol version and server capabilities",
                    "value": {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                },
                "tools": {
                    "summary": "Discover available tools and argument schemas",
                    "value": {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                },
                "resources": {
                    "summary": "Discover readable resources",
                    "value": {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}},
                },
                "search": {
                    "summary": "Search for TV shows",
                    "value": {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "search_shows", "arguments": {"query": "breaking"}},
                    },
                },
            },
        ),
    ],
) -> JSONResponse:
    try:
        body = request.model_dump(exclude_none=True)
        response = await _mcp_server.handle_request(body)
        return JSONResponse(content=response)
    except Exception as e:
        logger.exception("Error handling MCP request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {e}",
        ) from e


@router.get(
    "/mcp/health",
    summary="💚 MCP health check",
)
async def mcp_health() -> dict[str, str]:
    """
    **Check MCP server health.**

    Use for monitoring and load balancer health checks.

    Returns `{"status": "healthy"}` when operational.
    """
    return {"status": "healthy", "service": "mcp-server"}
