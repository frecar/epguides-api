#!/usr/bin/env python3
"""Enforce the LLM endpoint policy: no pay-per-token external LLM API
endpoints in committed code.

LLM calls should resolve their endpoint at runtime from configuration (an
approved proxy/gateway) rather than hard-coding a third-party host. External
pay-per-token APIs (`api.anthropic.com`, `api.openai.com`, etc.) add cost,
privacy exposure, and third-party dependency. See internal tracking for the
policy rationale.

This script flags any reference to those endpoints in committed files.
Test fixtures and benchmark scripts are exempt (they may legitimately
need to test against / benchmark these APIs). Documentation that explains
the policy can opt out per-line via `# llm-policy: ignore`.

Used by:
  - `.pre-commit-config.yaml` (runs on changed files at commit time)
  - `.github/workflows/ci.yml` (runs on all files for full coverage)
"""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

_FORBIDDEN_HOSTS = ("anthropic", "openai")
PATTERN = re.compile(r"api\." + r"(?:" + "|".join(_FORBIDDEN_HOSTS) + r")" + r"\.com")

IGNORE_MARKER = "llm-policy: ignore"

# Verified 2026-11-28: allowlisted components are generic test/tool/build dirs;
# the tracked tree's .j2/.json/.conf/.mjs files were unscanned, now checked and clean.
LITERAL_REVIEW_BY = date(2027, 5, 28)

ALLOWED_PATH_COMPONENTS = (
    "tests",
    "test",
    ".venv",
    "node_modules",
    "__pycache__",
    ".git",
    ".claude",
    ".next",
    ".cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    "dist",
    "build",
)
ALLOWED_FILENAMES = {
    "check_no_external_llm.py",
}
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
    ".j2",
    ".json",
    ".conf",
    ".mjs",
}


def is_allowed_path(path: Path) -> bool:
    """Return True if the file is in an allowlisted location."""
    if any(part in ALLOWED_PATH_COMPONENTS for part in path.parts):
        return True
    if path.name in ALLOWED_FILENAMES:
        return True
    return path.name.startswith("benchmark_")


def should_check_file(path: Path) -> bool:
    """Return True if this file type is worth scanning."""
    if path.suffix in CHECKED_EXTENSIONS:
        return True
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


def _review_lapsed(review_by: date) -> bool:
    """A lapsed review date is a stderr warning on the real clock,
    never a failure (it would dequeue the whole merge group on one calendar day).
    Tests that prove the lapse is detected set ENFORCE_REVIEW_LAPSE=1."""
    if datetime.now(UTC).date() <= review_by:
        return False
    if os.environ.get("ENFORCE_REVIEW_LAPSE") == "1":
        return True
    print(f"WARNING (non-blocking): review date {review_by.isoformat()} has lapsed", file=sys.stderr)
    return False


def main(argv: list[str]) -> int:
    if _review_lapsed(LITERAL_REVIEW_BY):
        print(
            f"FAIL: the allowlist/extension review date ({LITERAL_REVIEW_BY.isoformat()}) "
            "has lapsed — re-examine ALLOWED_PATH_COMPONENTS, ALLOWED_FILENAMES, and "
            "CHECKED_EXTENSIONS, then move LITERAL_REVIEW_BY forward deliberately."
        )
        return 1
    if argv:
        files = [Path(a) for a in argv]
    else:
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
        print(f"FAIL: {violation_count} violation(s) of the LLM endpoint policy.")
        print()
        print("Policy: route all LLM calls through an approved proxy/gateway.")
        print("Pay-per-token external APIs (api.anthropic.com, api.openai.com,")
        print("etc.) are forbidden in committed code.")
        print()
        print("Fix options:")
        print("  - Replace the endpoint with a configured gateway URL (env-driven default)")
        print("  - If the line is documentation that needs to name the forbidden")
        print(f"    pattern, append a trailing comment: `# {IGNORE_MARKER}`")
        print("  - If it's a test fixture, move the file under tests/ (allowlisted)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
