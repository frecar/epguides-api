"""Drive shell shards from source-bound configuration and mandatory invariants."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .cli import _write_json, receipt_to_json
from .invocation import assert_suite_runtime, command_payload, make_descriptor
from .manifest import ShardManifest, make_shard_receipt
from .shell import (
    DEFAULT_CLEANUP_SCRIPT,
    DEFAULT_PREFLIGHT_SCRIPT,
    DEFAULT_TESTS_DIR,
    collect_shell_files,
    run_shell_shard,
)


def shell_configuration(argv: list[str]) -> dict[str, str]:
    if not argv or argv[0] != "shell" or len(argv[1:]) % 2:
        raise ValueError("shell suite argv must start with shell and contain option/value pairs")
    values = {
        "tests_dir": DEFAULT_TESTS_DIR,
        "preflight_script": DEFAULT_PREFLIGHT_SCRIPT,
        "cleanup_script": DEFAULT_CLEANUP_SCRIPT,
    }
    selected: set[str] = set()
    for option, value in zip(argv[1::2], argv[2::2], strict=True):
        key = option.removeprefix("--").replace("-", "_")
        if not option.startswith("--") or key not in values or key in selected:
            raise ValueError("shell suite argv has an unknown or duplicate option")
        selected.add(key)
        values[key] = value
    return values


def collect_shell(spec: dict[str, Any], *, root: Path) -> dict[str, Any]:
    command = command_payload(spec, root=root, framework="shell-file")
    configuration = shell_configuration(command["argv"])
    required_files = {configuration["preflight_script"], configuration["cleanup_script"]}
    if not required_files.issubset(command["config_files"]):
        raise ValueError("shell descriptor must bind its actual preflight and cleanup source files")
    units = collect_shell_files(
        root, tests_dir=configuration["tests_dir"], cleanup_script=configuration["cleanup_script"]
    )
    return make_descriptor(root=root, framework="shell-file", spec=spec, collection={unit: [unit] for unit in units})


def run_shell(
    manifest: ShardManifest, descriptor: dict[str, Any], *, root: Path, shard_id: int, receipt_path: Path
) -> None:
    assert_suite_runtime(manifest, descriptor, shard_id, root=root)
    if receipt_path.exists():
        raise ValueError("shell receipt output already exists")
    configuration = shell_configuration(descriptor["command"]["argv"])
    if not {configuration["preflight_script"], configuration["cleanup_script"]}.issubset(
        descriptor["command"]["config_files"]
    ):
        raise ValueError("shell invocation lost its source-bound cleanup/preflight inputs")
    with tempfile.TemporaryDirectory(prefix="shell-native-receipt-") as directory:
        selected = run_shell_shard(
            root, manifest=manifest, shard_id=shard_id, receipt_path=Path(directory) / "receipt.json", **configuration
        )
    assert_suite_runtime(manifest, descriptor, shard_id, root=root)
    receipt = make_shard_receipt(manifest, shard_id, selected, case_results=dict.fromkeys(selected, "passed"))
    _write_json(str(receipt_path), receipt_to_json(receipt))
