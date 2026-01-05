# Epguides API

A REST API and MCP server for accessing TV show metadata and episode lists from [epguides.com](http://epguides.com).

**Public API**: https://epguides.frecar.no  
**REST & MCP API Documentation**: https://epguides.frecar.no/docs  

## Quick Start

### Using the Public API

Visit https://epguides.frecar.no/docs for interactive API documentation. The docs include:
- **REST API endpoints** - All show and episode endpoints
- **MCP endpoints** - JSON-RPC 2.0 interface for AI assistants (see MCP Server section below)

### Local Development

```bash
# Clone repository
gh repo clone frecar/epguides-api
cd epguides-api

# Start all services (API with MCP HTTP endpoint, Redis)
docker compose up --build

# Access local API docs
open http://localhost:3000/docs
```

To run specific services:
```bash
docker compose up epguides-api redis  # API only (includes MCP HTTP endpoint)
```

## REST API

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/shows/` | List all shows (paginated) |
| `GET` | `/shows/search?query={query}` | Search shows by title |
| `GET` | `/shows/{epguides_key}` | Get show metadata |
| `GET` | `/shows/{epguides_key}?include=episodes` | Get show + episodes |
| `GET` | `/shows/{epguides_key}/episodes` | Get episodes (with optional filters + NLQ) |
| `GET` | `/shows/{epguides_key}/episodes/next` | Get next unreleased episode (404 if show finished) |
| `GET` | `/shows/{epguides_key}/episodes/latest` | Get latest released episode |
| `GET` | `/health` | Health check |
| `GET` | `/health/llm` | LLM configuration status |
| `POST` | `/mcp` | MCP JSON-RPC endpoint (network access) |
| `GET` | `/mcp/health` | MCP server health check |

### Response Format Notes

- **`end_date` field**: The `end_date` field in list/search responses may be `null` if the show's end date is not available in the master CSV (approximately 10.8% of shows). For shows without `end_date` in the master list, you can use the individual show endpoint (`GET /shows/{epguides_key}`) which will derive it from episode data if available.

### Examples

```bash
# Search shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Get show with episodes
curl "https://epguides.frecar.no/shows/BreakingBad?include=episodes"

# Get episodes with structured filters
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2"
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2&episode=5"
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?year=2008"
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?title_search=pilot"

# Natural language queries (requires LLM - see Configuration)
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"
curl "https://epguides.frecar.no/shows/GameOfThrones/episodes?nlq=red+wedding"
curl "https://epguides.frecar.no/shows/TheOffice/episodes?nlq=jim+and+pam+moments"

# Check LLM status
curl "https://epguides.frecar.no/health/llm"
```

### Filtering Episodes

**Structured Filters** (always available):
- `season=2` - Filter by season number
- `episode=5` - Filter by episode number (requires season)
- `year=2008` - Filter by release year
- `title_search=pilot` - Search in episode titles

**Natural Language Query** (requires LLM - see Configuration):
- `nlq=your+query` - Use AI to filter episodes based on natural language

You can combine multiple filters:
```bash
# Structured filters
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2&episode=5"

# Natural language query
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"

# Combine structured filter with NLQ (structured filters apply first)
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5&nlq=most+intense"
```

## LLM-Powered Natural Language Queries

When LLM is enabled, you can use natural language to filter episodes using the `nlq` parameter.

### How It Works

1. Your query is sent to an OpenAI-compatible LLM API
2. The LLM analyzes episode titles and metadata to find matches
3. Filtered episodes are returned

### Examples

```bash
# Find finale episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"

# Find episodes with major plot events
curl "https://epguides.frecar.no/shows/GameOfThrones/episodes?nlq=episodes+where+main+characters+die"

# Find pilot/premiere episodes
curl "https://epguides.frecar.no/shows/TheOffice/episodes?nlq=pilot+or+premiere"

# Combine with structured filters (filter to season 5, then use NLQ)
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5&nlq=most+intense+episodes"
```

### Checking LLM Status

```bash
# Check if LLM is configured
curl https://epguides.frecar.no/health/llm
# Returns: {"enabled": true, "configured": true, "api_url": "https://..."}
```

### Graceful Degradation

- If LLM is **not configured** → `nlq` parameter is silently ignored, all episodes returned
- If LLM **fails** → Falls back to returning all episodes (no error)
- Structured filters (`season`, `year`, etc.) always work regardless of LLM status

## MCP Server

The project includes a [Model Context Protocol](https://modelcontextprotocol.io/) server for AI assistant integration. The MCP server exposes the same functionality as the REST API but through a protocol designed for AI assistants.

### Resources

Resources provide read-only access to data:

| URI | Description |
|-----|-------------|
| `epguides://shows` | Complete list of all TV shows (limited to first 100 for performance) |

**Example**: Access the shows resource to get a list of all available TV shows in JSON format.

### Tools

Tools provide interactive operations:

| Tool | Description | Parameters |
|------|-------------|------------|
| `search_shows` | Search for TV shows by title | `query` (string, required) - Search query |
| `get_show` | Get detailed information about a show | `epguides_key` (string, required) - Show identifier |
| `get_episodes` | Get all episodes for a TV show | `epguides_key` (string, required) - Show identifier |
| `get_next_episode` | Get next unreleased episode | `epguides_key` (string, required) - Show identifier |
| `get_latest_episode` | Get latest released episode | `epguides_key` (string, required) - Show identifier |

### Examples

**Search for shows:**
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

**Get show details:**
```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get_show",
      "arguments": {"epguides_key": "BreakingBad"}
    }
  }'
```

**Get episodes:**
```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get_episodes",
      "arguments": {"epguides_key": "BreakingBad"}
    }
  }'
```

**List available tools:**
```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/list",
    "params": {}
  }'
```

### Setup

The MCP server is exposed over HTTP at `/mcp` endpoint. This allows network-based access:

```bash
# Send MCP requests via HTTP POST
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

The HTTP endpoint is available when the FastAPI server is running (via `docker compose up` or `uvicorn app.main:app`).

## Configuration

Configuration is loaded from environment variables. Create a `.env` file for local development (see `.env.example`):

```bash
# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=

# Cache
CACHE_TTL_SECONDS=3600

# API
API_BASE_URL=http://localhost:3000/

# LLM Configuration (optional - for natural language queries)
LLM_ENABLED=true                        # Enable/disable LLM features
LLM_API_URL=https://api.openai.com/v1   # OpenAI-compatible API endpoint
LLM_API_KEY=sk-your-api-key             # API key for authentication

# Logging
LOG_LEVEL=INFO
LOG_REQUESTS=true
```

### LLM Configuration

The LLM feature requires an **OpenAI-compatible API** (OpenAI, Azure OpenAI, local LLMs via Ollama/vLLM, etc.).

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_ENABLED` | No | Set to `true` to enable natural language queries (default: `false`) |
| `LLM_API_URL` | If enabled | Base URL for OpenAI-compatible API (e.g., `https://api.openai.com/v1`) |
| `LLM_API_KEY` | If required by API | API key for authentication |

**Examples:**
```bash
# OpenAI
LLM_API_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...

# Azure OpenAI
LLM_API_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment
LLM_API_KEY=your-azure-key

# Local Ollama
LLM_API_URL=http://localhost:11434/v1
LLM_API_KEY=  # Not required for local

# Self-hosted (vLLM, text-generation-inference, etc.)
LLM_API_URL=https://your-llm-server.com/v1
LLM_API_KEY=your-key
```

Environment variables take precedence over `.env` file values.

## Development

Development commands run locally (volumes are mounted, so changes sync with Docker):

```bash
# Auto-fix code formatting and linting issues
make fix

# Run tests
make test

# Run the API server locally
make run
```

**First time setup** (if running locally):
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install pre-commit hook (optional but recommended)
pre-commit install
```

**Pre-commit Hook:**
The project includes a pre-commit hook that automatically runs `make fix` before each commit. This ensures code is properly formatted and linted. To set it up:

```bash
pre-commit install
```

To skip the hook (not recommended): `git commit --no-verify`

## Production Deployment

```bash
docker build -t epguides-api .
docker run -d -p 3000:3000 \
  -e REDIS_HOST=your-redis \
  -e REDIS_PORT=6379 \
  epguides-api
```

## Acknowledgments

*   [epguides.com](http://epguides.com) for providing TV show data
*   [FastAPI](https://fastapi.tiangolo.com/) for the excellent framework
