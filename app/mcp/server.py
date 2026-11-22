"""
MCP (Model Context Protocol) server implementation.

Exposes TV show data and operations as MCP resources and tools
for AI assistants to consume.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.constants import MCP_PROTOCOL_VERSION, VERSION
from app.exceptions import (
    IMDB_ID_EXAMPLE,
    SHOW_KEY_EXAMPLE,
    EpguidesAPIException,
    ErrorCode,
    ExternalServiceError,
    InvalidParameterError,
    NoEpisodesError,
    NoReleasedEpisodeError,
    NoUpcomingEpisodeError,
)
from app.models.schemas import EpisodeSchema
from app.services import llm_service, show_service

logger = logging.getLogger(__name__)

SHOWS_RESOURCE_URI = "epguides://shows"


class JSONRPCErrorCode(IntEnum):
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


_MCP_HINTS: dict[ErrorCode, str] = {
    ErrorCode.SHOW_NOT_FOUND: "Call search_shows with the show title to find its epguides_key.",
    ErrorCode.SEASON_NOT_FOUND: "Call get_seasons with this epguides_key to list valid seasons.",
    ErrorCode.NO_EPISODES: "Retry later; the episode list may not have loaded from upstream yet.",
    ErrorCode.NO_RELEASED_EPISODE: "Call get_next_episode for the first air date.",
    ErrorCode.NO_UPCOMING_EPISODE: "Call get_latest_episode for the most recent episode.",
    ErrorCode.SHOW_FINISHED: "Call get_latest_episode for the final episode.",
    ErrorCode.INVALID_IMDB_ID: f"Pass the ID from the IMDB title URL, for example {IMDB_ID_EXAMPLE!r}.",
    ErrorCode.IMDB_ID_NOT_FOUND: "Call search_shows with the show title instead.",
    ErrorCode.UPSTREAM_UNAVAILABLE: "Retry in a few minutes.",
    ErrorCode.VALIDATION_ERROR: "Call tools/list for the tool's inputSchema.",
}


class _ToolArguments(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class _SearchArguments(_ToolArguments):
    query: str = Field(min_length=1)


class _ImdbArguments(_ToolArguments):
    imdb_id: str = Field(min_length=1)


class _ShowArguments(_ToolArguments):
    epguides_key: str = Field(min_length=1)


class _EpisodeFilterArguments(_ShowArguments):
    season: int | None = Field(default=None, ge=1)
    episode: int | None = Field(default=None, ge=1)
    year: int | None = Field(default=None, ge=1900, le=2100)
    title_search: str | None = None
    nlq: str | None = None


_TOOL_ARGUMENT_EXAMPLES: dict[str, dict[str, object]] = {
    "search_shows": {"query": "breaking"},
    "lookup_by_imdb_id": {"imdb_id": IMDB_ID_EXAMPLE},
    "get_show": {"epguides_key": SHOW_KEY_EXAMPLE},
    "get_episodes": {"epguides_key": SHOW_KEY_EXAMPLE, "season": 1},
    "get_next_episode": {"epguides_key": SHOW_KEY_EXAMPLE},
    "get_latest_episode": {"epguides_key": SHOW_KEY_EXAMPLE},
    "get_seasons": {"epguides_key": SHOW_KEY_EXAMPLE},
}


def _describe_field_error(detail: Mapping[str, Any]) -> dict[str, object]:
    return {
        "field": ".".join(str(part) for part in detail["loc"]) or "arguments",
        "input": None if detail["type"] == "missing" else detail.get("input"),
        "msg": detail["msg"],
    }


class ToolArgumentError(Exception):
    """Tool arguments failed validation; ``field_errors`` lists each field, its input and the reason."""

    def __init__(self, tool_name: str, error: ValidationError) -> None:
        self.tool_name = tool_name
        self.field_errors = [_describe_field_error(detail) for detail in error.errors(include_url=False)]
        described = "; ".join(
            f"{e['field']}: {e['msg']}" if e["input"] is None else f"{e['field']}={e['input']!r}: {e['msg']}"
            for e in self.field_errors
        )
        example = json.dumps(_TOOL_ARGUMENT_EXAMPLES.get(tool_name, {}))
        super().__init__(f"Invalid arguments for tool {tool_name!r}: {described}. Example arguments: {example}.")


def _parse_arguments[ArgsT: _ToolArguments](tool_name: str, model: type[ArgsT], arguments: object) -> ArgsT:
    try:
        return model.model_validate(arguments if arguments is not None else {})
    except ValidationError as err:
        raise ToolArgumentError(tool_name, err) from err


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
        "name": "lookup_by_imdb_id",
        "description": (
            "Look up a show by its IMDB ID. Bridges an IMDB identifier "
            "(e.g. 'tt0903747') to the show's epguides_key, removing the "
            "title-search ambiguity between remakes/originals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "imdb_id": {
                    "type": "string",
                    "description": "IMDB show identifier (format: 'tt' followed by digits)",
                    "pattern": "^tt\\d+$",
                }
            },
            "required": ["imdb_id"],
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
        "description": (
            "Get episodes for a TV show with optional structured filters and "
            "AI-powered natural language queries. Mirrors REST /shows/{key}/episodes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "epguides_key": {
                    "type": "string",
                    "description": "Epguides show identifier",
                },
                "season": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Filter by season number",
                },
                "episode": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Filter by episode number (requires season)",
                },
                "year": {
                    "type": "integer",
                    "minimum": 1900,
                    "maximum": 2100,
                    "description": "Filter by release year",
                },
                "title_search": {
                    "type": "string",
                    "description": "Substring match on episode titles",
                },
                "nlq": {
                    "type": "string",
                    "description": (
                        "Natural-language query (requires LLM). Examples: 'finale episodes', "
                        "'pilot', 'most intense episodes'. Falls back to all matching episodes "
                        "if the LLM is unavailable."
                    ),
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
    {
        "name": "get_seasons",
        "description": "Get all seasons for a TV show with posters and summaries",
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

        handlers = {
            "initialize": self._handle_initialize,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resource_read,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tool_call,
        }

        handler = handlers.get(method)
        if not handler:
            return self._error(
                JSONRPCErrorCode.METHOD_NOT_FOUND,
                f"Method not found: {method!r}. Supported methods: {', '.join(handlers)}.",
            )

        try:
            return await handler(params)
        except Exception as e:
            logger.exception("Error handling %s request", method, extra={"mcp_method": method})
            return self._error(
                JSONRPCErrorCode.INTERNAL_ERROR,
                f"Internal error while handling {method!r}: {type(e).__name__}: {e}. Retry the request.",
            )

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
                        "uri": SHOWS_RESOURCE_URI,
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

        if uri != SHOWS_RESOURCE_URI:
            return self._error(
                JSONRPCErrorCode.INVALID_PARAMS,
                f"Unknown resource: {uri!r}. Available resources: {SHOWS_RESOURCE_URI} (see resources/list).",
            )

        shows = await show_service.get_all_shows()
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
        """Execute an MCP tool, turning domain and argument errors into actionable JSON-RPC errors."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool_handlers: dict[str, Callable[[Any], Awaitable[dict[str, Any]]]] = {
            "search_shows": self._tool_search_shows,
            "lookup_by_imdb_id": self._tool_lookup_by_imdb_id,
            "get_show": self._tool_get_show,
            "get_episodes": self._tool_get_episodes,
            "get_next_episode": self._tool_get_next_episode,
            "get_latest_episode": self._tool_get_latest_episode,
            "get_seasons": self._tool_get_seasons,
        }

        handler = tool_handlers.get(tool_name)
        if not handler:
            return self._error(
                JSONRPCErrorCode.METHOD_NOT_FOUND,
                f"Unknown tool: {tool_name!r}. Available tools: {', '.join(tool_handlers)}. "
                "Call tools/list for their argument schemas.",
            )

        log_fields: dict[str, object] = {"tool": tool_name}
        if isinstance(arguments, dict) and isinstance(arguments.get("epguides_key"), str):
            log_fields["epguides_key"] = arguments["epguides_key"]

        try:
            return await handler(arguments)
        except ToolArgumentError as e:
            logger.info("%s", e, extra=log_fields)
            return self._error(
                JSONRPCErrorCode.INVALID_PARAMS,
                f"{e} {_MCP_HINTS[ErrorCode.VALIDATION_ERROR]}",
                {"code": ErrorCode.VALIDATION_ERROR.value, "tool": tool_name, "errors": e.field_errors},
            )
        except EpguidesAPIException as e:
            return self._domain_error(tool_name, e, log_fields)
        except Exception as e:
            logger.exception("Error executing tool %s", tool_name, extra=log_fields)
            return self._error(
                JSONRPCErrorCode.INTERNAL_ERROR,
                f"Tool execution error in {tool_name!r}: {type(e).__name__}: {e}. Retry the call.",
                {"code": ErrorCode.INTERNAL_ERROR.value, "tool": tool_name},
            )

    def _domain_error(
        self, tool_name: str, error: EpguidesAPIException, log_fields: dict[str, object]
    ) -> dict[str, Any]:
        hint = _MCP_HINTS.get(error.code)
        fields = {**log_fields, "error_code": error.code.value, **error.context}
        if isinstance(error, ExternalServiceError):
            logger.warning("Tool %s upstream failure: %s", tool_name, error.message, extra=fields)
            rpc_code = JSONRPCErrorCode.INTERNAL_ERROR
        else:
            logger.info("Tool %s: %s", tool_name, error.message, extra=fields)
            rpc_code = JSONRPCErrorCode.INVALID_PARAMS
        data: dict[str, object] = {"code": error.code.value, "tool": tool_name}
        if hint:
            data["hint"] = hint
        if error.context:
            data["context"] = error.context
        message = f"{error.message} {hint}" if hint else error.message
        return self._error(rpc_code, message, data)

    async def _tool_search_shows(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search for shows by title."""
        parsed = _parse_arguments("search_shows", _SearchArguments, args)
        shows = await show_service.search_shows(parsed.query)
        result = [show.model_dump() for show in shows[:50]]
        return self._success(self._text_content(json.dumps(result, indent=2, default=str)))

    async def _tool_lookup_by_imdb_id(self, args: dict[str, Any]) -> dict[str, Any]:
        """Bridge an IMDB ID to the show's epguides_key (mirrors REST /shows/by-imdb/{imdb_id})."""
        parsed = _parse_arguments("lookup_by_imdb_id", _ImdbArguments, args)
        show = await show_service.require_show_by_imdb_id(parsed.imdb_id)
        return self._success(self._text_content(json.dumps(show.model_dump(), indent=2, default=str)))

    async def _tool_get_show(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get show details."""
        parsed = _parse_arguments("get_show", _ShowArguments, args)
        show = await show_service.require_show(parsed.epguides_key)
        return self._success(self._text_content(json.dumps(show.model_dump(), indent=2, default=str)))

    async def _episodes_or_raise(self, epguides_key: str) -> list[EpisodeSchema]:
        episodes = await show_service.get_episodes(epguides_key)
        if not episodes:
            await show_service.require_show(epguides_key)
            raise NoEpisodesError(epguides_key)
        return episodes

    async def _tool_get_episodes(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get episodes for a show, optionally filtered by season/episode/year/title/nlq.

        Mirrors REST GET /shows/{key}/episodes — same filter precedence:
        structured filters first, NL query last, no LLM = nlq ignored.
        """
        parsed = _parse_arguments("get_episodes", _EpisodeFilterArguments, args)
        if parsed.episode is not None and parsed.season is None:
            raise InvalidParameterError(
                "episode", parsed.episode, "the episode filter requires season, as in {'season': 1, 'episode': 5}"
            )
        episodes = await self._episodes_or_raise(parsed.epguides_key)

        if parsed.season is not None:
            episodes = [ep for ep in episodes if ep.season == parsed.season]
            if parsed.episode is not None:
                episodes = [ep for ep in episodes if ep.number == parsed.episode]

        if parsed.year is not None:
            episodes = [ep for ep in episodes if ep.release_date.year == parsed.year]

        if parsed.title_search:
            search_lower = parsed.title_search.lower()
            episodes = [ep for ep in episodes if search_lower in ep.title.lower()]

        if parsed.nlq and episodes:
            episodes_as_dicts = [ep.model_dump() for ep in episodes]
            llm_result = await llm_service.parse_natural_language_query(parsed.nlq, episodes_as_dicts)
            if llm_result is not None:
                episodes = [EpisodeSchema(**ep) for ep in llm_result]

        result = [ep.model_dump() for ep in episodes]
        return self._success(self._text_content(json.dumps(result, indent=2, default=str)))

    async def _tool_get_next_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get next unreleased episode."""
        parsed = _parse_arguments("get_next_episode", _ShowArguments, args)
        episodes = await self._episodes_or_raise(parsed.epguides_key)

        for ep in episodes:
            if not ep.is_released and ep.title:
                return self._success(self._text_content(json.dumps(ep.model_dump(), indent=2, default=str)))

        raise NoUpcomingEpisodeError(parsed.epguides_key)

    async def _tool_get_latest_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get most recently released episode."""
        parsed = _parse_arguments("get_latest_episode", _ShowArguments, args)
        episodes = await self._episodes_or_raise(parsed.epguides_key)

        released = [ep for ep in episodes if ep.is_released]
        if not released:
            raise NoReleasedEpisodeError(parsed.epguides_key)

        last_ep = released[-1]
        return self._success(self._text_content(json.dumps(last_ep.model_dump(), indent=2, default=str)))

    async def _tool_get_seasons(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all seasons for a show with posters and summaries."""
        parsed = _parse_arguments("get_seasons", _ShowArguments, args)
        seasons = await show_service.get_seasons(parsed.epguides_key)

        if not seasons:
            await show_service.require_show(parsed.epguides_key)
            raise NoEpisodesError(parsed.epguides_key)

        result = [season.model_dump() for season in seasons]
        return self._success(self._text_content(json.dumps(result, indent=2, default=str)))

    def _success(self, result: dict[str, Any]) -> dict[str, Any]:
        """Build successful JSON-RPC response."""
        return {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "result": result,
        }

    def _error(self, code: JSONRPCErrorCode, message: str, data: dict[str, object] | None = None) -> dict[str, Any]:
        """Build error JSON-RPC response; ``data`` carries the stable error code, hint and context."""
        error: dict[str, object] = {"code": int(code), "message": message}
        if data is not None:
            error["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "error": error,
        }

    def _text_content(self, text: str) -> dict[str, Any]:
        """Build MCP text content response."""
        return {"content": [{"type": "text", "text": text}]}
