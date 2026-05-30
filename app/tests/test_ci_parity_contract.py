"""Regression tests for the local/CI check-parity contract.

These tests pin the parity invariant so a future edit can't silently re-open
the local-vs-CI check gap:

  * `make ci-parity` exists and runs the deterministic CI subset
    (full-tree ruff format-check + lint, mypy, configured-LLM-endpoint lint).
  * A single pre-push hook invokes `make ci-parity` (one hook, no drift).

The 100%-coverage floor is enforced on every commit by the `tests-coverage`
pre-commit hook, so it does not need a separate parity assertion here. If a CI
lint/type job gains a new deterministic, locally-reproducible step, the
matching `make ci-parity` line must be added too — these tests are the guard.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = _REPO_ROOT / "Makefile"
PRE_COMMIT = _REPO_ROOT / ".pre-commit-config.yaml"


def _makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _local_hooks() -> dict[str, dict]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        if repo.get("repo") == "local":
            return {hook["id"]: hook for hook in repo["hooks"]}
    raise AssertionError("no `repo: local` block in .pre-commit-config.yaml")


def test_makefile_exposes_ci_parity_target() -> None:
    """`make ci-parity` runs the deterministic CI checks."""
    text = _makefile_text()
    assert "\nci-parity:" in text, "missing the `ci-parity` Makefile target"
    parity_line = next(line for line in text.splitlines() if line.startswith("ci-parity:"))
    # Composes the existing lint targets plus mypy.
    assert "format-check" in parity_line
    assert "lint" in parity_line
    assert "typecheck" in parity_line, "ci-parity must run mypy via typecheck"
    # And the full-tree configured-LLM-endpoint lint.
    assert "check_no_external_llm.py" in text, "ci-parity must run scripts/check_no_external_llm.py over the full tree"
    # The typecheck target itself must invoke mypy.
    assert "\ntypecheck:" in text, "missing the `typecheck` Makefile target"


def test_pre_push_runs_ci_parity_target() -> None:
    """A pre-push hook invokes `make ci-parity` — one hook, no drift."""
    hooks = _local_hooks()
    assert "ci-parity" in hooks, "missing the ci-parity pre-push hook"
    parity = hooks["ci-parity"]
    assert parity["entry"] == "make ci-parity"
    assert parity["stages"] == ["pre-push"]
    assert parity["always_run"] is True
    assert parity["pass_filenames"] is False
