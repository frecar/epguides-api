"""
JSON-RPC 2.0 schemas for MCP (Model Context Protocol).

These schemas define the request/response format for MCP over HTTP.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Example Requests (for OpenAPI documentation)
# =============================================================================

_EXAMPLE_INITIALIZE: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {},
}

_EXAMPLE_TOOLS_LIST: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
}

_EXAMPLE_TOOLS_CALL: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "search_shows",
        "arguments": {"query": "breaking"},
    },
}

_EXAMPLE_RESOURCES_LIST: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 4,
    "method": "resources/list",
    "params": {},
}


# =============================================================================
# Request/Response Models
# =============================================================================


class JSONRPCRequest(BaseModel):
    """
    JSON-RPC 2.0 request model.

    Used for all MCP HTTP endpoint requests.
    """

    jsonrpc: str = Field(
        default="2.0",
        description="JSON-RPC version (must be '2.0')",
        pattern=r"^2\.0$",
    )
    id: str | int | None = Field(
        default=None,
        description="Request ID for response correlation",
    )
    method: str = Field(
        ...,
        description="Method to call",
        examples=["initialize", "tools/list", "tools/call", "resources/list", "resources/read"],
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Method parameters",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": _EXAMPLE_TOOLS_LIST,
            "examples": [
                _EXAMPLE_INITIALIZE,
                _EXAMPLE_TOOLS_LIST,
                _EXAMPLE_TOOLS_CALL,
                _EXAMPLE_RESOURCES_LIST,
            ],
        }
    )


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: Any | None = Field(default=None, description="Additional error data")


class JSONRPCResponse(BaseModel):
    """
    JSON-RPC 2.0 response model.

    Either result or error will be present, never both.
    """

    jsonrpc: str = Field(default="2.0", description="JSON-RPC version")
    id: str | int | None = Field(default=None, description="Request ID")
    result: dict[str, Any] | None = Field(default=None, description="Success result")
    error: JSONRPCError | None = Field(default=None, description="Error details")
