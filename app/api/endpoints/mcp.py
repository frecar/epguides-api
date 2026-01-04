"""
MCP (Model Context Protocol) HTTP endpoints.

Exposes MCP server functionality over HTTP for network access.
"""

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.mcp.server import MCPServer
from app.models.mcp_schemas import JSONRPCRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton MCP server instance
_mcp_server = MCPServer()


@router.post(
    "/mcp",
    summary="MCP JSON-RPC endpoint",
    response_model_exclude_none=True,
    response_description="JSON-RPC 2.0 response",
)
async def mcp_endpoint(request: JSONRPCRequest) -> JSONResponse:
    """
    Handle MCP JSON-RPC 2.0 requests over HTTP.

    **Available Methods:**
    - `initialize` - Initialize the MCP connection
    - `tools/list` - List available tools
    - `tools/call` - Call a tool (search_shows, get_show, get_episodes, etc.)
    - `resources/list` - List available resources
    - `resources/read` - Read a resource

    **Example: List Tools**
    ```json
    {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    ```

    **Example: Search Shows**
    ```json
    {
      "jsonrpc": "2.0",
      "id": 2,
      "method": "tools/call",
      "params": {"name": "search_shows", "arguments": {"query": "breaking"}}
    }
    ```
    """
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
    summary="MCP server health check",
)
async def mcp_health() -> dict[str, str]:
    """Check if MCP server is available."""
    return {"status": "healthy", "service": "mcp-server"}
