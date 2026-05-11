# Contributing to Epguides API

TV show metadata API + MCP server. Production at
https://epguides.frecar.no (VMID 122 on thor).

## Setup

```bash
git clone git@github.com:frecar/epguides-api.git
cd epguides-api
make setup   # venv + pre-commit hooks
```

## Daily

```bash
make up         # docker compose, hot reload
make down
make test       # 100% coverage required
make fix        # ruff format + lint auto-fix
make doctor     # env health check
make urls       # show service URLs
make clean      # remove caches
```

Single test:

```bash
pytest app/tests/test_endpoints.py::test_function -v
```

## Coverage

100% enforced by pre-commit. Commits blocked if coverage drops. If you
can't test it, remove it.

## Workflow

1. Branch off `main` (`feat/`, `fix/`, `chore/`, `docs/`).
2. Commit. Pre-commit runs ruff + version bump + 100% coverage tests.
   Never `--no-verify`.
3. Push.
4. PR. Squash merge.

## Deploy

The public instance auto-rebuilds daily. Contributors don't deploy
manually — merge a PR and the change goes live within a day.

## Where things live

- Architecture, caching pattern: CLAUDE.md
- TTL constants: `app/core/constants.py`
- Adding endpoints: `app/api/endpoints/`
