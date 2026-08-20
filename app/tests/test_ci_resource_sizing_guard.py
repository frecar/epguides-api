"""Regression tests for the CI resource-sizing guard + the repo invariant.

Two things are pinned here:

  * the guard ``scripts/check_ci_resource_sizing.py`` actually has teeth — it
    FAILS on a hardcoded ``pytest -n <N>`` / ``--maxprocesses=<N>`` / a
    literal ``cpus:``/``mem_limit:`` ceiling, and PASSES a capacity-relative
    value (``auto``, a GitHub Actions expression); and
  * this repo's own workflows stay free of a hardcoded worker/CPU/memory
    ceiling (a future edit that adds one fails this test as well as the lint
    job).

The guard is a standalone stdlib script, so it is exercised as a subprocess
(the same way pre-commit + CI run it), not imported — it is outside the
``--cov=app`` measurement scope by design.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / "scripts" / "check_ci_resource_sizing.py"


def _run(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_GUARD), "--repo-root", str(repo_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_workflow(tmp_path: Path, name: str, content: str) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(content)


# --- the repo invariant -----------------------------------------------------


def test_repo_workflows_pass_the_guard() -> None:
    result = _run(_REPO_ROOT)
    assert result.returncode == 0, (
        f"no workflow step may hardcode a topology-specific worker/CPU/memory ceiling; guard said:\n{result.stderr}"
    )


def test_ci_test_job_uses_capacity_relative_xdist() -> None:
    config = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    test_job = config["jobs"]["test"]
    test_commands = [step["run"] for step in test_job["steps"] if "run" in step]

    assert test_job["runs-on"] == "ubuntu-latest"
    assert any("pytest -n auto --dist=worksteal" in command for command in test_commands), (
        "the public CI test job must use the tested capacity-relative xdist selector"
    )


def test_guard_self_test_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(_GUARD), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "self-test passed" in result.stdout


# --- the guard has teeth ----------------------------------------------------


def test_guard_flags_hardcoded_xdist_worker_count(tmp_path: Path) -> None:
    _write_workflow(tmp_path, "ci.yml", "jobs:\n  test:\n    steps:\n      - run: uv run pytest -n 16 --cov=app\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "ci.yml:4" in result.stderr


def test_guard_flags_maxprocesses(tmp_path: Path) -> None:
    _write_workflow(tmp_path, "ci.yml", "jobs:\n  test:\n    steps:\n      - run: uv run pytest --maxprocesses=16\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "--maxprocesses" in result.stderr


def test_guard_flags_hardcoded_xdist_env_var(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        'jobs:\n  test:\n    steps:\n      - run: echo "PYTEST_XDIST_AUTO_NUM_WORKERS=8" >> "$GITHUB_ENV"\n',
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS" in result.stderr


def test_guard_flags_hardcoded_docker_resource_ceiling(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  test:\n    services:\n      redis:\n        options: >-\n          --memory=2g\n",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "--memory" in result.stderr


def test_guard_passes_capacity_relative_worker_count(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  test:\n    steps:\n      - run: uv run pytest -n auto --cov=app\n",
    )
    assert _run(tmp_path).returncode == 0


def test_guard_passes_gha_expression_worker_count(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  test:\n    steps:\n      - run: uv run pytest -n ${{ steps.cap.outputs.workers }}\n",
    )
    assert _run(tmp_path).returncode == 0


def test_guard_ignores_unrelated_numeric_settings(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  test:\n    timeout-minutes: 20\n    steps:\n      - run: uv run pytest --cov-fail-under=95\n",
    )
    assert _run(tmp_path).returncode == 0


def test_guard_ignores_commented_out_hardcoded_flag(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  test:\n    steps:\n      # - run: uv run pytest -n 16\n      - run: uv run pytest -n auto\n",
    )
    assert _run(tmp_path).returncode == 0


def test_guard_fails_closed_on_no_workflows(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "no .github/workflows" in result.stderr


# --- three-surface wiring parity (no-drift, mirrors the ci-parity contract) --


def test_guard_wired_into_all_enforcement_surfaces() -> None:
    script = "scripts/check_ci_resource_sizing.py"

    makefile = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert script in makefile, "make ci-parity must run the CI resource-sizing guard"

    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert script in ci, "the lint job must run the CI resource-sizing guard so it gates"

    config = yaml.safe_load((_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    # Every `repo: local` block, not just the first — this config carries
    # several, so `next(...)` inspected only the earliest.
    local = {"hooks": [h for r in config["repos"] if r.get("repo") == "local" for h in r["hooks"]]}
    entries = [h["entry"] for h in local["hooks"]]
    assert any(script in e for e in entries), "a pre-commit hook must run the CI resource-sizing guard"
