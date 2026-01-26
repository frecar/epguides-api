# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Epguides API is a high-performance REST API for TV show metadata, episode information, air dates, and plot summaries. It also provides an MCP (Model Context Protocol) server for AI assistant integration.

- **Framework:** FastAPI with async/await throughout
- **Caching:** Redis with TTL-based invalidation
- **Data Sources:**
  - **epguides.com** (primary): Master show list, episode CSV data
  - **TVMaze API** (fallback): Episodes, summaries, images when epguides unavailable
- **Public API:** https://epguides.frecar.no

## Commands

| Command | Purpose |
|---------|---------|
| `make up` | Start dev environment (Docker + hot reload) |
| `make down` | Stop all Docker services |
| `make test` | Run tests (100% coverage required) |
| `make fix` | Format (black) + lint (ruff) + auto-fix |
| `make cache-clear` | Flush Redis cache |
| `make up-prod` | Start production environment |

Run a single test:
```bash
pytest app/tests/test_endpoints.py::test_specific_function -v
```

## Architecture

```
app/
├── api/endpoints/       # REST routes (FastAPI routers)
│   ├── shows.py         # /shows/* endpoints
│   └── mcp.py           # /mcp endpoint (JSON-RPC for AI assistants)
├── core/
│   ├── cache.py         # Redis caching with @cached decorator
│   ├── config.py        # Pydantic settings from env vars
│   └── constants.py     # TTLs, version, external URLs
├── mcp/server.py        # MCP protocol JSON-RPC implementation
├── models/
│   ├── schemas.py       # Pydantic models (ShowSchema, EpisodeSchema)
│   └── responses.py     # Response wrappers (PaginatedResponse)
├── services/
│   ├── show_service.py  # Core business logic
│   ├── epguides.py      # External APIs: epguides.com (primary), TVMaze (fallback)
│   └── llm_service.py   # Natural language query processing
└── tests/               # pytest suite (100% coverage enforced)
```

**Layered architecture flow:** API endpoints → Services → External APIs, with Redis caching at the service layer.

## Code Patterns

### Caching with @cached decorator
```python
@cached("show:{show_id}", ttl=TTL_7_DAYS, model=ShowSchema, key_transform=normalize_show_id)
async def get_show(show_id: str) -> ShowSchema | None:
    ...
```

TTL constants in `app/core/constants.py`:
- `TTL_7_DAYS` — Ongoing shows, episodes, seasons
- `TTL_30_DAYS` — Show list, indexes
- `TTL_1_YEAR` — Finished shows (won't change)

### Schema factory functions
```python
# Always use factory function (handles defaults)
show = create_show_schema(epguides_key="test", title="Test")

# NOT direct instantiation
show = ShowSchema(...)  # Don't do this
```

### Parallel async fetches
```python
results = await asyncio.gather(
    epguides.get_episodes_data(show_id),
    epguides.get_maze_id_for_show(show_id),
)
```

## Testing

**100% test coverage is enforced** by pre-commit hooks. Commits are blocked if coverage drops below 100%.

Mock patterns:
```python
@patch("app.core.cache.cache_get", return_value=None)  # Cache miss
@patch("app.services.show_service.get_show")           # Service layer
```

Performance tests in `test_performance.py`: hard limit < 50ms, target < 20ms.

If code can't be tested, remove it — no `# pragma: no cover`.

## Pre-commit Hooks

Auto-enforced on every commit:
1. Version update (increments build number)
2. Code formatting (`make fix`)
3. Test coverage (blocks if < 100%)

Setup: `pre-commit install`

## Style

- Line length: 120 characters
- Python 3.11+
- All I/O must be async
