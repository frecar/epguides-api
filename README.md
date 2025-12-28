# Epguides API

A high-performance, asynchronous REST API and MCP server for accessing TV show metadata and episode lists from [epguides.com](http://epguides.com).

[![CI](https://github.com/yourusername/epguides-api/workflows/CI/badge.svg)](https://github.com/yourusername/epguides-api/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🚀 Features

*   **Modern Architecture**: Built with [FastAPI](https://fastapi.tiangolo.com/), fully asynchronous using `httpx` and `redis-py`.
*   **Rich Metadata**: Combines epguides' master show list with scraped metadata (Network, Runtime, Country, IMDB ID). List endpoints return simplified data; detailed metadata available on individual show endpoints.
*   **Smart Filtering**: Fast regex-based filtering with optional LLM-powered natural language queries.
*   **MCP Server**: Exposes TV show data as [Model Context Protocol](https://modelcontextprotocol.io/) server for AI assistants.
*   **Performance**: Redis connection pooling and intelligent caching for sub-150ms cached responses.
*   **Clean API**: Strict data validation with [Pydantic](https://docs.pydantic.dev/), auto-generated Swagger UI.
*   **Production Ready**: Dockerized with proper error handling, structured logging, and connection pooling.
*   **Well Tested**: Comprehensive test suite with end-to-end coverage.
*   **Type Safe**: Full type hints throughout the codebase.

## 🛠️ Tech Stack

*   **Python 3.11** (Alpine Linux)
*   **FastAPI** & **Uvicorn**
*   **Redis** (Connection-pooled caching)
*   **Httpx** (Async HTTP client)
*   **Pydantic** (Data validation)

## 🏃‍♂️ Quick Start

### Docker (Recommended)

```bash
# Clone and start all services (API, MCP server, Redis)
git clone https://github.com/yourusername/epguides-api.git
cd epguides-api
docker compose up --build -d

# Access API docs
open http://localhost:3000/docs

# Run specific services
docker compose up epguides-api redis  # API only
docker compose up epguides-mcp redis  # MCP server only
```

### Local Development

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Run API
uvicorn app.main:app --reload
```

## 📚 REST API

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/shows/` | List all shows (paginated) |
| `GET` | `/shows/search?query={query}` | Search shows by title |
| `GET` | `/shows/{epguides_key}` | Get show metadata |
| `GET` | `/shows/{epguides_key}?include=episodes` | Get show + episodes |
| `GET` | `/shows/{epguides_key}/episodes` | Get episodes (with optional filters) |
| `GET` | `/shows/{epguides_key}/episodes/next` | Get next unreleased episode (404 if show finished) |
| `GET` | `/shows/{epguides_key}/episodes/latest` | Get latest released episode |
| `GET` | `/health` | Health check |

### Examples

```bash
# Search shows
curl "http://localhost:3000/shows/search?query=breaking"

# Get show details
curl "http://localhost:3000/shows/BreakingBad"

# Get show with episodes
curl "http://localhost:3000/shows/BreakingBad?include=episodes"

# Get episodes with structured filters
curl "http://localhost:3000/shows/BreakingBad/episodes?season=2"
curl "http://localhost:3000/shows/BreakingBad/episodes?season=2&episode=5"
curl "http://localhost:3000/shows/BreakingBad/episodes?year=2008"
curl "http://localhost:3000/shows/BreakingBad/episodes?title_search=pilot"

# Legacy filter (still supported)
curl "http://localhost:3000/shows/BreakingBad/episodes?filter=s2e5"
curl "http://localhost:3000/shows/BreakingBad/episodes?q=s2e5"
```

### Filter Syntax

**Structured Query Parameters** (recommended):
- `season=2` - Filter by season number
- `episode=5` - Filter by episode number (requires season)
- `year=2008` - Filter by release year
- `title_search=pilot` - Search in episode titles

**Legacy Filter String** (backward compatible):
- `filter=season 2` or `filter=s2` - Filter by season
- `filter=s2e5` - Specific season and episode
- `filter=2008` - Filter by release year
- `filter=fly` - Search in episode titles
- `q=season 2` - Alternative parameter name for `filter` (episodes endpoint only)

**LLM-Enhanced Queries** (when `LLM_ENABLED=true`):
- Natural language queries like "episodes where Walter dies"
- Contextual filters like "first half of season 3"
- Only used as fallback when regex patterns don't match

## 🤖 MCP Server

The project includes a [Model Context Protocol](https://modelcontextprotocol.io/) server for AI assistant integration.

### Running MCP Server

**Local (for MCP clients like Claude Desktop):**
```bash
python -m app.mcp.server
# or
make mcp
```

**Docker Compose (for testing/development):**
```bash
docker compose up epguides-mcp redis
```

> **Note**: For actual MCP client usage (e.g., Claude Desktop), run the MCP server locally. Docker is mainly useful for testing and development.

### MCP Resources

- `epguides://shows` - Complete list of all TV shows

### MCP Tools

- `search_shows` - Search for TV shows by title
- `get_show` - Get detailed information about a show
- `get_episodes` - Get episodes with optional filtering
- `get_next_episode` - Get next unreleased episode (returns 404 if show has finished airing)
- `get_latest_episode` - Get latest released episode

### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "epguides-api": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/epguides-api"
    }
  }
}
```

## ⚙️ Configuration

The application loads configuration from environment variables with sensible defaults. You can optionally create a `.env` file for local development:

```bash
# Copy the example file
cp .env.example .env

# Edit .env with your settings
```

Example `.env` file:

```bash
# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=

# Cache
CACHE_TTL_SECONDS=3600

# LLM (optional)
LLM_ENABLED=true
LLM_API_URL=https://localhost/v1
LLM_API_KEY=

# Logging
LOG_LEVEL=INFO
LOG_REQUESTS=true
```

> **Note**: The `.env` file is optional. If it doesn't exist, the application will use default values. Environment variables take precedence over `.env` file values.

## 🧪 Development

```bash
# Format code
make format

# Lint
make lint

# Fix issues
make fix

# Run tests
make test

# Run MCP server
make mcp
```

## 📊 Performance

*   **Cached responses**: <150ms
*   **First request**: ~2s (includes external API calls)
*   **Connection pooling**: Redis connections reused efficiently
*   **Async I/O**: Non-blocking HTTP requests

## 🚢 Production

### Docker Deployment

```bash
docker build -t epguides-api .
docker run -d -p 3000:3000 \
  -e REDIS_HOST=your-redis \
  -e REDIS_PORT=6379 \
  epguides-api
```

### Security Checklist

- [ ] Configure CORS appropriately (`allow_origins` in `app/main.py`)
- [ ] Use Redis password authentication
- [ ] Consider rate limiting for public APIs
- [ ] Use HTTPS in production
- [ ] Monitor Redis connection pool usage

## 📝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

*   [epguides.com](http://epguides.com) for providing TV show data
*   [FastAPI](https://fastapi.tiangolo.com/) for the excellent framework
*   All contributors and users

## 📞 Support

*   **Issues**: [GitHub Issues](https://github.com/yourusername/epguides-api/issues)
*   **Discussions**: [GitHub Discussions](https://github.com/yourusername/epguides-api/discussions)
