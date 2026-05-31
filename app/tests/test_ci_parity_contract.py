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
CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = _REPO_ROOT / "pyproject.toml"

# The exact host-3.12 compile guard string that must appear, byte-for-byte, in
# every enforcement surface (CI step, pre-commit hook, make ci-parity).
_HOST_PY312_COMPILE = "uv run --python 3.12 --no-project python -m py_compile"


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


def test_ruff_carves_back_scripts_to_py312() -> None:
    """scripts/ runs on the system python3 (possibly older than 3.14), so ruff
    must NOT emit 3.14-only syntax (e.g. PEP 758 `except A, B:`) there. Pinned
    via per-file-target-version so the project stays py314 everywhere else."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "[tool.ruff.per-file-target-version]" in text, "missing the host-3.12 ruff carve-back"
    assert '"scripts/*.py" = "py312"' in text, "scripts/*.py must be pinned to py312"


def test_host_py312_compile_guard_in_all_surfaces() -> None:
    """The real-CPython-3.12 compile guard over scripts/ must exist in CI,
    pre-commit, AND make ci-parity, byte-for-byte identical, so a `ruff format`
    that introduces 3.14-only syntax can't reach the host interpreter
    undetected. These three are the no-drift contract."""
    # make ci-parity
    assert _HOST_PY312_COMPILE in _makefile_text(), "ci-parity must compile scripts/ under host 3.12"

    # pre-commit hook (changed-file, files-scoped to scripts/)
    hooks = _local_hooks()
    assert "host-python312-syntax" in hooks, "missing the host-python312-syntax pre-commit hook"
    guard = hooks["host-python312-syntax"]
    assert guard["entry"] == _HOST_PY312_COMPILE
    assert guard["language"] == "system"
    assert guard["files"] == r"^scripts/.*\.py$"
    assert guard["stages"] == ["pre-commit"]

    # CI step
    assert _HOST_PY312_COMPILE in CI_WORKFLOW.read_text(encoding="utf-8"), (
        "the Host-interpreter syntax guard CI step must compile scripts/ under host 3.12"
    )
