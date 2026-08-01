#!/usr/bin/env python3
"""Fail-closed: no CI workflow step hardcodes a topology-specific worker,
CPU, or memory ceiling.

A literal number baked into a CI command — ``pytest -n 16``,
``--maxprocesses=16``, ``--memory=8g`` — only ever matches the machine it was
tuned on. It silently under-utilizes a bigger runner and silently
overcommits/OOMs a smaller one, and nobody notices until the runner changes
underneath the number. The fix is not a *different* constant; it's deriving
the value from whatever capacity the assigned runner actually reports at
run time (``auto`` / ``logical`` / a computed fraction of the visible CPU or
memory), so the same workflow step is correct on any runner size.

This guard scans every tracked ``.github/workflows/*.yml`` file and fails on
a small set of well-known worker/CPU/memory flags when they are followed by
a bare literal number. It does NOT fail on:

  - a capacity-relative value (``auto``, ``logical``, a percentage, a shell
    expansion like ``$(...)``, an environment variable, or a GitHub Actions
    ``${{ ... }}`` expression) — those adapt to whatever runner is assigned;
  - unrelated numeric flags (``timeout-minutes``, ``--health-retries``,
    coverage thresholds, etc.) — this guard only targets worker/CPU/memory
    *sizing*, not time budgets or unrelated counts.

Scope note: this only covers the CI path (workflow files). Production
runtime sizing (e.g. a deploy manifest's process/worker count) is a
deliberately separate concern — a wrong number there is a capacity/ops
question, not a public-repo untrusted-CI-input question, and changing it
carries its own deploy risk that does not belong in a CI-hygiene guard.

Used by:
  - `.pre-commit-config.yaml` (runs on changed files at commit time)
  - `.github/workflows/ci.yml` (runs on every workflow file for full
    coverage)

Stdlib-only; parses under Python 3.12 (the host-syntax guard) and 3.14.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS_DIR = ".github/workflows"

# A value is capacity-relative (allowed) rather than a fixed host-size count
# when it is one of the well-known adaptive keywords, or when it clearly
# is NOT a bare literal integer (a shell/GHA expansion, an env var, a
# percentage). We only flag the unambiguous case: the flag is immediately
# followed by a plain decimal integer.
_ADAPTIVE_KEYWORDS = {"auto", "logical"}

# (flag pattern, requires "pytest" on the same line, human label)
# The `-n`/`-j` short flags are ambiguous with unrelated tools, so they are
# only flagged on a line that also mentions pytest/xdist. The long flags are
# specific enough to xdist/uvicorn/gunicorn-style worker sizing to flag
# unconditionally.
_FLAG_RULES: tuple[tuple[str, bool, str], ...] = (
    (r"-n", True, "pytest-xdist -n"),
    (r"--numprocesses", False, "pytest-xdist --numprocesses"),
    (r"--maxprocesses", False, "pytest-xdist --maxprocesses"),
    (r"--dist-workers", False, "--dist-workers"),
    (r"--workers", False, "--workers"),
    (r"--cpus", False, "--cpus"),
    (r"--memory", False, "--memory"),
)

# `KEY: <literal-int>` YAML-style resource ceilings, e.g. a service
# container's `cpus: "2"` / `mem_limit: 512` (docker-compose-flavoured keys
# that occasionally leak into `options:` blocks).
_YAML_RESOURCE_KEYS: tuple[str, ...] = ("cpus", "mem_limit")

# Env var pytest-xdist reads for the `auto` worker cap. A literal number here
# is the same anti-pattern as `-n <N>` — it should be unset, "auto", or a
# computed value, never a bare constant.
_XDIST_ENV_RE = re.compile(r"PYTEST_XDIST_AUTO_NUM_WORKERS\s*[:=]\s*[\"']?(\d+)[\"']?\b")


def _is_hardcoded_int(raw_value: str) -> bool:
    """Return True if raw_value is a bare literal number, not a capacity-relative one."""
    value = raw_value.strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered in _ADAPTIVE_KEYWORDS:
        return False
    if value.startswith(("$", "%")) or "${{" in value:
        return False
    if value.endswith("%"):
        return False
    return bool(re.fullmatch(r"\d+(?:\.\d+)?[a-zA-Z]*", value))


def _flag_violation(flag: str, line: str) -> str | None:
    """Return the matched literal value if `flag` is followed by a hardcoded int."""
    pattern = re.compile(re.escape(flag) + r"(?:=|\s+)([^\s]+)")
    match = pattern.search(line)
    if not match:
        return None
    value = match.group(1)
    return value if _is_hardcoded_int(value) else None


def find_workflow_files(repo_root: Path) -> list[Path]:
    workflows_dir = repo_root / _WORKFLOWS_DIR
    if not workflows_dir.is_dir():
        return []
    return sorted(p for p in workflows_dir.glob("*.y*ml") if p.is_file())


def find_problems(paths: list[Path]) -> list[tuple[Path, int, str, str]]:
    """Return (path, lineno, raw_line, description) for every hardcoded ceiling."""
    hits: list[tuple[Path, int, str, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - is_file() passed but read failed (race/perm)
            continue
        for lineno, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue

            requires_pytest = "pytest" in stripped or "xdist" in stripped
            for flag, needs_pytest_context, label in _FLAG_RULES:
                if needs_pytest_context and not requires_pytest:
                    continue
                if flag not in stripped:
                    continue
                value = _flag_violation(flag, stripped)
                if value is not None:
                    hits.append((path, lineno, stripped, f"{label} {value} — hardcoded worker/resource count"))

            for key in _YAML_RESOURCE_KEYS:
                key_match = re.match(rf"^{re.escape(key)}\s*:\s*(.+)$", stripped)
                if key_match and _is_hardcoded_int(key_match.group(1)):
                    hits.append((path, lineno, stripped, f"{key}: {key_match.group(1)} — hardcoded resource ceiling"))

            env_match = _XDIST_ENV_RE.search(stripped)
            if env_match:
                hits.append(
                    (
                        path,
                        lineno,
                        stripped,
                        f"PYTEST_XDIST_AUTO_NUM_WORKERS={env_match.group(1)} — hardcoded worker count",
                    )
                )
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="Repo checkout root to scan (default: this script's repo).",
    )
    parser.add_argument("--self-test", action="store_true", help="Run the built-in self-test and exit.")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    repo_root = args.repo_root.resolve()
    workflow_files = find_workflow_files(repo_root)
    if not workflow_files:
        print(
            "ERROR: no .github/workflows/*.yml file found to check — this guard is "
            "wired into a repo with a CI workflow, so zero files means a path/wiring "
            "regression.",
            file=sys.stderr,
        )
        return 1

    problems = find_problems(workflow_files)
    if problems:
        print(
            "ERROR: CI step(s) hardcode a topology-specific worker/CPU/memory ceiling.",
            file=sys.stderr,
        )
        print(
            "       Derive the value from the runner's own capacity at run time "
            "(pytest-xdist's `auto`/`logical`, or a computed fraction of the "
            "scheduler-visible CPU/memory) instead of a fixed number.",
            file=sys.stderr,
        )
        for path, lineno, line, description in problems:
            rel = path.relative_to(repo_root).as_posix()
            print(f"  {rel}:{lineno}: {description}: {line}", file=sys.stderr)
        return 1

    print(f"OK: no hardcoded worker/CPU/memory ceiling across {len(workflow_files)} workflow file(s).")
    return 0


def _self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        workflows = root / _WORKFLOWS_DIR
        workflows.mkdir(parents=True)

        bad = workflows / "bad.yml"
        bad.write_text(
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - run: uv run pytest -n 16 --cov=app\n"
            "      - run: uv run pytest --maxprocesses=8\n"
            '      - run: echo "PYTEST_XDIST_AUTO_NUM_WORKERS=4" >> "$GITHUB_ENV"\n',
            encoding="utf-8",
        )
        bad_problems = find_problems([bad])
        if len(bad_problems) != 3:
            print(f"expected 3 seeded violations, got {len(bad_problems)}: {bad_problems}", file=sys.stderr)
            return 1

        good = workflows / "good.yml"
        good.write_text(
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - run: uv run pytest -n auto --cov=app\n"
            "      - run: uv run pytest -n ${{ steps.cap.outputs.workers }}\n"
            "      - timeout-minutes: 20\n"
            "      - run: echo done\n",
            encoding="utf-8",
        )
        if find_problems([good]):
            print("adaptive-sizing fixture was rejected", file=sys.stderr)
            return 1

        if find_workflow_files(root) != [bad, good]:
            print("find_workflow_files did not discover both fixtures", file=sys.stderr)
            return 1

    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
