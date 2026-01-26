# Epguides API

REST API for TV show metadata, episodes, air dates, and summaries. Also provides an MCP server for AI assistants.

## Tech Stack

- **Framework:** FastAPI (async)
- **Caching:** Redis with TTL-based invalidation
- **Data Sources:** epguides.com (primary), TVMaze API (fallback)
- **Python:** 3.12+
- **Public API:** https://epguides.frecar.no

## Commands

```bash
make help          # Show all commands
make up            # Start dev environment (Docker + hot reload)
make down          # Stop all services
make test          # Run tests (100% coverage required)
make fix           # Format + lint with ruff
make doctor        # Check environment health
make urls          # Show service URLs
make clean         # Remove cache files
```

Run single test:
```bash
pytest app/tests/test_endpoints.py::test_function -v
```

## Architecture

```
app/
├── api/endpoints/       # REST routes
│   ├── shows.py         # /shows/* endpoints
│   └── mcp.py           # /mcp JSON-RPC endpoint
├── core/
│   ├── cache.py         # Redis caching, @cached decorator
│   ├── config.py        # Pydantic settings
│   └── constants.py     # TTLs, version, URLs
├── models/
│   ├── schemas.py       # ShowSchema, EpisodeSchema
│   └── responses.py     # PaginatedResponse
├── services/
│   ├── show_service.py  # Business logic
│   ├── epguides.py      # External API calls
│   └── llm_service.py   # Natural language queries
└── tests/               # 100% coverage required
```

**Flow:** Endpoints -> Services -> External APIs, with Redis caching at service layer.

## Code Patterns

### Caching

```python
@cached("show:{show_id}", ttl=TTL_7_DAYS, model=ShowSchema, key_transform=normalize_show_id)
async def get_show(show_id: str) -> ShowSchema | None:
    ...
```

TTL constants (`app/core/constants.py`):
- `TTL_7_DAYS` - Ongoing shows, episodes
- `TTL_30_DAYS` - Show list, indexes
- `TTL_1_YEAR` - Finished shows

### Schema Factory

```python
# Use factory function (handles defaults)
show = create_show_schema(epguides_key="test", title="Test")

# Not direct instantiation
show = ShowSchema(...)  # Don't do this
```

### Async Parallel

```python
results = await asyncio.gather(
    epguides.get_episodes_data(show_id),
    epguides.get_maze_id_for_show(show_id),
)
```

## Testing

100% coverage enforced by pre-commit. Commits blocked if coverage drops.

Mock patterns:
```python
@patch("app.core.cache.cache_get", return_value=None)  # Cache miss
@patch("app.services.show_service.get_show")           # Service layer
```

Performance tests: < 50ms hard limit, < 20ms target.

If code can't be tested, remove it.

## Pre-commit Hooks

Runs automatically on commit:
1. Trailing whitespace, YAML check, large files, merge conflicts, private keys
2. Ruff lint + format
3. Version update
4. Tests with 100% coverage

Setup: `make setup` (installs venv + hooks)

## Style

- Line length: 120
- Python 3.12+
- All I/O async
- Ruff for linting and formatting
