#!/usr/bin/env python3
"""Block owner-scoped Git dependency sources outside this public repository."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OWNER = "frecar"
MANIFEST_NAMES = {"Cargo.toml", "package.json", "pyproject.toml"}
GITHUB_REPO_RE = re.compile(
    r"(?:github\.com[:/]|github:)" + re.escape(OWNER) + r"/(?P<repo>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    path: Path
    context: str
    repo: str
    value: str


def repo_from_match(raw_repo: str) -> str:
    return raw_repo.removesuffix(".git").lower()


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip())
    return Path.cwd()


def allowed_repos(root: Path) -> set[str]:
    repos = {root.name.lower()}
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner_prefix = f"{OWNER}/"
    if github_repository.lower().startswith(owner_prefix):
        repos.add(github_repository.split("/", 1)[1].lower())

    origin = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    if origin.returncode == 0:
        for match in GITHUB_REPO_RE.finditer(origin.stdout.strip()):
            repos.add(repo_from_match(match.group("repo")))
    return repos


def default_manifest_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        paths = [root / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]
    else:
        paths = [path for path in root.rglob("*") if path.is_file()]
    return [path for path in paths if path.name in MANIFEST_NAMES]


def load_manifest(path: Path) -> Any:
    if path.name == "package.json":
        return json.loads(path.read_text(encoding="utf-8"))
    return tomllib.loads(path.read_text(encoding="utf-8"))


def walk_strings(value: Any, context: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(context, value)]
    if isinstance(value, list):
        found: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            found.extend(walk_strings(item, f"{context}[{index}]"))
        return found
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            found.extend(walk_strings(item, f"{context}.{key}"))
        return found
    return []


def find_violations(paths: list[Path], allowed: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if not path.exists() or not path.is_file() or path.name not in MANIFEST_NAMES:
            continue
        try:
            manifest = load_manifest(path)
        except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            findings.append(Finding(path, "parse", "-", f"could not parse manifest: {exc}"))
            continue

        for context, value in walk_strings(manifest):
            for match in GITHUB_REPO_RE.finditer(value):
                repo = repo_from_match(match.group("repo"))
                if repo not in allowed:
                    findings.append(Finding(path, context, repo, value))
    return findings


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixtures = {
            "pyproject.toml": """
[project]
name = "demo"
dependencies = [
    "demo @ git+https://github.com/frecar/example-private.git",
]
""",
            "package.json": json.dumps(
                {"dependencies": {"demo": "git+ssh://git@github.com/frecar/example-private.git"}}
            ),
            "Cargo.toml": """
[dependencies]
demo = { git = "https://github.com/frecar/example-private.git" }
""",
        }
        paths = []
        for name, content in fixtures.items():
            path = root / name
            path.write_text(content, encoding="utf-8")
            paths.append(path)

        findings = find_violations(paths, {"example-public"})
        if len(findings) != 3:
            print(f"expected 3 seeded violations, got {len(findings)}", file=sys.stderr)
            return 1

        allowed_dir = root / "allowed"
        allowed_dir.mkdir()
        allowed_path = allowed_dir / "pyproject.toml"
        allowed_path.write_text(
            """
[project]
name = "demo"
dependencies = [
    "demo @ git+https://github.com/frecar/example-public.git",
]
""",
            encoding="utf-8",
        )
        if find_violations([allowed_path], {"example-public"}):
            print("allowed repository fixture was rejected", file=sys.stderr)
            return 1

    print("self-test passed")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        if len(argv) > 1:
            print("--self-test does not accept file arguments", file=sys.stderr)
            return 2
        return self_test()

    root = repo_root()
    paths = [Path(arg) for arg in argv] if argv else default_manifest_files(root)
    findings = find_violations(paths, allowed_repos(root))
    for finding in findings:
        print(f"{finding.path}: {finding.context}: blocked Git dependency source: {finding.value}")

    if findings:
        print()
        print(f"FAIL: {len(findings)} owner-scoped Git dependency source(s) found.")
        print("Only this repository may be referenced from dependency Git URLs.")
        print("Use a registry release or a public package source instead.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
