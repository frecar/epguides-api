"""
Pytest fixtures for test suite.

Provides async HTTP client for endpoint testing.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scripts.compute_xdist_workers import current_selection, redis_db_for_worker

# Each xdist worker gets its own Redis database. The suite deliberately uses
# fixed cache keys to exercise production caching behavior, so sharing DB 0
# makes otherwise-independent tests overwrite one another when they run in
# parallel. The capacity selector caps the normal path at eight workers, safely
# within Redis's default 16 logical databases.
_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
_XDIST_REDIS_DB = redis_db_for_worker(_XDIST_WORKER)
if _XDIST_REDIS_DB is not None:
    os.environ["REDIS_DB"] = str(_XDIST_REDIS_DB)

from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def async_client():
    """Async HTTP client for testing endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """Make ``pytest -n auto`` capacity-relative and fail-closed."""
    del config
    selection = current_selection()
    print(
        "epguides xdist capacity: "
        f"workers={selection.workers} visible_cpus={selection.visible_cpus or 'unknown'} "
        f"cpu_budget={selection.cpu_budget} memory_budget={selection.memory_budget} "
        f"reason={selection.reason}",
        flush=True,
    )
    return selection.workers


def pytest_configure(config: pytest.Config) -> None:
    """Warn loudly when a `--cov` run shares the unisolated worktree datafile.

    See `_warn_if_coverage_datafile_unisolated` docstring (epguides-api#414).
    """
    _warn_if_coverage_datafile_unisolated(config)


def _warn_if_coverage_datafile_unisolated(config: pytest.Config) -> None:
    """Loud warning for an ad-hoc ``pytest --cov`` run sharing the datafile.

    ``[tool.coverage.run]`` has no ``data_file`` override, so coverage writes
    to the default ``.coverage`` in this worktree's CWD. `make test` /
    `make coverage` and the pre-commit `tests-coverage` hook all isolate
    ``COVERAGE_FILE`` to a fresh per-run temp dir (epguides-api#414); a bare
    ``uv run pytest --cov=app`` (or any scoped ad-hoc check) does not.

    This can only WARN, not prevent: pytest-cov constructs its ``Coverage()``
    object inside its own ``pytest_load_initial_conftests`` hookimpl (marked
    ``tryfirst=True``), which runs BEFORE this conftest.py is even loaded —
    that hook is what loads conftest.py. There is no hook early enough here to
    redirect the data file — this is a pytest-cov plugin-timing constraint,
    not something specific to this repo's setup. A collision is silent
    otherwise: pytest-cov's
    ``combine()`` step globs every ``.coverage.*`` file in the shared
    directory and DELETES what it merges, so a concurrent run's total reads
    wrong-but-plausible with ZERO test failures. ``config.issue_config_time_warning``
    (not a bare ``print``) so the message survives pytest's default output
    capture and always lands in the warnings summary, pass or fail.
    """
    if not config.pluginmanager.has_plugin("_cov"):
        return  # --cov not requested; pytest-cov never activated
    if os.environ.get("COVERAGE_FILE"):
        return  # already isolated (Makefile / pre-commit hook, or a caller who set it)

    config.issue_config_time_warning(
        pytest.PytestConfigWarning(
            "coverage is active but COVERAGE_FILE is unset (epguides-api#414) — "
            "this run shares the worktree-local .coverage data_file with any "
            "concurrent `pytest --cov` run in this worktree (the pre-commit "
            "tests-coverage hook included). A collision reports a "
            "wrong-but-plausible total with ZERO test failures, not a visible "
            "error. Use `make test` / `make coverage` (already isolated) or, "
            'for a scoped check: COVERAGE_FILE="$(mktemp -d)/.coverage" uv run '
            "pytest <args> --cov=app"
        ),
        stacklevel=1,
    )
