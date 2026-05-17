#!/usr/bin/env python3
"""Enforce the cluster LLM policy (asgard#801): no pay-per-token external
LLM API endpoints in committed code.

The cluster's design target is `llm.carlsen.io` for all LLM calls. External
pay-per-token APIs (`api.anthropic.com`, `api.openai.com`, etc.) add cost,
privacy exposure, and third-party dependency. Documented in
`feedback_llm_local.md` and the policy issue.

This script flags any reference to those endpoints in committed files.
Test fixtures and benchmark scripts are exempt (they may legitimately
need to test against / benchmark these APIs). Documentation that explains
the policy can opt out per-line via `# llm-policy: ignore`.

Used by:
  - `.pre-commit-config.yaml` (runs on changed files at commit time)
  - `.github/workflows/ci.yml` (runs on all files for full coverage)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Pattern split + reassembled at runtime so this file itself doesn't
# trigger the lint when run against the whole tree.
_FORBIDDEN_HOSTS = ("anthropic", "openai")
PATTERN = re.compile(r"api\." + r"(?:" + "|".join(_FORBIDDEN_HOSTS) + r")" + r"\.com")

# Per-line opt-out — for docs/runbooks/issue bodies that need to name the
# forbidden patterns when explaining the policy.
IGNORE_MARKER = "llm-policy: ignore"

# Path fragments / filenames that are always allowed (tests, benchmarks,
# this script itself, virtualenvs, build artifacts).
ALLOWED_PATH_FRAGMENTS = (
    "/tests/",
    "/test/",
    "/.venv/",
    "/node_modules/",
    "/__pycache__/",
    "/.git/",
    "/.next/",
    "/.cache/",
    "/.mypy_cache/",
    "/.ruff_cache/",
    "/.pytest_cache/",
    "/site-packages/",
    "/dist/",
    "/build/",
)
ALLOWED_FILENAMES = {
    "check_no_external_llm.py",
    "benchmark_llm.py",
}
# File extensions we DO want to check. Skip binaries, lockfiles, etc.
CHECKED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".yaml",
    ".yml",
    ".toml",
    ".env",
    ".env.example",
    ".env.production",
    ".sh",
    ".bash",
    ".rs",
}


def is_allowed_path(path: Path) -> bool:
    """Return True if the file is in an allowlisted location."""
    path_str = str(path)
    if any(frag in path_str for frag in ALLOWED_PATH_FRAGMENTS):
        return True
    if path.name in ALLOWED_FILENAMES:
        return True
    # Benchmark scripts are allowlisted by prefix convention.
    return path.name.startswith("benchmark_")


def should_check_file(path: Path) -> bool:
    """Return True if this file type is worth scanning."""
    if path.suffix in CHECKED_EXTENSIONS:
        return True
    # Match `.env.<anything>` files (`.env.production`, `.env.dev`, …).
    return path.name.startswith(".env")


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a list of (line_no, line_content) violations."""
    violations: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return violations
    for i, line in enumerate(text.split("\n"), start=1):
        if PATTERN.search(line) and IGNORE_MARKER not in line:
            violations.append((i, line.rstrip()))
    return violations


def main(argv: list[str]) -> int:
    if argv:
        # Pre-commit pass: argv is the list of changed files.
        files = [Path(a) for a in argv]
    else:
        # CI / manual pass: walk the entire repo from CWD.
        repo_root = Path.cwd()
        files = [p for p in repo_root.rglob("*") if p.is_file()]

    violation_count = 0
    for f in files:
        if not f.exists() or not f.is_file():
            continue
        if is_allowed_path(f):
            continue
        if not should_check_file(f):
            continue
        for line_no, content in check_file(f):
            print(f"{f}:{line_no}: forbidden external LLM endpoint: {content}")
            violation_count += 1

    if violation_count:
        print()
        print(f"FAIL: {violation_count} violation(s) of cluster LLM policy (asgard#801).")
        print()
        print("Cluster policy: route all LLM calls through llm.carlsen.io.")
        print("Pay-per-token external APIs (api.anthropic.com, api.openai.com,")
        print("etc.) are forbidden in committed code.")
        print()
        print("Fix options:")
        print("  - Replace the endpoint with https://llm.carlsen.io/v1 (or env-driven default)")
        print("  - If the line is documentation that needs to name the forbidden")
        print(f"    pattern, append a trailing comment: `# {IGNORE_MARKER}`")
        print("  - If it's a test fixture, move the file under tests/ (allowlisted)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
