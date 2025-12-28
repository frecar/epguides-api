"""
MCP (Model Context Protocol) request and response schemas.

Defines Pydantic models for JSON-RPC 2.0 requests and responses.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Example requests for different methods
EXAMPLE_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {},
}

EXAMPLE_TOOLS_LIST = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
}

EXAMPLE_TOOLS_CALL = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "search_shows",
        "arguments": {"query": "breaking"},
    },
}

EXAMPLE_RESOURCES_LIST = {
    "jsonrpc": "2.0",
    "id": 4,
    "method": "resources/list",
    "params": {},
}


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request model."""

    jsonrpc: str = Field("2.0", description="JSON-RPC version (must be '2.0')")
    id: str | int | None = Field(None, description="Request ID (optional, can be string or number)")
    method: str = Field(
        ...,
        description="Method name. Available methods: 'initialize', 'tools/list', 'tools/call', 'resources/list', 'resources/read'",
        examples=["initialize", "tools/list", "tools/call", "resources/list", "resources/read"],
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Method parameters. For 'tools/call', use: {'name': 'tool_name', 'arguments': {...}}",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": EXAMPLE_TOOLS_LIST,
            "examples": [
                EXAMPLE_INITIALIZE,
                EXAMPLE_TOOLS_LIST,
                EXAMPLE_TOOLS_CALL,
                EXAMPLE_RESOURCES_LIST,
            ],
        }
    )


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response model."""

    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    id: str | int | None = Field(None, description="Request ID")
    result: dict[str, Any] | None = Field(None, description="Result (on success)")
    error: dict[str, Any] | None = Field(None, description="Error (on failure)")

