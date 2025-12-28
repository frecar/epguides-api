"""
MCP (Model Context Protocol) HTTP endpoints.

Exposes MCP server functionality over HTTP for network access.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)

router = APIRouter()
mcp_server = MCPServer()


@router.post("/mcp", summary="MCP JSON-RPC endpoint")
async def mcp_endpoint(request: Request):
    """
    Handle MCP JSON-RPC 2.0 requests over HTTP.

    This endpoint allows network-based access to the MCP server.
    Send JSON-RPC 2.0 requests as POST with JSON body.
    """
    try:
        body = await request.json()
        response = await mcp_server.handle_request(body)
        return JSONResponse(content=response)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}") from e
    except Exception as e:
        logger.error(f"Error handling MCP request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}") from e


@router.get("/mcp/health", summary="MCP server health check")
async def mcp_health():
    """Check if MCP server is available."""
    return {"status": "healthy", "service": "mcp-server"}
