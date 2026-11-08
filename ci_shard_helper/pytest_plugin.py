"""Portable pytest collection and successful-run receipts for format 2."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from .cli import read_manifest, receipt_to_json
from .manifest import ShardManifest, make_shard_receipt, validate_manifest
from .runtime import assert_runtime_identity
from .source import TrackedSources


def _read_manifest(path: str) -> ShardManifest:
    return read_manifest(path)


def _positive_env(name: str) -> int:
    value = os.environ.get(name, "")
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        raise ValueError(f"{name} must be a positive decimal integer")
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{name} must be positive")
    return parsed


def _item_unit(item: pytest.Item, root: Path, owned: TrackedSources | None = None) -> str:
    item_path = getattr(item, "path", None)
    if item_path is None:
        item_path = item.fspath
    raw_path = Path(str(item_path))
    path = owned.require(raw_path) if owned is not None else raw_path.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"collected test is outside the checkout: {path}") from exc


def _report_path_unit(nodeid: str, root: Path, candidates: set[str] | None = None) -> str | None:
    path = Path(nodeid.split("::", 1)[0])
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        unit = resolved.relative_to(root).as_posix()
    except ValueError:
        return None
    if candidates is not None and unit not in candidates:
        return None
    return unit if path.suffix == ".py" else None


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(serialized)


class PytestCollectionPlugin:
    """Record test files evidenced by a complete successful collect-only run."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.root = Path(str(config.rootpath)).resolve()
        output = os.environ.get("CI_FLEET_COLLECTION_PATH", "")
        if not output:
            raise ValueError("CI_FLEET_COLLECTION_PATH is required for collection discovery")
        self.output = Path(output)
        self.units: set[str] = set()
        self.item_units: set[str] = set()

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        unit = _report_path_unit(report.nodeid, self.root)
        if unit is not None and report.outcome in {"passed", "skipped"}:
            self.units.add(unit)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.item_units.update(_item_unit(item, self.root) for item in session.items)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if exitstatus != pytest.ExitCode.OK:
            return
        units = tuple(sorted(self.units | self.item_units))
        if not units:
            return
        _write_json_new(self.output, list(units))


class PytestShardReceiptPlugin:
    """Write a v2 receipt only after exact collection and a successful session."""

    def __init__(self, config: pytest.Config, manifest: ShardManifest, *, allow_legacy: bool = False) -> None:
        validate_manifest(manifest)
        if manifest.framework != "pytest-file":
            raise ValueError("pytest receipt requires a pytest-file manifest")
        if manifest.format_version != 2 and not allow_legacy:
            raise ValueError("portable pytest receipt requires an identity-bound format-2 manifest")
        self.config = config
        self.manifest = manifest
        self.root = Path(str(config.rootpath)).resolve()
        self.shard_id = _positive_env("SHARD_ID")
        self.shard_total = _positive_env("SHARD_TOTAL")
        if self.shard_total != manifest.shard_total:
            raise ValueError("SHARD_TOTAL does not match the source-bound manifest")
        if self.shard_id > manifest.shard_total:
            raise ValueError("SHARD_ID is outside the source-bound manifest")

        if manifest.format_version == 2:
            self._assert_runtime_identity()
        if manifest.format_version != 2:
            actual_source = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.root, check=True, capture_output=True, text=True
            ).stdout.strip()
            if actual_source != manifest.source_sha:
                raise ValueError("checked-out source SHA differs from the manifest")

        receipt_path = os.environ.get("CI_FLEET_SHARD_RECEIPT_PATH", "")
        if not receipt_path:
            raise ValueError("CI_FLEET_SHARD_RECEIPT_PATH is required in shard mode")
        self.receipt_path = Path(receipt_path)
        self.expected_units = set(manifest.shards[self.shard_id - 1])
        self.selected_units: tuple[str, ...] | None = None
        self.collection_units: set[str] = set()
        self.worker_collection_units: set[str] = set()
        self.reported_units: set[str] = set()

    def _assert_runtime_identity(self) -> None:
        assert_runtime_identity(self.manifest, self.shard_id, root=self.root)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        selected = {_item_unit(item, self.root) for item in session.items}
        if not selected.issubset(self.expected_units):
            raise ValueError("pytest selected file units outside this manifest shard")
        observed = selected | self.collection_units
        if observed != self.expected_units:
            raise ValueError("pytest collection evidence differs from this manifest shard")
        self.selected_units = tuple(sorted(observed))

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        unit = _report_path_unit(report.nodeid, self.root, set(self.manifest.units))
        if unit is not None and report.outcome in {"passed", "skipped"}:
            self.collection_units.add(unit)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        unit = _report_path_unit(report.nodeid, self.root, set(self.manifest.units))
        if unit is not None:
            self.reported_units.add(unit)

    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        if error is not None:
            raise ValueError("pytest-xdist worker exited with an error")
        workeroutput = getattr(node, "workeroutput", {})
        if (
            workeroutput.get("ci_fleet_manifest_digest") != self.manifest.digest
            or workeroutput.get("ci_fleet_shard_id") != self.shard_id
            or set(workeroutput.get("ci_fleet_collected_units", [])) != self.expected_units
        ):
            raise ValueError("xdist worker did not prove exact manifest collection")
        self.worker_collection_units.update(self.expected_units)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if hasattr(self.config, "workerinput"):
            if self.selected_units is not None:
                self.config.workeroutput["ci_fleet_manifest_digest"] = self.manifest.digest
                self.config.workeroutput["ci_fleet_shard_id"] = self.shard_id
                self.config.workeroutput["ci_fleet_collected_units"] = list(self.selected_units)
            return
        if exitstatus != pytest.ExitCode.OK:
            return
        collected = set(self.selected_units or ()) | self.worker_collection_units
        if collected != self.expected_units:
            raise ValueError("pytest collection evidence differs from this manifest shard")
        if not self.reported_units.issubset(self.expected_units):
            raise ValueError("successful pytest reports include a file outside this manifest shard")
        receipt = make_shard_receipt(self.manifest, self.shard_id, collected)
        _write_json_new(self.receipt_path, receipt_to_json(receipt))


def pytest_configure(config: pytest.Config) -> None:
    mode = os.environ.get("CI_FLEET_PYTEST_MODE", "")
    if not mode:
        return
    if mode == "collect":
        plugin = PytestCollectionPlugin(config)
    elif mode == "run":
        manifest_path = os.environ.get("CI_FLEET_SHARD_MANIFEST_PATH", "")
        if not manifest_path:
            raise ValueError("CI_FLEET_SHARD_MANIFEST_PATH is required in shard mode")
        plugin = PytestShardReceiptPlugin(config, _read_manifest(manifest_path))
    else:
        raise ValueError("CI_FLEET_PYTEST_MODE must be collect or run")
    config.pluginmanager.register(plugin, "ci-fleet-pytest-shard")
