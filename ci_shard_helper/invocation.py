"""Source-bound actual invocation and native case collection for strict shards."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .bundle import bundle_manifest
from .manifest import (
    FRAMEWORK_KINDS,
    ShardManifest,
    ShardReceipt,
    _canonical_json,
    _normalize_unit,
    command_config_payload,
    verify_aggregate,
)
from .runtime import assert_runtime_identity
from .source import TrackedSources

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def adapter_digest() -> str:
    package = Path(__file__).resolve().parent
    files = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.suffix in {".py", ".mjs"}
    }
    return hashlib.sha256(bundle_manifest(files)).hexdigest()


def assert_clean_source(root: Path) -> None:
    result = subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", "--no-textconv", "HEAD", "--"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("checked-out tracked source differs from its Git identity")


def source_sha(root: Path) -> str:
    assert_clean_source(root)
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True)
    value = result.stdout.strip()
    if not _SOURCE.fullmatch(value):
        raise ValueError("checked-out source identity is unavailable")
    return value


_AMBIENT = {
    "pytest-file": ("PYTEST_ADDOPTS", "PYTHONPATH", "PYTHONHASHSEED", "DJANGO_SETTINGS_MODULE"),
    "Django-label": ("DJANGO_SETTINGS_MODULE", "PYTHONPATH", "PYTHONHASHSEED"),
    "Vitest-file": ("NODE_OPTIONS", "NODE_ENV", "TZ"),
    "shell-file": ("BASH_ENV", "ENV"),
}


def _environment(names: Iterable[str], *, root: Path) -> dict[str, str]:
    values = {}
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in values:
            raise ValueError("suite environment names are invalid or duplicate")
        # Bind actual values without publishing credentials or other raw env.
        value = os.environ.get(name)
        if value is not None and name == "PYTHONPATH":
            for path, marker in sorted(
                ((str(root.resolve()), "${CHECKOUT}"), (str(Path(__file__).resolve().parent.parent), "${ADAPTER}")),
                key=lambda item: -len(item[0]),
            ):
                value = value.replace(path, marker)
        values[name] = hashlib.sha256(_canonical_json([value is not None, value])).hexdigest()
    return values


def command_payload(spec: Mapping[str, Any], *, root: Path, framework: str) -> dict[str, object]:
    if not isinstance(spec, dict) or set(spec) != {"argv", "config_files", "environment"}:
        raise ValueError("suite spec requires exactly argv/config_files/environment")
    for key in ("argv", "config_files", "environment"):
        if not isinstance(spec[key], list) or any(not isinstance(value, str) for value in spec[key]):
            raise ValueError(f"suite spec {key} must be an array of strings")
    if len(set(spec["environment"])) != len(spec["environment"]):
        raise ValueError("suite environment inputs are duplicate")
    owned = TrackedSources(root)
    for relative in spec["config_files"]:
        owned.require(Path(relative))
    names = sorted(set(spec["environment"]) | set(_AMBIENT[framework]) | {"GITHUB_RUN_ID"})
    return command_config_payload(
        spec["argv"], root=root, config_files=spec["config_files"], environment=_environment(names, root=root)
    )


def make_descriptor(
    *,
    root: Path,
    framework: str,
    spec: Mapping[str, Any],
    collection: Mapping[str, Sequence[str]],
    skipped: Iterable[str] = (),
    case_modes: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    skipped = set(skipped)
    if framework != "Django-label":
        owned = TrackedSources(root)
        for unit in collection:
            owned.require(Path(unit))
    payload = {
        "format": 1,
        "framework": framework,
        "source_sha": source_sha(root),
        "adapter_sha256": adapter_digest(),
        "command": command_payload(spec, root=root, framework=framework),
        "collection": {
            unit: {
                "cases": sorted(cases),
                "skipped": unit in skipped,
                "case_modes": dict(case_modes[unit]) if case_modes is not None else dict.fromkeys(cases, "run"),
            }
            for unit, cases in sorted(collection.items())
        },
    }
    if skipped - set(collection):
        raise ValueError("skipped collection unit is outside the complete universe")
    validate_descriptor(payload)
    return payload


def validate_descriptor(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "format",
        "framework",
        "source_sha",
        "adapter_sha256",
        "command",
        "collection",
    }:
        raise ValueError("suite descriptor has missing or broadened fields")
    if type(value["format"]) is not int or value["format"] != 1 or value["framework"] not in FRAMEWORK_KINDS:
        raise ValueError("suite descriptor format/framework is invalid")
    if not isinstance(value["source_sha"], str) or not _SOURCE.fullmatch(value["source_sha"]):
        raise ValueError("suite descriptor source is invalid")
    if not isinstance(value["adapter_sha256"], str) or not _SHA.fullmatch(value["adapter_sha256"]):
        raise ValueError("suite descriptor adapter identity is invalid")
    command = value["command"]
    if not isinstance(command, dict) or set(command) != {"format", "argv", "config_files", "environment"}:
        raise ValueError("suite command has missing or broadened fields")
    if (
        type(command["format"]) is not int
        or command["format"] != 1
        or not isinstance(command["argv"], list)
        or not command["argv"]
        or any(not isinstance(arg, str) for arg in command["argv"])
    ):
        raise ValueError("suite command argv is invalid")
    for key in ("config_files", "environment"):
        if not isinstance(command[key], dict) or any(
            not isinstance(name, str) or not isinstance(digest, str) or not _SHA.fullmatch(digest)
            for name, digest in command[key].items()
        ):
            raise ValueError("suite command input digest is invalid")
    collection = value["collection"]
    if not isinstance(collection, dict) or not collection:
        raise ValueError("suite native collection is empty")
    seen: set[str] = set()
    for unit, entry in collection.items():
        if (
            _normalize_unit(value["framework"], unit) != unit
            or not isinstance(entry, dict)
            or set(entry) != {"cases", "skipped", "case_modes"}
            or type(entry["skipped"]) is not bool
        ):
            raise ValueError("suite collection unit is invalid")
        cases = entry["cases"]
        if (
            not isinstance(cases, list)
            or any(not isinstance(case, str) or not case or any(ord(char) < 32 for char in case) for case in cases)
            or cases != sorted(set(cases))
        ):
            raise ValueError("suite native case identities are malformed or duplicate")
        if value["framework"] == "Vitest-file" and not cases:
            raise ValueError("Vitest suite contains a zero-case module")
        modes = entry["case_modes"]
        if (
            not isinstance(modes, dict)
            or set(modes) != set(cases)
            or any(mode not in {"run", "only", "skip", "todo"} for mode in modes.values())
        ):
            raise ValueError("suite native case modes differ from its complete case identities")
        if seen.intersection(cases):
            raise ValueError("suite native case identity occurs in multiple units")
        seen.update(cases)
    if not seen:
        raise ValueError("suite collected zero native test cases")
    if not any(mode in {"run", "only"} for entry in collection.values() for mode in entry["case_modes"].values()):
        raise ValueError("suite selected no executable native test cases")


def descriptor_digest(descriptor: dict[str, Any]) -> str:
    validate_descriptor(descriptor)
    return hashlib.sha256(_canonical_json(descriptor)).hexdigest()


def assert_descriptor(manifest: ShardManifest, descriptor: dict[str, Any]) -> None:
    if manifest.format_version != 2 or descriptor_digest(descriptor) != manifest.command_config_sha256:
        raise ValueError("suite descriptor differs from the format-2 command/collection identity")
    if (
        descriptor["framework"] != manifest.framework
        or descriptor["source_sha"] != manifest.source_sha
        or tuple(sorted(descriptor["collection"])) != manifest.units
    ):
        raise ValueError("suite descriptor collection/source/framework differs from the manifest")


def expected_cases(manifest: ShardManifest, descriptor: dict[str, Any], shard_id: int) -> tuple[str, ...]:
    assert_descriptor(manifest, descriptor)
    if type(shard_id) is not int or not 1 <= shard_id <= manifest.shard_total:
        raise ValueError("shard identity is outside the manifest")
    cases = tuple(
        sorted(case for unit in manifest.shards[shard_id - 1] for case in descriptor["collection"][unit]["cases"])
    )
    if not cases or not any(
        mode in {"run", "only"}
        for unit in manifest.shards[shard_id - 1]
        for mode in descriptor["collection"][unit]["case_modes"].values()
    ):
        raise ValueError("shard contains zero executable native test cases")
    return cases


def assert_suite_runtime(manifest: ShardManifest, descriptor: dict[str, Any], shard_id: int, *, root: Path) -> None:
    assert_runtime_identity(manifest, shard_id, root=root)
    assert_clean_source(root)
    assert_descriptor(manifest, descriptor)
    if descriptor["adapter_sha256"] != adapter_digest():
        raise ValueError("framework adapter source changed after collection")
    command = descriptor["command"]
    spec = {
        "argv": command["argv"],
        "config_files": list(command["config_files"]),
        "environment": list(command["environment"]),
    }
    if command_payload(spec, root=root, framework=manifest.framework) != command:
        raise ValueError("actual suite command/config/environment differs from collection")
    expected_cases(manifest, descriptor, shard_id)


def verify_execution_aggregate(
    manifest: ShardManifest, descriptor: dict[str, Any], receipts: Iterable[ShardReceipt]
) -> None:
    assert_descriptor(manifest, descriptor)
    receipts = tuple(receipts)
    verify_aggregate(manifest, receipts)
    for receipt in receipts:
        if receipt.completed_cases != expected_cases(manifest, descriptor, receipt.shard_id):
            raise ValueError("shard receipt lacks the exact native test-case completion evidence")
        if (
            receipt.case_results is None
            or any(outcome not in {"passed", "skipped", "expected-failure"} for _, outcome in receipt.case_results)
            or not any(outcome in {"passed", "expected-failure"} for _, outcome in receipt.case_results)
        ):
            raise ValueError("shard lacks a successful executable native test outcome")
        modes = {
            case: mode
            for unit in manifest.shards[receipt.shard_id - 1]
            for case, mode in descriptor["collection"][unit]["case_modes"].items()
        }
        if any(modes[case] in {"skip", "todo"} and outcome != "skipped" for case, outcome in receipt.case_results):
            raise ValueError("native case outcome differs from its source-bound selection mode")


def read_descriptor(path: str | Path) -> dict[str, Any]:
    from .cli import read_json

    value = read_json(str(path))
    validate_descriptor(value)
    return value
