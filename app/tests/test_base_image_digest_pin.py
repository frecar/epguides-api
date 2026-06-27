"""Regression tests for the base-image digest-pin guard + the repo invariant.

Two things are pinned here:

  * the guard ``scripts/check_base_image_digest_pin_drift.py`` actually has
    teeth — it FAILS on a tag-only ``FROM`` and a tag-only ``COPY --from``
    external image, and SKIPS internal stage references / ``scratch``; and
  * this repo's own Dockerfile stays digest-pinned (a future edit that drops a
    ``@sha256:`` fails this test as well as the lint job).

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
_GUARD = _REPO_ROOT / "scripts" / "check_base_image_digest_pin_drift.py"

_PINNED_PY = "python:3.14.6-slim@sha256:63a4c7f612a00f92042cbdcc7cdc6a306f38485af0a200b9c89de7d9b1607d15"


def _run(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_GUARD), "--repo-root", str(repo_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(tmp_path: Path, content: str) -> None:
    (tmp_path / "Dockerfile").write_text(content)


# --- the repo invariant -----------------------------------------------------


def test_repo_dockerfile_is_digest_pinned() -> None:
    result = _run(_REPO_ROOT)
    assert result.returncode == 0, (
        f"the repo Dockerfile must keep every FROM + external COPY --from digest-pinned; guard said:\n{result.stderr}"
    )


# --- the guard has teeth ----------------------------------------------------


def test_guard_flags_tag_only_from(tmp_path: Path) -> None:
    _write(tmp_path, "FROM python:3.14.6-slim AS builder\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "Dockerfile:1" in result.stderr


def test_guard_flags_tag_only_copy_from(tmp_path: Path) -> None:
    _write(
        tmp_path,
        f"FROM {_PINNED_PY} AS builder\nCOPY --from=ghcr.io/example/tool:1.0 /x /x\n",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "Dockerfile:2" in result.stderr


def test_guard_passes_fully_pinned_including_copy_from(tmp_path: Path) -> None:
    pinned_tool = "ghcr.io/example/tool:1.0@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write(
        tmp_path,
        f"FROM {_PINNED_PY} AS builder\n"
        f"COPY --from={pinned_tool} /x /x\n"
        f"FROM {_PINNED_PY} AS runtime\n"
        "COPY --from=builder /app /app\n",
    )
    assert _run(tmp_path).returncode == 0


def test_guard_skips_internal_refs_and_scratch(tmp_path: Path) -> None:
    _write(
        tmp_path,
        f"FROM {_PINNED_PY} AS builder\nFROM scratch\nCOPY --from=builder /a /a\nCOPY --from=0 /b /b\n",
    )
    assert _run(tmp_path).returncode == 0


def test_guard_fails_closed_on_no_dockerfile(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "no Dockerfile" in result.stderr


# --- three-surface wiring parity (no-drift, mirrors the ci-parity contract) --


def test_guard_wired_into_all_enforcement_surfaces() -> None:
    script = "scripts/check_base_image_digest_pin_drift.py"

    makefile = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert script in makefile, "make ci-parity must run the digest-pin guard"

    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert script in ci, "the lint job must run the digest-pin guard so it gates"

    config = yaml.safe_load((_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    local = next(r for r in config["repos"] if r.get("repo") == "local")
    entries = [h["entry"] for h in local["hooks"]]
    assert any(script in e for e in entries), "a pre-commit hook must run the digest-pin guard"
