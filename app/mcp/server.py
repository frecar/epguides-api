"""
MCP (Model Context Protocol) server implementation.

Exposes TV show data and operations as MCP resources and tools for AI assistants.
"""

import asyncio
import json
import logging
import sys
from typing import Any

from app.core.constants import MCP_PROTOCOL_VERSION, VERSION
from app.services import show_service

logger = logging.getLogger(__name__)


class MCPServer:
    """MCP server for Epguides API."""

    def __init__(self) -> None:
        self.request_id: str | None = None

    def _jsonrpc_response(self, result: dict[str, Any]) -> dict[str, Any]:
        """Helper to build JSON-RPC 2.0 response."""
        return {"jsonrpc": "2.0", "id": self.request_id, "result": result}

    def _text_content(self, text: str) -> dict[str, Any]:
        """Helper to build text content response."""
        return {
            "content": [
                {
                    "type": "text",
                    "text": text,
                }
            ],
        }

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle incoming MCP request."""
        method = request.get("method")
        params = request.get("params", {})
        self.request_id = request.get("id")

        try:
            if method == "initialize":
                return await self.handle_initialize(params)
            elif method == "resources/list":
                return await self.handle_resources_list()
            elif method == "resources/read":
                return await self.handle_resource_read(params)
            elif method == "tools/list":
                return await self.handle_tools_list()
            elif method == "tools/call":
                return await self.handle_tool_call(params)
            else:
                return self.error_response(-32601, f"Method not found: {method}")
        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            return self.error_response(-32603, f"Internal error: {str(e)}")

    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request."""
        return {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "resources": {},
                    "tools": {},
                },
                "serverInfo": {
                    "name": "epguides-api",
                    "version": VERSION,
                },
            },
        }

    async def handle_resources_list(self) -> dict[str, Any]:
        """List available resources."""
        return {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "result": {
                "resources": [
                    {
                        "uri": "epguides://shows",
                        "name": "All Shows",
                        "description": "Complete list of all TV shows from epguides.com",
                        "mimeType": "application/json",
                    },
                ],
            },
        }

    async def handle_resource_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a resource."""
        uri = params.get("uri", "")

        if uri == "epguides://shows":
            shows = await show_service.get_all_shows()
            # Limit to first 100 for performance
            shows_data = [show.model_dump() for show in shows[:100]]
            return {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "result": {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(shows_data, indent=2, default=str),
                        }
                    ],
                },
            }
        else:
            return self.error_response(-32602, f"Unknown resource: {uri}")

    async def handle_tools_list(self) -> dict[str, Any]:
        """List available tools."""
        return {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "result": {
                "tools": [
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
                                    "description": "Epguides show key/identifier (e.g., 'BreakingBad')",
                                }
                            },
                            "required": ["epguides_key"],
                        },
                    },
                    {
                        "name": "get_episodes",
                        "description": "Get episodes for a TV show, optionally filtered",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "epguides_key": {
                                    "type": "string",
                                    "description": "Epguides show key/identifier (e.g., 'BreakingBad')",
                                },
                                "filter": {
                                    "type": "string",
                                    "description": "Optional filter (e.g., 'season 2', 's2e5', '2008')",
                                },
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
                                    "description": "Epguides show key/identifier (e.g., 'BreakingBad')",
                                }
                            },
                            "required": ["epguides_key"],
                        },
                    },
                    {
                        "name": "get_last_episode",
                        "description": "Get the last released episode for a show",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "epguides_key": {
                                    "type": "string",
                                    "description": "Epguides show key/identifier (e.g., 'BreakingBad')",
                                }
                            },
                            "required": ["epguides_key"],
                        },
                    },
                ],
            },
        }

    async def handle_tool_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tool call."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        try:
            if tool_name == "search_shows":
                query = arguments.get("query", "")
                shows = await show_service.search_shows(query)
                result = [show.model_dump() for show in shows[:50]]  # Limit results
                return self._jsonrpc_response(self._text_content(json.dumps(result, indent=2, default=str)))

            elif tool_name == "get_show":
                epguides_key = arguments.get("epguides_key", "")
                show = await show_service.get_show(epguides_key)
                if not show:
                    return self.error_response(-32602, f"Show not found: {epguides_key}")
                return self._jsonrpc_response(self._text_content(json.dumps(show.model_dump(), indent=2, default=str)))

            elif tool_name == "get_episodes":
                epguides_key = arguments.get("epguides_key", "")
                filter_query = arguments.get("filter")
                episodes = await show_service.get_episodes(epguides_key, filter_query=filter_query)
                if not episodes:
                    return self.error_response(-32602, f"Episodes not found for show: {epguides_key}")
                result = [ep.model_dump() for ep in episodes]
                return self._jsonrpc_response(self._text_content(json.dumps(result, indent=2, default=str)))

            elif tool_name == "get_next_episode":
                epguides_key = arguments.get("epguides_key", "")
                episodes = await show_service.get_episodes(epguides_key)
                if not episodes:
                    return self.error_response(-32602, f"Episodes not found for show: {epguides_key}")
                for ep in episodes:
                    if not ep.is_released and ep.title:
                        return self._jsonrpc_response(
                            self._text_content(json.dumps(ep.model_dump(), indent=2, default=str))
                        )
                return self.error_response(-32602, "Next episode not found")

            elif tool_name == "get_latest_episode":
                epguides_key = arguments.get("epguides_key", "")
                episodes = await show_service.get_episodes(epguides_key)
                if not episodes:
                    return self.error_response(-32602, f"Episodes not found for show: {epguides_key}")
                released = [ep for ep in episodes if ep.is_released]
                if not released:
                    return self.error_response(-32602, "No released episodes found")
                last_ep = released[-1]
                return self._jsonrpc_response(
                    self._text_content(json.dumps(last_ep.model_dump(), indent=2, default=str))
                )

            else:
                return self.error_response(-32601, f"Unknown tool: {tool_name}")

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return self.error_response(-32603, f"Tool execution error: {str(e)}")

    def error_response(self, code: int, message: str) -> dict[str, Any]:
        """Create error response."""
        return {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


async def run_mcp_server():
    """Run MCP server on stdio."""
    server = MCPServer()

    # Setup logging to stderr (stdio is for JSON-RPC)
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("MCP server starting on stdio")

    # Read from stdin, write to stdout
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            response = await server.handle_request(request)
            print(json.dumps(response), flush=True)

        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {str(e)}",
                },
            }
            print(json.dumps(error_response), flush=True)
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}",
                },
            }
            print(json.dumps(error_response), flush=True)


def main():
    """Main entry point for MCP server."""
    try:
        asyncio.run(run_mcp_server())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
