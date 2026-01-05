# :material-robot: MCP Server

The Epguides API includes a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for AI assistant integration.

!!! success "Public MCP Endpoint"
    **URL:** `https://epguides.frecar.no/mcp`  
    **Protocol:** JSON-RPC 2.0 over HTTP POST

---

## :material-information: Overview

The MCP server exposes TV show data through a protocol designed for AI assistants like Claude, ChatGPT, or custom agents.

| Feature | Description |
|---------|-------------|
| :material-protocol: **Protocol** | JSON-RPC 2.0 |
| :material-web: **Transport** | HTTP POST |
| :material-database: **Data** | Same as REST API |
| :material-cached: **Caching** | Shared with REST API |

---

## :material-file-tree: Resources

Resources provide read-only access to data:

| URI | Description |
|-----|-------------|
| :material-database: `epguides://shows` | Complete list of TV shows (limited to 100) |

---

## :material-tools: Tools

Tools provide interactive operations:

| Tool | Description | Parameters |
|------|-------------|------------|
| :material-magnify: `search_shows` | Search for shows | `query` (required) |
| :material-television: `get_show` | Get show details | `epguides_key` (required) |
| :material-playlist-play: `get_episodes` | Get all episodes | `epguides_key` (required) |
| :material-skip-next: `get_next_episode` | Next unreleased episode | `epguides_key` (required) |
| :material-skip-previous: `get_latest_episode` | Latest aired episode | `epguides_key` (required) |

---

## :material-connection: HTTP Endpoint

Send JSON-RPC 2.0 requests via HTTP POST:

=== ":material-cloud: Public API"

    ```bash
    curl -X POST https://epguides.frecar.no/mcp \
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

=== ":material-laptop: Local Development"

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

---

## :material-code-json: Examples

### :material-handshake: Initialize Connection

```bash
curl -X POST https://epguides.frecar.no/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {}
  }'
```

??? success "Response"
    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "protocolVersion": "2025-06-18",
        "serverInfo": {
          "name": "epguides-mcp",
          "version": "123"
        },
        "capabilities": {
          "tools": {},
          "resources": {}
        }
      }
    }
    ```

---

### :material-format-list-bulleted: List Available Tools

```bash
curl -X POST https://epguides.frecar.no/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

---

### :material-magnify: Search Shows

```bash
curl -X POST https://epguides.frecar.no/mcp \
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

??? success "Response"
    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "content": [
          {
            "type": "text",
            "text": "{\"shows\": [{\"epguides_key\": \"BreakingBad\", ...}]}"
          }
        ]
      }
    }
    ```

---

### :material-television: Get Show Details

```bash
curl -X POST https://epguides.frecar.no/mcp \
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

---

### :material-playlist-play: Get Episodes

```bash
curl -X POST https://epguides.frecar.no/mcp \
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

---

### :material-skip-next: Get Next Episode

```bash
curl -X POST https://epguides.frecar.no/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_next_episode",
      "arguments": {"epguides_key": "Severance"}
    }
  }'
```

---

## :material-heart-pulse: Health Check

```bash
curl https://epguides.frecar.no/mcp/health
```

```json
{
  "status": "healthy",
  "service": "mcp-server"
}
```

---

## :material-head-cog: AI Assistant Integration

### :material-lightbulb: Use Cases

| Use Case | Example Query |
|----------|---------------|
| :material-help-circle: Episode Lookup | "What episode of Breaking Bad has the fly?" |
| :material-calendar-clock: Next Episode | "When does Severance season 2 continue?" |
| :material-magnify: Show Discovery | "Find shows similar to The Office" |
| :material-trophy: Season Planning | "List all Game of Thrones finales" |

### :material-code-json: Response Format

All MCP responses follow JSON-RPC 2.0:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"data\": ...}"
      }
    ]
  }
}
```

### :material-alert-circle: Error Handling

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32602,
    "message": "Invalid params",
    "data": "Missing required parameter: epguides_key"
  }
}
```

| Code | Meaning |
|------|---------|
| `-32700` | :material-close-circle: Parse error |
| `-32600` | :material-close-circle: Invalid request |
| `-32601` | :material-close-circle: Method not found |
| `-32602` | :material-close-circle: Invalid params |
| `-32603` | :material-close-circle: Internal error |
