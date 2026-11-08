"""Strict native pytest case collection and terminal execution observations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from .cli import read_manifest, receipt_to_json
from .invocation import assert_suite_runtime, expected_cases, read_descriptor
from .manifest import make_shard_receipt
from .pytest_plugin import _item_unit, _positive_env, _report_path_unit, _write_json_new
from .source import TrackedSources


class ExecutionPlugin:
    def __init__(self, config: pytest.Config, mode: str) -> None:
        self.config, self.mode = config, mode
        self.root = Path(str(config.rootpath)).resolve()
        self.sources = TrackedSources(self.root)
        self.collection: dict[str, dict[str, Any]] = {}
        self.full_collection_verified = False
        self.terminal: list[tuple[str, str]] = []
        self.controller = not hasattr(config, "workerinput") and bool(getattr(config.option, "numprocesses", 0))
        if mode == "run":
            self.manifest = read_manifest(os.environ["CI_FLEET_SHARD_MANIFEST_PATH"])
            self.descriptor = read_descriptor(os.environ["CI_FLEET_SUITE_DESCRIPTOR_PATH"])
            self.shard_id = _positive_env("SHARD_ID")
            assert_suite_runtime(self.manifest, self.descriptor, self.shard_id, root=self.root)
            if self.manifest.framework != "pytest-file":
                raise ValueError("pytest execution requires a pytest-file descriptor")
            self.expected = expected_cases(self.manifest, self.descriptor, self.shard_id)
            self.units = self.manifest.shards[self.shard_id - 1]

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        unit = _report_path_unit(report.nodeid, self.root)
        if unit is not None and report.outcome in {"passed", "skipped"}:
            entry = self.collection.setdefault(unit, {"cases": [], "skipped": False, "case_modes": {}})
            entry["skipped"] = entry["skipped"] or report.outcome == "skipped"

    def _native_collection(self, items: list[pytest.Item]) -> dict[str, dict[str, Any]]:
        result = {
            unit: {"cases": [], "skipped": entry["skipped"], "case_modes": {}}
            for unit, entry in self.collection.items()
        }
        for item in items:
            unit = _item_unit(item, self.root, self.sources)
            entry = result.setdefault(unit, {"cases": [], "skipped": False, "case_modes": {}})
            entry["cases"].append(item.nodeid)
            skip = item.get_closest_marker("skip")
            skipif = item.get_closest_marker("skipif")
            mode = (
                "skip"
                if skip is not None or (skipif is not None and any(value is True for value in skipif.args))
                else "run"
            )
            entry["case_modes"][item.nodeid] = mode
        for entry in result.values():
            entry["cases"].sort()
            if entry["cases"]:
                entry["skipped"] = False
        return dict(sorted(result.items()))

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session: pytest.Session, config: pytest.Config, items: list[pytest.Item]):
        yield
        if self.mode == "run":
            observed = self._native_collection(items)
            if observed != self.descriptor["collection"]:
                raise ValueError("native pytest case collection differs from the complete source-bound suite")
            self.full_collection_verified = True
            selected = [item for item in items if _item_unit(item, self.root, self.sources) in self.units]
            deselected = [item for item in items if _item_unit(item, self.root, self.sources) not in self.units]
            if deselected:
                config.hook.pytest_deselected(items=deselected)
            items[:] = selected

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if self.controller:
            return
        if self.mode == "collect":
            self.collection = self._native_collection(list(session.items))
        elif tuple(sorted(item.nodeid for item in session.items)) != self.expected:
            raise ValueError("selected pytest test cases differ from the manifest shard")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if self.mode == "run" and (report.when == "call" or (report.when == "setup" and report.outcome == "skipped")):
            outcome = (
                "expected-failure" if hasattr(report, "wasxfail") and report.outcome == "skipped" else report.outcome
            )
            self.terminal.append((report.nodeid, outcome))

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        if (
            error is not None
            or node.workeroutput.get("ci_suite_collection") != self.descriptor["collection"]
            or node.workeroutput.get("ci_suite_cases") != list(self.expected)
        ):
            raise ValueError("pytest worker failed to prove complete native case collection")
        self.full_collection_verified = True

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.mode == "collect":
            if exitstatus == pytest.ExitCode.OK:
                _write_json_new(Path(os.environ["CI_FLEET_COLLECTION_PATH"]), {"collection": self.collection})
            return
        if hasattr(self.config, "workerinput"):
            if self.full_collection_verified:
                self.config.workeroutput["ci_suite_collection"] = self.descriptor["collection"]
                self.config.workeroutput["ci_suite_cases"] = list(self.expected)
            return
        if exitstatus != pytest.ExitCode.OK:
            return
        if not self.full_collection_verified or tuple(sorted(case for case, _ in self.terminal)) != self.expected:
            raise ValueError("pytest execution lacks exact terminal evidence for every selected native case")
        if not any(outcome in {"passed", "expected-failure"} for _, outcome in self.terminal):
            raise ValueError("pytest shard produced no executable passing native case")
        receipt = make_shard_receipt(self.manifest, self.shard_id, self.units, case_results=dict(self.terminal))
        _write_json_new(Path(os.environ["CI_FLEET_SHARD_RECEIPT_PATH"]), receipt_to_json(receipt))


def pytest_configure(config: pytest.Config) -> None:
    mode = os.environ.get("CI_FLEET_PYTEST_MODE", "")
    if mode not in {"collect", "run"}:
        raise ValueError("strict pytest execution requires collect or run mode")
    config.pluginmanager.register(ExecutionPlugin(config, mode), "strict-suite-execution")
