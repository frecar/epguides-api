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
    summary="🤖 MCP JSON-RPC endpoint",
    response_model_exclude_none=True,
    response_description="JSON-RPC 2.0 response",
)
async def mcp_endpoint(request: JSONRPCRequest) -> JSONResponse:
    """
    **Model Context Protocol** endpoint for AI assistant integration.

    Send JSON-RPC 2.0 requests to interact with TV show data programmatically.

    ---

    ### 📚 Available Methods

    | Method | Description |
    |--------|-------------|
    | `initialize` | Initialize connection, get server info |
    | `tools/list` | List all available tools |
    | `tools/call` | Execute a tool |
    | `resources/list` | List available resources |
    | `resources/read` | Read a resource |

    ---

    ### 🔧 Available Tools

    | Tool | Description |
    |------|-------------|
    | `search_shows` | Search TV shows by title |
    | `get_show` | Get show metadata |
    | `get_episodes` | Get episode list |
    | `get_next_episode` | Get next unreleased episode |
    | `get_latest_episode` | Get latest aired episode |

    ---

    ### 📝 Examples

    **Initialize:**
    ```json
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    ```

    **List Tools:**
    ```json
    {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    ```

    **Search Shows:**
    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "method": "tools/call",
      "params": {"name": "search_shows", "arguments": {"query": "breaking"}}
    }
    ```

    **Get Episodes:**
    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "method": "tools/call",
      "params": {"name": "get_episodes", "arguments": {"epguides_key": "BreakingBad"}}
    }
    ```

    ---

    ### 📖 Documentation
    See [MCP Server docs](https://epguides-api.readthedocs.io/en/latest/mcp-server/) for full reference.
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
    summary="💚 MCP health check",
)
async def mcp_health() -> dict[str, str]:
    """
    **Check MCP server health.**

    Use for monitoring and load balancer health checks.

    Returns `{"status": "healthy"}` when operational.
    """
    return {"status": "healthy", "service": "mcp-server"}
