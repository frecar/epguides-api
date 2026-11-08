#!/usr/bin/env python3
"""Source-bound pytest CI integration; generated adapters own execution evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ci_shard_helper.bundle import verify_bundle  # noqa: E402
from ci_shard_helper.cli import read_manifest  # noqa: E402
from ci_shard_helper.invocation import descriptor_digest, read_descriptor  # noqa: E402

CAPABILITY = "untrusted-linux-docker-x64"
SUITE = "pytest"
SPEC = ".github/pytest-suite.json"
MAX_CAPACITY = 1024
MAX_SHARDS = 256


def positive(value: str, *, maximum: int) -> int:
    if not isinstance(value, str) or not value.isascii() or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("a positive decimal identity/capacity is required")
    number = int(value)
    if number > maximum:
        raise ValueError("identity/capacity exceeds its bound")
    return number


def identity() -> tuple[str, int]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GitHub repository identity is unavailable")
    return repository, positive(os.environ.get("GITHUB_REPOSITORY_ID", ""), maximum=2**63 - 1)


def fleet_requested() -> bool:
    # Missing fork-origin evidence takes the hosted path.
    return os.environ.get("CI_FLEET_UNTRUSTED_ENABLED") == "true" and os.environ.get("CI_FORK_PR") == "false"


def gate(plan_result: str, shards_result: str) -> None:
    expected = "success" if fleet_requested() else "skipped"
    if plan_result != expected or shards_result != expected:
        raise ValueError("required pytest planning/execution did not complete")


def helper(*arguments: str) -> None:
    subprocess.run([sys.executable, "-m", "ci_shard_helper.cli", *arguments], cwd=ROOT, check=True)


def plan(directory: Path, *, capacity: int) -> list[int]:
    if type(capacity) is not int or not 1 <= capacity <= MAX_CAPACITY:
        raise ValueError("qualified isolated Docker capacity is unavailable")
    repository, repository_id = identity()
    verify_bundle(ROOT / "ci_shard_helper")
    directory.mkdir(parents=True, exist_ok=False)
    descriptor_path, manifest_path = directory / "suite.json", directory / "manifest.json"
    helper("collect-pytest", "--spec", SPEC, "--output", str(descriptor_path))
    descriptor = read_descriptor(descriptor_path)
    total = min(max(1, capacity - 1), len(descriptor["collection"]), MAX_SHARDS)
    if total < 1:
        raise ValueError("complete pytest collection is empty")
    helper(
        "plan",
        "--suite-descriptor",
        str(descriptor_path),
        "--source-sha",
        descriptor["source_sha"],
        "--shards",
        str(total),
        "--compatible-capacity",
        str(capacity),
        "--repository-id",
        str(repository_id),
        "--repository",
        repository,
        "--capability",
        CAPABILITY,
        "--suite",
        SUITE,
        "--output",
        str(manifest_path),
    )
    return list(range(1, total + 1))


def bound_manifest(directory: Path):
    verify_bundle(ROOT / "ci_shard_helper")
    manifest = read_manifest(str(directory / "manifest.json"))
    repository, repository_id = identity()
    if (
        manifest.format_version != 2
        or manifest.framework != "pytest-file"
        or manifest.repository != repository
        or manifest.repository_id != repository_id
        or manifest.capability != CAPABILITY
        or manifest.suite != SUITE
    ):
        raise ValueError("pytest manifest crosses its execution identity")
    return manifest


def run(directory: Path, output: Path, *, shard: int) -> None:
    manifest = bound_manifest(directory)
    if type(shard) is not int or not 1 <= shard <= manifest.shard_total:
        raise ValueError("pytest shard identity is outside the complete plan")
    descriptor = read_descriptor(directory / "suite.json")
    os.environ.update(
        CI_FLEET_REPOSITORY_ID=str(identity()[1]),
        CI_FLEET_CAPABILITY=CAPABILITY,
        CI_FLEET_SUITE=SUITE,
        CI_FLEET_COMMAND_CONFIG_SHA256=descriptor_digest(descriptor),
        CI_FLEET_MANIFEST_DIGEST=manifest.digest,
        CI_FLEET_MANIFEST_SOURCE_SHA=manifest.source_sha,
        SHARD_ID=str(shard),
        SHARD_TOTAL=str(manifest.shard_total),
    )
    output.mkdir(parents=True, exist_ok=False)
    helper(
        "run-pytest",
        "--manifest",
        str(directory / "manifest.json"),
        "--suite-descriptor",
        str(directory / "suite.json"),
        "--source-sha",
        manifest.source_sha,
        "--shard-id",
        str(shard),
        "--coverage-file",
        str(output / ".coverage"),
        "--output",
        str(output / "receipt.json"),
    )


def combine(directory: Path, artifacts: Path, output: Path) -> None:
    manifest = bound_manifest(directory)
    pairs = sorted(artifacts.rglob("receipt.coverage.json"))
    if len(pairs) != manifest.shard_total:
        raise ValueError("complete sealed shard evidence is unavailable")
    helper(
        "combine-python-coverage",
        "--manifest",
        str(directory / "manifest.json"),
        "--suite-descriptor",
        str(directory / "suite.json"),
        "--source-sha",
        manifest.source_sha,
        "--coverage-output",
        str(output),
        *[item for pair in pairs for item in ("--coverage-pair", str(pair))],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("single", "plan", "run", "combine", "gate", "verify-bundle", "capacity"))
    parser.add_argument("--directory", type=Path, default=ROOT / ".ci-pytest")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--shard", type=int)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    try:
        if args.action == "verify-bundle":
            verify_bundle(ROOT / "ci_shard_helper")
        elif args.action == "capacity":
            if not fleet_requested():
                raise ValueError("parallel routing is not explicitly enabled")
            positive(os.environ.get("CI_QUALIFIED_DOCKER_CAPACITY", ""), maximum=MAX_CAPACITY)
        elif args.action == "gate":
            gate(os.environ.get("CI_PLAN_RESULT", ""), os.environ.get("CI_SHARDS_RESULT", ""))
        elif args.action == "plan":
            if not fleet_requested():
                raise ValueError("parallel routing is not explicitly enabled")
            capacity = positive(os.environ.get("CI_QUALIFIED_DOCKER_CAPACITY", ""), maximum=MAX_CAPACITY)
            shards = plan(directory, capacity=capacity)
            if os.environ.get("GITHUB_OUTPUT"):
                with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                    stream.write("shards=" + json.dumps(shards) + "\n")
        elif args.action == "single":
            if fleet_requested():
                raise ValueError("enabled parallel routing cannot fall back to an unverified single run")
            plan(directory, capacity=1)
            run(directory, directory / "artifacts/shard-1", shard=1)
            combine(directory, directory / "artifacts", directory / "combined.coverage")
        elif args.action == "run":
            if not fleet_requested() or args.shard is None:
                raise ValueError("explicit parallel routing and shard identity are required")
            run(directory, directory / ("artifacts/shard-" + str(args.shard)), shard=args.shard)
        else:
            if not fleet_requested() or args.artifacts is None:
                raise ValueError("parallel aggregation needs explicit routing and complete artifacts")
            combine(directory, args.artifacts.resolve(), directory / "combined.coverage")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"pytest CI evidence refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
