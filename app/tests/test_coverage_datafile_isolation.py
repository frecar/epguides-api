"""Regression tests for the ad-hoc coverage-datafile isolation fix (epguides-api#414).

`[tool.coverage.run]` has no `data_file` override, so coverage writes to the
default `.coverage` in the worktree's CWD. Without isolation, two concurrent
`pytest --cov` invocations in the same worktree (the pre-commit
`tests-coverage` hook, `make test`, `make coverage`, or a manual scoped
`pytest --cov=app.x` check) collide on it: pytest-cov's `combine()` step globs
every `.coverage.*` file in that directory and DELETES what it merges, so a
concurrent run's in-flight data gets silently absorbed or wiped — producing a
wrong-but-plausible coverage total with zero test failures.

These tests pin two invariants:

  * The two declared entry points (`make test`, `make coverage`) and the
    pre-commit `tests-coverage` hook isolate `COVERAGE_FILE` to a fresh
    per-run temp dir.
  * `app/tests/conftest.py::_warn_if_coverage_datafile_unisolated` fires a
    loud `PytestConfigWarning` for any OTHER, undeclared invocation that
    still shares the datafile — it cannot prevent the collision (pytest-cov
    constructs its `Coverage()` object before this conftest.py is even
    loaded), only make it visible instead of silent.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from app.tests.conftest import _warn_if_coverage_datafile_unisolated

_REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = _REPO_ROOT / "Makefile"
PRE_COMMIT = _REPO_ROOT / ".pre-commit-config.yaml"


def _makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _make_target_recipe(makefile_text: str, target: str) -> str:
    """Extract a Makefile target's recipe body (the indented lines under `target:`)."""
    lines = makefile_text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("\t"):
            body.append(line)
        elif line.strip() == "":
            continue
        else:
            break
    return "\n".join(body)


def _local_hooks() -> dict[str, dict]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        if repo.get("repo") == "local":
            return {hook["id"]: hook for hook in repo["hooks"]}
    raise AssertionError("no `repo: local` block in .pre-commit-config.yaml")


def test_make_test_isolates_coverage_file_per_run() -> None:
    """`make test` must isolate COVERAGE_FILE to a fresh per-run temp dir."""
    recipe = _make_target_recipe(_makefile_text(), "test")
    assert "COVERAGE_FILE=" in recipe and "mktemp" in recipe, (
        "make test must isolate COVERAGE_FILE to a fresh temp dir so concurrent "
        "runs (e.g. the pre-commit tests-coverage hook) don't collide on the "
        "shared worktree .coverage datafile — epguides-api#414"
    )


def test_make_coverage_isolates_coverage_file_per_run() -> None:
    """`make coverage` must isolate COVERAGE_FILE too — the other declared entry point."""
    recipe = _make_target_recipe(_makefile_text(), "coverage")
    assert "COVERAGE_FILE=" in recipe and "mktemp" in recipe, (
        "make coverage must isolate COVERAGE_FILE to a fresh temp dir — epguides-api#414"
    )


def test_pre_commit_coverage_hook_isolates_coverage_file_per_run() -> None:
    """The pre-commit `tests-coverage` hook must isolate COVERAGE_FILE too.

    This hook fires on every commit, so it is the highest-frequency source of
    collision with a concurrent `make test`/`make coverage`/ad-hoc run in the
    same worktree.
    """
    hooks = _local_hooks()
    assert "tests-coverage" in hooks, "missing the tests-coverage pre-commit hook"
    entry = hooks["tests-coverage"]["entry"]
    assert "COVERAGE_FILE=" in entry and "mktemp" in entry, (
        "the tests-coverage pre-commit hook must isolate COVERAGE_FILE to a fresh temp dir — epguides-api#414"
    )
    assert "--cov=app" in entry and "--cov-fail-under=95" in entry, (
        "the isolation fix must not drop the existing coverage flags"
    )


def _fake_config(*, cov_active: bool) -> SimpleNamespace:
    """A minimal double of `pytest.Config` for the two attributes the hook reads.

    Deliberately NOT a bare `MagicMock()` for the whole config: MagicMock
    auto-vivifies any attribute access, which would defeat later assertions
    that only the expected attributes are touched.
    """
    return SimpleNamespace(
        pluginmanager=MagicMock(has_plugin=MagicMock(return_value=cov_active)),
        issue_config_time_warning=MagicMock(),
    )


def test_no_warning_when_cov_not_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """--cov never requested: pytest-cov never activated, nothing to warn about."""
    monkeypatch.delenv("COVERAGE_FILE", raising=False)
    config = _fake_config(cov_active=False)

    _warn_if_coverage_datafile_unisolated(config)

    config.issue_config_time_warning.assert_not_called()


def test_no_warning_when_coverage_file_already_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller already isolated COVERAGE_FILE (Makefile / pre-commit hook / manual) — silent."""
    monkeypatch.setenv("COVERAGE_FILE", "/tmp/some-isolated-dir/.coverage")
    config = _fake_config(cov_active=True)

    _warn_if_coverage_datafile_unisolated(config)

    config.issue_config_time_warning.assert_not_called()


def test_warns_on_unisolated_ad_hoc_cov_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """--cov active, COVERAGE_FILE unset: the exact undeclared-caller gap this fix targets."""
    monkeypatch.delenv("COVERAGE_FILE", raising=False)
    config = _fake_config(cov_active=True)

    _warn_if_coverage_datafile_unisolated(config)

    config.issue_config_time_warning.assert_called_once()
    (warning,), kwargs = config.issue_config_time_warning.call_args
    assert isinstance(warning, pytest.PytestConfigWarning)
    message = str(warning)
    assert "COVERAGE_FILE" in message
    assert "epguides-api#414" in message
    assert "make test" in message or "make coverage" in message, (
        "the warning must point at the already-isolated escape hatch, not just name the problem"
    )
    assert kwargs.get("stacklevel") == 1


def test_warning_checks_env_after_confirming_cov_active() -> None:
    """has_plugin gates the check — a non-cov run must never even read COVERAGE_FILE state.

    Guards against a future edit reordering the checks in a way that makes the
    hook noisy on every plain `pytest app/tests/` run (no --cov at all).
    """
    config = _fake_config(cov_active=False)
    _warn_if_coverage_datafile_unisolated(config)
    config.issue_config_time_warning.assert_not_called()
    config.pluginmanager.has_plugin.assert_called_with("_cov")
