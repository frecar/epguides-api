# 🤖 MCP Server

The Epguides API includes a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for AI assistant integration.

!!! success "Public MCP Endpoint"
    **URL:** `https://epguides.frecar.no/mcp`  
    **Protocol:** JSON-RPC 2.0 over HTTP POST

---

## Overview

The MCP server exposes TV show data through a protocol designed for AI assistants like Claude, ChatGPT, or custom agents.

| Feature | Description |
|---------|-------------|
| **Protocol** | JSON-RPC 2.0 |
| **Transport** | HTTP POST |
| **Data** | Same as REST API |
| **Caching** | Shared with REST API |

---

## Resources

Resources provide read-only access to data:

| URI | Description |
|-----|-------------|
| `epguides://shows` | Complete list of TV shows (limited to 100) |

---

## Tools

Tools provide interactive operations:

| Tool | Description | Parameters |
|------|-------------|------------|
| `search_shows` | Search for shows | `query` (required) |
| `get_show` | Get show details | `epguides_key` (required) |
| `get_episodes` | Get all episodes | `epguides_key` (required) |
| `get_next_episode` | Next unreleased episode | `epguides_key` (required) |
| `get_latest_episode` | Latest aired episode | `epguides_key` (required) |

---

## HTTP Endpoint

Send JSON-RPC 2.0 requests via HTTP POST:

=== "Public API"

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

=== "Local"

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

## Examples

### Initialize Connection

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

### List Tools

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

### Search Shows

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

### Get Show Details

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

### Get Episodes

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

### Get Next Episode

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

## 💚 Health Check

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

## AI Assistant Integration

### Use Cases

| Use Case | Example Query |
|----------|---------------|
| Episode Lookup | "What episode of Breaking Bad has the fly?" |
| Next Episode | "When does Severance season 2 continue?" |
| Show Discovery | "Find shows similar to The Office" |
| Season Planning | "List all Game of Thrones finales" |

### Response Format

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

### Error Handling

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
| `-32700` | Parse error |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |
