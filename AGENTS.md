# epguides-api — Agent Guidance

<!-- AGENTS-CORE:BEGIN — generated from frecar/dotfiles code/AGENTS-CORE-public.md. Do NOT edit inline; run code/sync-agents-core.sh. -->
## Cross-agent core rules

These rules bind **every** agent working in this repo — Claude, Codex, Gemini, OpenCode — regardless of tool. They are the shared contract; your tool-specific file (`CLAUDE.md` / `GEMINI.md` / your config) adds only tool mechanics on top. This block is machine-synced — do not edit it inline.

### Worktrees
- Create worktrees **only** under `/tmp/wt-<branch-slug>/<repo>` (branch with `/`→`-`). **Never** nest a worktree inside the main clone directory — that pollutes the workspace.
- Base off fresh `origin/main`: `git fetch origin` immediately before `git worktree add "/tmp/wt-<slug>/<repo>" origin/main -b <branch>`.
- Name the worktree by the branch, not the issue. **Tear it down** on completion or hand-off: `git worktree remove <path>` + `rm -rf` the parent.

### Multi-agent coordination (several agents run concurrently as the same GitHub user)
- Before starting an issue, sweep for an existing branch touching it (`git ls-remote --heads origin "*<issue>*"`). If one exists, another agent has it — back off.
- Claim atomically: assign yourself, flip `status:ready`→`status:in-progress`, push an agent-name-prefixed branch, and post a claim comment. Then **wait ~60s and re-read** — if another agent's claim landed in the gap, back off and undo yours.
- One issue per agent. Never edit, review, or push to another agent's claimed issue / PR / branch. Stamp your agent identity on branches and comments so ownership is visible.

### Merge discipline
- `main` is protected on every repo: **never** `git push` to it, **never** raw `gh pr merge` or web-merge.
- Merge **only** via the project's gated merge wrapper, which refuses unless every required check has concluded `success`.
- **Never merge red.** A failing/missing required check or a change-requesting review is a signal to FIX, not to merge. Branch off latest `origin/main` → worktree-isolate → wait for CI green → merge via the gate.

### Commits & conventions
- **Never** add `Co-Authored-By` or any AI-attribution line — commits are the operator's own work.
- **Never** fix production by ad-hoc SSH. Fix in the repo, commit, deploy. Ad-hoc SSH creates drift that the next deploy overwrites.
- Docker-first — run tooling in containers, not on the host. Keep secrets in environment variables or a secrets manager, never committed to the repo.
- Do not hard-code external LLM API endpoints (OpenAI, Anthropic, etc.) in source. Route model calls through the endpoint configured via environment variable.

### GitHub issues
- Any non-trivial plan or task becomes a GH issue, before or as you start — the issue is the durable record. Apply **exactly one each** of `type:` (bug/feature/chore/docs/infra), `severity:` (critical/high/medium/low), `status:` (triage/ready/in-progress/blocked/burn-in) at file time.
- Self-filed issue → `Closes #N` in the PR. **External-reporter** issue → `Refs #N` (never auto-close on merge; the reporter verifies first).
- This is a public repo — never reference internal hostnames, IPs, private repos, or private deployment details in issues/PRs/comments.

### Quality gates
- Pre-commit and pre-push run automatically; **never** `--no-verify`. Fix the failure instead.
- Wait for CI green before merging. The coverage floor is a fixed **95%** — never lower a gate to pass.

> Detail and rationale live in this repo's own `AGENTS.md` below. This CORE is the non-negotiable shared minimum.
<!-- AGENTS-CORE:END -->


Canonical agent instructions for this repository. Compatibility files (`CLAUDE.md`, `.github/copilot-instructions.md`) point here.

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
- **Lint + format:** `ruff` (target `py314`, matching the committed `.python-version` and `requires-python = ">=3.14"`).
- **Type-check:** `mypy` with `check_untyped_defs` + `warn_unused_ignores` + `strict_optional` floor; strict mode opt-in per module.
- **Tests:** `pytest` + `pytest-cov`. **95% coverage floor** at the pre-commit + CI gate (`fail_under = 95` in `pyproject.toml`). Commits below the floor are rejected.
- **API contract gate:** `app/tests/test_api_contract.py` (driven by the `app/contract.py` engine) is a per-PR regression gate over the *published OpenAPI contract*. It boots the app in-process (FastAPI `TestClient`, no network) and asserts every anonymous, no-required-param GET route (`/shows/`, `/health`, `/health/ready`, `/health/llm`, `/health/cache`) still returns `200` with a body that validates against its **declared** OpenAPI `200` response schema. A route that starts `500`ing, serves a non-JSON error stub, drifts its response shape, or disappears from the schema (the `MUST_COVER` floor in `app/contract.py`) fails the test — and so the PR — before merge. The contract definition (anonymous-GET eligibility filter + `MUST_COVER` floor + declared-200-schema validation) is the single source of truth: the same engine shape can be pointed at the deployed `/openapi.json` for an out-of-band post-deploy probe, so the pre-merge gate and any deployed check cannot disagree on "the contract". Add a new public anonymous GET route → add it to `MUST_COVER`.
- **Security:** CVE coverage is layered in CI — `pip-audit --strict --require-hashes` against the exported (hashed) transitive dependency set, plus a Trivy filesystem scan (reads `uv.lock`) and a Trivy image scan of the built runtime. CRITICAL findings gate the merge; HIGH surface as annotations. Unfixable findings with no upstream patch are suppressed via `.trivyignore` / `ignore-unfixed` with a tracking trail — never silenced silently.
- **Public surface:** `scripts/check-no-internal-refs.sh` runs in pre-commit and CI. Keep source, docs, and examples standalone; use runtime configuration for private deployment values.
- **Error tracking:** `app.core.observability` initialises `sentry-sdk[fastapi]` only when `SENTRY_DSN` env var is set; traces and profiles default to `0.0` unless configured.
- **Observability:** `/metrics` endpoint exposes Prometheus exposition format (cache hits/misses by type, upstream request totals by source/outcome, upstream latency histogram, per-source ingest-freshness heartbeat). `/health` (cheap liveness), `/health/ready` (deep readiness — Redis round-trip + upstream freshness, structured `status` field, `503` when data is silently stale), `/health/llm`, `/health/cache` return structured JSON.
- **Docker hardening:** multi-stage build (compile in builder, ship runtime only), non-root user (UID 1000), `no-new-privileges`, healthcheck, log rotation, pinned `python:3.14-slim` base, pinned `ghcr.io/astral-sh/uv:0.11.3` for the uv binary.
- **Backup tier:** **N/A.** All persistent state is in upstream APIs (epguides.com, TVMaze); cache is Redis-resident and ephemeral. No DB to back up. Documented as a baseline-contract row even when the answer is "nothing to do here."
- **Makefile contract:** `make help / dev / stop / lint / fix / test / ci / build` — same surface as other Python services I maintain (aliases `up`/`down`/`deploy-prod` retained for existing muscle memory).
- **Deploy:** auto-update timer rebuilds the container daily.

## Commands

```bash
make help          # Show all commands
make up            # Start dev environment (Docker + hot reload)
make down          # Stop all services
make test          # Run tests (95% coverage floor)
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
└── tests/               # 95% coverage floor
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
- Upstream-staleness signal: `epguides_upstream_request_total{source,outcome}` + `epguides_ingest_last_success_timestamp{source}` heartbeat are exported, and `/health/ready` now flips to a `503` when no successful epguides.com fetch has landed within `UPSTREAM_STALENESS_HOURS` (default 24h). Remaining open work is operator-side monitoring config (the external Grafana/probe alert wiring), out of this repo's scope.
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

95% coverage floor enforced by pre-commit. Commits below the floor are rejected.

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
4. Tests with 95% coverage floor

Setup: `make setup` (runs `uv sync` to create `.venv` from `uv.lock`, then installs pre-commit hooks). Requires `uv` — install via https://docs.astral.sh/uv/.

## Style

- Line length: 120
- Python 3.14 (pinned via committed `.python-version`; `requires-python = ">=3.14"`)
- All I/O async
- Ruff for linting and formatting
