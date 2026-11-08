"""Drive pytest from the immutable descriptor rather than a reused env digest."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .cli import _write_json, read_json, read_receipt, receipt_to_json
from .invocation import assert_suite_runtime, command_payload, expected_cases, make_descriptor, source_sha
from .manifest import ShardManifest


def _arguments(command: dict[str, Any], *, collect: bool, partial_coverage: bool = False) -> list[str]:
    argv = command["argv"]
    if not argv or argv[0] != "pytest":
        raise ValueError("pytest suite argv must start with pytest")
    arguments = [*argv[1:], "-p", "ci_shard_helper.pytest_execution"]
    if collect:
        arguments += ["--collect-only"]
        if importlib.util.find_spec("pytest_cov") is not None:
            arguments += ["--no-cov"]
        if any(
            arg in {"-n", "--numprocesses"}
            or arg.startswith("--numprocesses=")
            or re.fullmatch(r"-n(?:[0-9]+|auto|logical)", arg) is not None
            for arg in argv[1:]
        ):
            arguments += ["-n0"]
    elif partial_coverage:
        # Partial data cannot satisfy the suite floor. The strict aggregate
        # separately requires every artifact and evaluates the full 95% floor.
        arguments += ["--cov-fail-under=0"]
    return arguments


def collect_pytest(spec: dict[str, Any], *, root: Path) -> dict[str, Any]:
    command = command_payload(spec, root=root, framework="pytest-file")
    revision = source_sha(root)
    with tempfile.TemporaryDirectory(prefix="pytest-native-collection-") as directory:
        output = Path(directory) / "collection.json"
        environment = {**os.environ, "CI_FLEET_PYTEST_MODE": "collect", "CI_FLEET_COLLECTION_PATH": str(output)}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *_arguments(command, collect=True)], cwd=root, env=environment, check=False
        )
        if result.returncode != 0:
            raise ValueError("complete native pytest collection failed")
        observed = read_json(str(output))
    if (
        not isinstance(observed, dict)
        or set(observed) != {"collection"}
        or not isinstance(observed["collection"], dict)
    ):
        raise ValueError("native pytest collection output is malformed")
    if command_payload(spec, root=root, framework="pytest-file") != command or source_sha(root) != revision:
        raise ValueError("suite invocation/source changed during collection")
    collection = observed["collection"]
    return make_descriptor(
        root=root,
        framework="pytest-file",
        spec=spec,
        collection={unit: entry["cases"] for unit, entry in collection.items()},
        skipped=[unit for unit, entry in collection.items() if entry["skipped"]],
        case_modes={unit: entry["case_modes"] for unit, entry in collection.items()},
    )


def run_pytest(
    manifest: ShardManifest,
    descriptor: dict[str, Any],
    *,
    root: Path,
    shard_id: int,
    manifest_path: Path,
    descriptor_path: Path,
    receipt_path: Path,
    coverage_file: Path | None = None,
) -> None:
    assert_suite_runtime(manifest, descriptor, shard_id, root=root)
    if receipt_path.exists():
        raise ValueError("pytest receipt output already exists")
    environment = {
        **os.environ,
        "CI_FLEET_PYTEST_MODE": "run",
        "CI_FLEET_SHARD_MANIFEST_PATH": str(manifest_path.resolve()),
        "CI_FLEET_SUITE_DESCRIPTOR_PATH": str(descriptor_path.resolve()),
        "CI_FLEET_SHARD_RECEIPT_PATH": str(receipt_path.resolve()),
    }
    if coverage_file is not None:
        if coverage_file.exists():
            raise ValueError("pytest coverage output already exists")
        environment["COVERAGE_FILE"] = str(coverage_file.resolve())
    with tempfile.TemporaryDirectory(prefix="pytest-native-receipt-") as directory:
        provisional = Path(directory) / "receipt.json"
        environment["CI_FLEET_SHARD_RECEIPT_PATH"] = str(provisional)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *_arguments(descriptor["command"], collect=False, partial_coverage=coverage_file is not None),
            ],
            cwd=root,
            env=environment,
            check=False,
        )
        if result.returncode != 0 or not provisional.is_file():
            raise ValueError("pytest shard did not produce successful native case evidence")
        assert_suite_runtime(manifest, descriptor, shard_id, root=root)
        receipt = read_receipt(str(provisional))
        if receipt.completed_cases != expected_cases(manifest, descriptor, shard_id):
            raise ValueError("pytest shard omitted native case completion")
        if coverage_file is not None and (not coverage_file.is_file() or coverage_file.stat().st_size == 0):
            raise ValueError("pytest shard did not produce its coverage artifact")
        _write_json(str(receipt_path), receipt_to_json(receipt))
