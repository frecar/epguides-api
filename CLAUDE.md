# Epguides API

REST API for TV show metadata, episodes, air dates, and summaries. Also provides an MCP server for AI assistants.

## Git Workflow (Standard)
- **Commit Messages:** Use descriptive prefixes (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`).
- **Branching:** Work primarily on `main`. Always pull latest before starting.
- **Pre-commit:** Ensure pre-commit hooks pass before pushing.

## LLM Policy
- Natural-language queries are routed through whatever OpenAI-compatible gateway is set in `LLM_API_URL` (local Ollama, vLLM, llama.cpp server, hosted endpoint, ...).
- Do not add Claude/OpenAI/Anthropic external API endpoints or runtime fallbacks to committed code paths. `scripts/check_no_external_llm.py` enforces this in pre-commit and CI.
- Optional `ALLOWED_LLM_HOSTS` env var (comma-separated hostnames) gates which hosts the gateway URL may resolve to. Empty/unset (default) means no host enforcement — any configured URL is accepted.

## Deployment

All changes flow through git. Deployment automation is operator-side and
not part of this project's published surface — contributors merge a PR
and the public instance picks up the change on the next rebuild (daily).

For local runs see "Quick Start" below.

## Tech Stack

- **Framework:** FastAPI (async)
- **Caching:** Redis with TTL-based invalidation
- **Data Sources:** epguides.com (primary), TVMaze API (fallback)
- **Python:** 3.14+
- **Public API:** https://epguides.frecar.no

## Quality baseline

This repo defines and adheres to a Python-service quality baseline:

- **Dependency manager:** `uv` with `uv.lock` committed. Docker builds use `uv sync --frozen --no-dev` so any lockfile drift fails the build instead of silently re-resolving.
- **Lint + format:** `ruff` (target `py313` — `py314` strips parens around `except (A, B):` clauses, which the formatter shouldn't do).
- **Type-check:** `mypy` with `check_untyped_defs` + `warn_unused_ignores` + `strict_optional` floor; strict mode opt-in per module.
- **Tests:** `pytest` + `pytest-cov`. **100% coverage enforced** at the pre-commit + CI gate (`fail_under = 100.0` in `pyproject.toml`). Commits below the floor are rejected.
- **Security:** OSV-Scanner runs on `uv.lock` in CI. Unfixable transitive CVEs land in `.osv-scanner.toml` with a fix-by date and a tracking issue — never silenced silently.
- **Public surface:** `scripts/check-no-internal-refs.sh` runs in pre-commit and CI. Keep source, docs, and examples standalone; use runtime configuration for private deployment values.
- **Error tracking:** `sentry-sdk[fastapi]` initialised in `app/main.py` only when `SENTRY_DSN` env var is set (prod-only by convention; dev/test stays no-op).
- **Observability:** `/metrics` endpoint exposes Prometheus exposition format (cache hits/misses by type, upstream request totals by source/outcome, upstream latency histogram). `/health`, `/health/llm`, `/health/cache` return structured JSON.
- **Docker hardening:** multi-stage build (compile in builder, ship runtime only), non-root user (UID 1000), `no-new-privileges`, healthcheck, log rotation, pinned `python:3.14-slim` base, pinned `ghcr.io/astral-sh/uv:0.11.3` for the uv binary.
- **Backup tier:** **N/A.** All persistent state is in upstream APIs (epguides.com, TVMaze); cache is Redis-resident and ephemeral. No DB to back up. Documented as a baseline-contract row even when the answer is "nothing to do here."
- **Makefile contract:** `make help / dev / stop / lint / fix / test / ci / build` — same surface as other Python services I maintain (aliases `up`/`down`/`deploy-prod` retained for existing muscle memory).
- **Deploy:** auto-update timer rebuilds the container daily.

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

## REST ↔ MCP coverage matrix

Both surfaces share the same service layer; only the wire format differs.
Last verified 2026-05-10 (#197).

| Capability | REST (`/shows/*`) | MCP tool | Status |
|---|---|---|---|
| Search shows | `GET /search?q=` | `search_shows` | ✅ parity |
| Get show metadata | `GET /{key}` | `get_show` | ✅ parity |
| List seasons | `GET /{key}/seasons` | `get_seasons` | ✅ parity |
| Get episodes (with filters) | `GET /{key}/episodes` (season, episode, year, title_search, nlq, refresh) | `get_episodes` (season, episode, year, title_search, nlq) | ✅ parity (refresh deliberately omitted — MCP clients shouldn't need cache busting) |
| Next unreleased episode | `GET /{key}/episodes/next` | `get_next_episode` | ✅ parity |
| Latest released episode | `GET /{key}/episodes/latest` | `get_latest_episode` | ✅ parity |
| List ALL shows | `GET /` | `epguides://shows` resource | 🟨 different surface (resource, not tool — MCP clients should browse this rather than dump-then-filter) |
| Season-specific episode listing | `GET /{key}/seasons/{n}/episodes` | use `get_episodes` with `season=n` | ✅ folded into `get_episodes` |

### MCP-side conventions

- Tools always return JSON text content via `content: [{type: "text", text: ...}]` per the MCP spec; clients deserialize.
- `nlq` falls back to all matching episodes when the LLM is unavailable, matching REST behavior.
- Tool input schemas live in `app/mcp/server.py` `_TOOLS`. CI parity test: every REST endpoint adds a comment naming the corresponding MCP tool (or a deliberate-difference rationale).

## Code Patterns

### Caching

```python
@cached("show:{show_id}", ttl=TTL_7_DAYS, model=ShowSchema, key_transform=normalize_show_id)
async def get_show(show_id: str) -> ShowSchema | None:
    ...
```

TTL constants (`app/core/cache.py`):
- `TTL_7_DAYS` - Ongoing shows, seasons, episodes
- `TTL_30_DAYS` - Show list, indexes
- `TTL_1_YEAR` - Finished shows (`show.end_date is not None`) — promoted automatically by `_get_show_ttl()` / `_get_episodes_ttl()`

### Data freshness SLA (#196)

What clients can assume about how recent the data is.

| Resource | Worst case | Why |
|---|---|---|
| Show metadata (ongoing series) | 7 days | `TTL_7_DAYS` cache + `?refresh=true` invalidation supported |
| Show metadata (finished series) | 1 year | `_get_show_ttl()` extends to `TTL_1_YEAR` once `end_date` is set — these don't change |
| Episode list (ongoing) | 7 days | `TTL_7_DAYS`. Smart-invalidation on `GET /{key}/episodes/next` if the cached "next" date has passed (see `shows.py:405`) — bounds staleness for the most-asked-about episode to ≤24h after release |
| Episode list (finished) | 1 year | promoted automatically via `_get_episodes_ttl()` when all episodes are released |
| Show list (master index) | 30 days | rebuilt on demand via `extend_cache_ttl` |
| Search results | 7 days | derived from the show list |

### Upstream sources (epguides.com primary, TVMaze fallback)

- Primary: `https://epguides.com/` master list + per-show CSVs.
- Fallback: TVMaze API (used for episode data when epguides parse fails).

The cache hides upstream outages — once warmed, the API serves stale-but-bounded data even if both upstreams are down. Expected downsides:

- A scrape regression (e.g. epguides.com changes their HTML) won't surface as user-visible failures until the cache expires for a given show. Catch this with active probes (#196 fix items 2-4).
- New episodes for an ongoing series take up to `TTL_7_DAYS` to appear unless a client passes `?refresh=true` or hits `/episodes/next` past the prior cached "next" date.

### Observability gaps (open work — #196 follow-ups)

- No metric for cache hit/miss ratio per type. Add `epguides_cache_hits_total{type}` / `epguides_cache_misses_total{type}` in the `@cached` decorator.
- No alert if upstream stops responding. Add `epguides_upstream_request_total{source,outcome}` + Grafana `EpguidesUpstreamStale` alert (no successful epguides.com fetch in 24h).
- No measurement of upstream latency. Add `epguides_upstream_response_age_seconds{source}` histogram.

These are kept intentionally separate from the SLA section above so the docs reflect today's truth — the gaps don't lie about coverage that doesn't exist yet.

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

Setup: `make setup` (runs `uv sync` to create `.venv` from `uv.lock`, then installs pre-commit hooks). Requires `uv` — install via https://docs.astral.sh/uv/.

## Style

- Line length: 120
- Python 3.12+
- All I/O async
- Ruff for linting and formatting
