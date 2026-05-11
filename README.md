# Epguides API

REST API for TV show data, episode lists, air dates, and plot summaries. Includes an MCP server for AI assistant integration.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-green.svg)](https://fastapi.tiangolo.com/)
[![Documentation](https://img.shields.io/badge/docs-ReadTheDocs-blue.svg)](https://epguides-api.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Links

| Resource | URL |
|----------|-----|
| Public API | https://epguides.frecar.no |
| Swagger UI | https://epguides.frecar.no/docs |
| Documentation | https://epguides-api.readthedocs.io |
| MCP Endpoint | https://epguides.frecar.no/mcp |

## Features

- TV show database with metadata for thousands of series
- Search shows by title
- Browse seasons and episodes
- Plot summaries via TVMaze
- Show posters, season posters, episode stills
- Next/latest episode tracking
- Natural language search (LLM-powered)
- MCP server for AI assistants

## Quick Start

No API key needed:

```bash
# Search for shows
curl "https://epguides.frecar.no/shows/search?query=breaking+bad"

# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# List seasons
curl "https://epguides.frecar.no/shows/BreakingBad/seasons"

# Get episodes for a season
curl "https://epguides.frecar.no/shows/BreakingBad/seasons/1/episodes"

# Get all episodes with filtering
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"

# Get next episode
curl "https://epguides.frecar.no/shows/Severance/episodes/next"
```

## MCP (for AI assistants)

The API exposes a Model Context Protocol server at `/mcp` so AI assistants can query TV show data directly. Transport is JSON-RPC 2.0 over HTTP POST — any MCP client that speaks HTTP transports works.

### Available tools

| Tool | What it does |
|---|---|
| `search_shows` | Search shows by title |
| `get_show` | Get show metadata by epguides key (e.g. `BreakingBad`) |
| `get_seasons` | List seasons with posters + summaries |
| `get_episodes` | Episodes with filters (`season`, `episode`, `year`, `title_search`, natural-language `nlq`) |
| `get_next_episode` | Next unreleased episode for a show |
| `get_latest_episode` | Most recently released episode |

Plus a resource at `epguides://shows` that returns the complete show list.

### Quick test

The endpoint accepts standard JSON-RPC 2.0 — useful for sanity checks before wiring it up:

```bash
# List available tools
curl -s -X POST https://epguides.frecar.no/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Call search_shows
curl -s -X POST https://epguides.frecar.no/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":2,
    "method":"tools/call",
    "params":{"name":"search_shows","arguments":{"query":"breaking bad"}}
  }'
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "epguides": {
      "url": "https://epguides.frecar.no/mcp"
    }
  }
}
```

Restart Claude Desktop. Tools appear under the 🔌 menu — ask "what's the next Severance episode?" and the assistant will call `get_next_episode` for you.

### Other clients

Any client that speaks MCP over HTTP works. Point it at `https://epguides.frecar.no/mcp` and call `tools/list` to discover what's available. No auth required.

## Documentation

Full docs at [epguides-api.readthedocs.io](https://epguides-api.readthedocs.io):

- [Getting Started](https://epguides-api.readthedocs.io/en/latest/getting-started/)
- [REST API Reference](https://epguides-api.readthedocs.io/en/latest/rest-api/)
- [MCP Server](https://epguides-api.readthedocs.io/en/latest/mcp-server/)
- [Configuration](https://epguides-api.readthedocs.io/en/latest/configuration/)
- [Development](https://epguides-api.readthedocs.io/en/latest/development/)

## Self-Hosting

### Development

```bash
git clone https://github.com/frecar/epguides-api.git
cd epguides-api
make setup
make up

# API at http://localhost:3000 (with hot reload)
```

### Production

```bash
make up-prod

# 12 workers, uvloop, 5GB Redis cache
```

See [Development Guide](https://epguides-api.readthedocs.io/en/latest/development/) for details.

## Contributing

```bash
git clone git@github.com:frecar/epguides-api.git
cd epguides-api
make setup   # creates the uv-managed venv + installs pre-commit hooks
make up      # docker compose, hot reload
make test    # 100% coverage required
make fix     # ruff format + lint auto-fix
make doctor  # env health check
make urls    # show service URLs
```

Run a single test:

```bash
make test  # runs everything; pre-commit gate also enforces 100%
uv run pytest app/tests/test_endpoints.py::test_function -v  # one specific test
```

**Coverage:** 100% enforced by pre-commit. If you can't test it, remove it. Never `--no-verify`.

**Workflow:**
1. Branch off `main` with a conventional prefix (`feat/`, `fix/`, `chore/`, `docs/`)
2. Commit. Pre-commit runs ruff + version bump + 100% coverage tests
3. Push and open a PR
4. Squash merge

**Deploy:** the public instance auto-rebuilds daily. Contributors don't deploy manually — merge a PR and the change goes live within a day.

Architecture, caching patterns, and gotchas live in [CLAUDE.md](./CLAUDE.md) — read that before deeper changes.

## Data Sources

| Source | Data |
|--------|------|
| [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates |
| [TVMaze](https://api.tvmaze.com) | Summaries, posters, episode stills |
| [IMDB](https://imdb.com) | IMDB IDs |

## License

MIT
