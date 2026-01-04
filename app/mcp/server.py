"""
MCP (Model Context Protocol) server implementation.

Exposes TV show data and operations as MCP resources and tools
for AI assistants to consume.
"""

import json
import logging
from typing import Any

from app.core.constants import MCP_PROTOCOL_VERSION, VERSION
from app.services import show_service

logger = logging.getLogger(__name__)


# =============================================================================
# JSON-RPC Error Codes
# =============================================================================

_ERROR_METHOD_NOT_FOUND = -32601
_ERROR_INVALID_PARAMS = -32602
_ERROR_INTERNAL = -32603


# =============================================================================
# Tool Definitions
# =============================================================================

_TOOLS = [
    {
        "name": "search_shows",
        "description": "Search for TV shows by title",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (show title)",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_show",
        "description": "Get detailed information about a specific TV show",
        "inputSchema": {
            "type": "object",
            "properties": {
                "epguides_key": {
                    "type": "string",
                    "description": "Epguides show identifier (e.g., 'BreakingBad')",
                }
            },
            "required": ["epguides_key"],
        },
    },
    {
        "name": "get_episodes",
        "description": "Get all episodes for a TV show",
        "inputSchema": {
            "type": "object",
            "properties": {
                "epguides_key": {
                    "type": "string",
                    "description": "Epguides show identifier",
                }
            },
            "required": ["epguides_key"],
        },
    },
    {
        "name": "get_next_episode",
        "description": "Get the next unreleased episode for a show",
        "inputSchema": {
            "type": "object",
            "properties": {
                "epguides_key": {
                    "type": "string",
                    "description": "Epguides show identifier",
                }
            },
            "required": ["epguides_key"],
        },
    },
    {
        "name": "get_latest_episode",
        "description": "Get the most recently released episode for a show",
        "inputSchema": {
            "type": "object",
            "properties": {
                "epguides_key": {
                    "type": "string",
                    "description": "Epguides show identifier",
                }
            },
            "required": ["epguides_key"],
        },
    },
]


# =============================================================================
# MCP Server
# =============================================================================


class MCPServer:
    """
    MCP server for Epguides API.

    Implements JSON-RPC 2.0 protocol for MCP communication.
    """

    def __init__(self) -> None:
        self._request_id: str | int | None = None

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Route incoming MCP request to appropriate handler.

        Args:
            request: JSON-RPC 2.0 request object.

        Returns:
            JSON-RPC 2.0 response object.
        """
        method = request.get("method", "")
        params = request.get("params", {})
        self._request_id = request.get("id")

        # Route to handler
        handlers = {
            "initialize": self._handle_initialize,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resource_read,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tool_call,
        }

        handler = handlers.get(method)
        if not handler:
            return self._error(_ERROR_METHOD_NOT_FOUND, f"Method not found: {method}")

        try:
            return await handler(params)
        except Exception as e:
            logger.exception("Error handling %s request", method)
            return self._error(_ERROR_INTERNAL, f"Internal error: {e}")

    # -------------------------------------------------------------------------
    # Protocol Handlers
    # -------------------------------------------------------------------------

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle MCP initialize request."""
        return self._success(
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"resources": {}, "tools": {}},
                "serverInfo": {"name": "epguides-api", "version": VERSION},
            }
        )

    async def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """List available MCP resources."""
        return self._success(
            {
                "resources": [
                    {
                        "uri": "epguides://shows",
                        "name": "All Shows",
                        "description": "Complete list of all TV shows",
                        "mimeType": "application/json",
                    },
                ],
            }
        )

    async def _handle_resource_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read an MCP resource."""
        uri = params.get("uri", "")

        if uri != "epguides://shows":
            return self._error(_ERROR_INVALID_PARAMS, f"Unknown resource: {uri}")

        shows = await show_service.get_all_shows()
        # Limit for performance
        shows_data = [show.model_dump() for show in shows[:100]]

        return self._success(
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(shows_data, indent=2, default=str),
                    }
                ],
            }
        )

    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """List available MCP tools."""
        return self._success({"tools": _TOOLS})

    async def _handle_tool_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an MCP tool."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # Route to tool handler
        tool_handlers = {
            "search_shows": self._tool_search_shows,
            "get_show": self._tool_get_show,
            "get_episodes": self._tool_get_episodes,
            "get_next_episode": self._tool_get_next_episode,
            "get_latest_episode": self._tool_get_latest_episode,
        }

        handler = tool_handlers.get(tool_name)
        if not handler:
            return self._error(_ERROR_METHOD_NOT_FOUND, f"Unknown tool: {tool_name}")

        try:
            return await handler(arguments)
        except Exception as e:
            logger.exception("Error executing tool %s", tool_name)
            return self._error(_ERROR_INTERNAL, f"Tool execution error: {e}")

    # -------------------------------------------------------------------------
    # Tool Implementations
    # -------------------------------------------------------------------------

    async def _tool_search_shows(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search for shows by title."""
        query = args.get("query", "")
        shows = await show_service.search_shows(query)
        result = [show.model_dump() for show in shows[:50]]
        return self._success(self._text_content(json.dumps(result, indent=2, default=str)))

    async def _tool_get_show(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get show details."""
        epguides_key = args.get("epguides_key", "")
        show = await show_service.get_show(epguides_key)

        if not show:
            return self._error(_ERROR_INVALID_PARAMS, f"Show not found: {epguides_key}")

        return self._success(self._text_content(json.dumps(show.model_dump(), indent=2, default=str)))

    async def _tool_get_episodes(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all episodes for a show."""
        epguides_key = args.get("epguides_key", "")
        episodes = await show_service.get_episodes(epguides_key)

        if not episodes:
            return self._error(_ERROR_INVALID_PARAMS, f"No episodes found for: {epguides_key}")

        result = [ep.model_dump() for ep in episodes]
        return self._success(self._text_content(json.dumps(result, indent=2, default=str)))

    async def _tool_get_next_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get next unreleased episode."""
        epguides_key = args.get("epguides_key", "")
        episodes = await show_service.get_episodes(epguides_key)

        if not episodes:
            return self._error(_ERROR_INVALID_PARAMS, f"No episodes found for: {epguides_key}")

        for ep in episodes:
            if not ep.is_released and ep.title:
                return self._success(self._text_content(json.dumps(ep.model_dump(), indent=2, default=str)))

        return self._error(_ERROR_INVALID_PARAMS, "No unreleased episodes found")

    async def _tool_get_latest_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get most recently released episode."""
        epguides_key = args.get("epguides_key", "")
        episodes = await show_service.get_episodes(epguides_key)

        if not episodes:
            return self._error(_ERROR_INVALID_PARAMS, f"No episodes found for: {epguides_key}")

        released = [ep for ep in episodes if ep.is_released]
        if not released:
            return self._error(_ERROR_INVALID_PARAMS, "No released episodes found")

        last_ep = released[-1]
        return self._success(self._text_content(json.dumps(last_ep.model_dump(), indent=2, default=str)))

    # -------------------------------------------------------------------------
    # Response Helpers
    # -------------------------------------------------------------------------

    def _success(self, result: dict[str, Any]) -> dict[str, Any]:
        """Build successful JSON-RPC response."""
        return {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "result": result,
        }

    def _error(self, code: int, message: str) -> dict[str, Any]:
        """Build error JSON-RPC response."""
        return {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "error": {"code": code, "message": message},
        }

    def _text_content(self, text: str) -> dict[str, Any]:
        """Build MCP text content response."""
        return {"content": [{"type": "text", "text": text}]}
