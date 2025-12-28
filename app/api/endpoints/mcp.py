"""
MCP (Model Context Protocol) HTTP endpoints.

Exposes MCP server functionality over HTTP for network access.
"""

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.mcp.server import MCPServer
from app.models.mcp_schemas import JSONRPCRequest

logger = logging.getLogger(__name__)

router = APIRouter()
mcp_server = MCPServer()


@router.post(
    "/mcp",
    summary="MCP JSON-RPC endpoint",
    response_model_exclude_none=True,
    response_description="JSON-RPC 2.0 response with result or error",
)
async def mcp_endpoint(request: JSONRPCRequest):
    """
    Handle MCP JSON-RPC 2.0 requests over HTTP.

    This endpoint allows network-based access to the MCP server.
    Send JSON-RPC 2.0 requests as POST with JSON body.

    **Available Methods:**
    - `initialize` - Initialize the MCP connection
    - `tools/list` - List available tools
    - `tools/call` - Call a tool (e.g., search_shows, get_show, get_episodes)
    - `resources/list` - List available resources
    - `resources/read` - Read a resource (requires `uri` in params)

    **Example: List Tools**
    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "method": "tools/list",
      "params": {}
    }
    ```

    **Example: Search Shows**
    ```json
    {
      "jsonrpc": "2.0",
      "id": 2,
      "method": "tools/call",
      "params": {
        "name": "search_shows",
        "arguments": {"query": "breaking"}
      }
    }
    ```
    """
    try:
        # Convert Pydantic model to dict for MCP server
        body = request.model_dump(exclude_none=True)
        response = await mcp_server.handle_request(body)
        return JSONResponse(content=response)
    except Exception as e:
        logger.error(f"Error handling MCP request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}") from e


@router.get("/mcp/health", summary="MCP server health check")
async def mcp_health():
    """Check if MCP server is available."""
    return {"status": "healthy", "service": "mcp-server"}
