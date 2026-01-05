# MCP Server

The project includes a [Model Context Protocol](https://modelcontextprotocol.io/) server for AI assistant integration. The MCP server exposes the same functionality as the REST API but through JSON-RPC 2.0.

## Resources

Resources provide read-only access to data:

| URI | Description |
|-----|-------------|
| `epguides://shows` | Complete list of all TV shows (limited to first 100) |

## Tools

Tools provide interactive operations:

| Tool | Description | Parameters |
|------|-------------|------------|
| `search_shows` | Search for TV shows by title | `query` (string, required) |
| `get_show` | Get detailed information about a show | `epguides_key` (string, required) |
| `get_episodes` | Get all episodes for a TV show | `epguides_key` (string, required) |
| `get_next_episode` | Get next unreleased episode | `epguides_key` (string, required) |
| `get_latest_episode` | Get latest released episode | `epguides_key` (string, required) |

## HTTP Endpoint

The MCP server is exposed at `/mcp` via HTTP POST:

```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "search_shows",
      "arguments": {"query": "breaking"}
    }
  }'
```

## Examples

### Initialize Connection

```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {}
  }'
```

### List Available Tools

```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

### Search Shows

```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "search_shows",
      "arguments": {"query": "breaking"}
    }
  }'
```

### Get Show Details

```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_show",
      "arguments": {"epguides_key": "BreakingBad"}
    }
  }'
```

### Get Episodes

```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_episodes",
      "arguments": {"epguides_key": "BreakingBad"}
    }
  }'
```

## Health Check

```bash
curl http://localhost:3000/mcp/health
# Returns: {"status": "healthy", "service": "mcp-server"}
```

