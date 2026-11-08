"""Drive a configured native Django runner from its collected suite descriptor."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .cli import _write_json, read_json, read_receipt, receipt_to_json
from .invocation import assert_suite_runtime, command_payload, expected_cases, make_descriptor, source_sha
from .manifest import ShardManifest


def django_arguments(command: dict[str, Any]) -> list[str]:
    argv = list(command["argv"])
    if len(argv) < 2 or argv[1] != "test" or Path(argv[0]).name != "manage.py":
        raise ValueError("Django suite argv must invoke manage.py test")
    if any(arg.startswith("--testrunner") for arg in argv):
        raise ValueError("keep the configured base TEST_RUNNER; the adapter selects its own entry point")
    for index, arg in enumerate(argv):
        if (arg == "--parallel" and (index + 1 >= len(argv) or argv[index + 1] != "1")) or (
            arg.startswith("--parallel=") and arg != "--parallel=1"
        ):
            raise ValueError("native Django shard execution requires --parallel=1")
    if not any(arg == "--parallel" or arg.startswith("--parallel=") for arg in argv):
        argv.append("--parallel=1")
    return [*argv, "--testrunner=ci_shard_helper.django_runner.ShardRunner"]


def collect_django(spec: dict[str, Any], *, root: Path) -> dict[str, Any]:
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise ValueError("native Django descriptor collection requires explicit DJANGO_SETTINGS_MODULE")
    command = command_payload(spec, root=root, framework="Django-label")
    revision = source_sha(root)
    with tempfile.TemporaryDirectory(prefix="django-native-collection-") as directory:
        output = Path(directory) / "collection.json"
        environment = {**os.environ, "CI_FLEET_DJANGO_MODE": "collect", "CI_FLEET_COLLECTION_PATH": str(output)}
        result = subprocess.run([sys.executable, *django_arguments(command)], cwd=root, env=environment, check=False)
        if result.returncode != 0:
            raise ValueError("complete native Django collection failed")
        observed = read_json(str(output))
    if (
        not isinstance(observed, dict)
        or set(observed) != {"collection"}
        or not isinstance(observed["collection"], dict)
    ):
        raise ValueError("native Django collection output is malformed")
    if command_payload(spec, root=root, framework="Django-label") != command or source_sha(root) != revision:
        raise ValueError("suite invocation/source changed during Django collection")
    collection = observed["collection"]
    return make_descriptor(
        root=root,
        framework="Django-label",
        spec=spec,
        collection={unit: entry["cases"] for unit, entry in collection.items()},
        case_modes={unit: entry["case_modes"] for unit, entry in collection.items()},
    )


def run_django(
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
        raise ValueError("Django receipt output already exists")
    environment = {
        **os.environ,
        "CI_FLEET_DJANGO_MODE": "run",
        "CI_FLEET_MANIFEST_PATH": str(manifest_path.resolve()),
        "CI_FLEET_SUITE_DESCRIPTOR_PATH": str(descriptor_path.resolve()),
        "CI_FLEET_SHARD_RECEIPT_PATH": str(receipt_path.resolve()),
    }
    prefix = [sys.executable]
    if coverage_file is not None:
        if coverage_file.exists():
            raise ValueError("Django coverage output already exists")
        environment["COVERAGE_FILE"] = str(coverage_file.resolve())
        prefix += ["-m", "coverage", "run", "--parallel-mode"]
    with tempfile.TemporaryDirectory(prefix="django-native-receipt-") as directory:
        provisional = Path(directory) / "receipt.json"
        environment["CI_FLEET_SHARD_RECEIPT_PATH"] = str(provisional)
        result = subprocess.run(
            [*prefix, *django_arguments(descriptor["command"])], cwd=root, env=environment, check=False
        )
        if result.returncode != 0 or not provisional.is_file():
            raise ValueError("Django shard did not produce successful native case evidence")
        assert_suite_runtime(manifest, descriptor, shard_id, root=root)
        receipt = read_receipt(str(provisional))
        if receipt.completed_cases != expected_cases(manifest, descriptor, shard_id):
            raise ValueError("Django shard omitted native case completion")
        if coverage_file is not None:
            files = list(coverage_file.parent.glob(coverage_file.name + ".*"))
            if len(files) != 1 or files[0].stat().st_size == 0:
                raise ValueError("Django shard did not produce one unique parallel coverage artifact")
        _write_json(str(receipt_path), receipt_to_json(receipt))
