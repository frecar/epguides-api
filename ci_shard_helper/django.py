"""Native Django runner mixin; preserve the consumer's configured runner base.

Only the consumer entry point imports Django. This core can be tested with the
standard unittest runner and does not add a runtime dependency to other suites.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

from .cli import read_manifest, receipt_to_json
from .django_run import django_arguments
from .invocation import assert_suite_runtime, expected_cases, read_descriptor
from .manifest import make_shard_receipt
from .source import TrackedSources


def _cases(suite: Any) -> list[unittest.TestCase]:
    if isinstance(suite, unittest.TestCase):
        if isinstance(suite, unittest.loader._FailedTest):
            raise ValueError("Django collection contains a failed test import")
        return [suite]
    return [case for child in suite for case in _cases(child)]


def _write_new(path: str, payload: Any) -> None:
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2)
        stream.write("\n")


class ShardRunnerMixin:
    """Add collection and observed successful execution to an existing runner.

    Outer shards each own their database/services. Inner Django parallelism is
    explicitly refused until its remote result observation is qualified; it is
    never silently disabled. Existing base runner result hooks remain active.
    """

    def run_tests(self, test_labels: Any, **kwargs: Any) -> int:
        self._fleet_mode = os.environ.get("CI_FLEET_DJANGO_MODE", "")
        if self._fleet_mode not in {"collect", "run"}:
            raise ValueError("CI_FLEET_DJANGO_MODE must be collect or run")
        if getattr(self, "parallel", 1) != 1:
            raise ValueError("native Django shard receipts require --parallel=1")
        self._fleet_started: list[str] = []
        self._fleet_terminal: dict[str, str] = {}
        self._fleet_skip_groups: dict[str, list[str]] = {}
        self._fleet_selected: tuple[str, ...] = ()
        if self._fleet_mode == "collect":
            self.setup_test_environment()  # type: ignore[attr-defined]
            try:
                self.build_suite(test_labels, **kwargs)
                output = os.environ.get("CI_FLEET_COLLECTION_PATH", "")
                if not output:
                    raise ValueError("CI_FLEET_COLLECTION_PATH is required")
                _write_new(output, {"collection": self._fleet_collection})
            finally:
                self.teardown_test_environment()  # type: ignore[attr-defined]
            return 0
        self._fleet_manifest = read_manifest(os.environ.get("CI_FLEET_MANIFEST_PATH", ""))
        if self._fleet_manifest.framework != "Django-label":
            raise ValueError("native Django execution requires a Django-label manifest")
        try:
            shard_id = int(os.environ.get("SHARD_ID", ""))
        except ValueError as exc:
            raise ValueError("SHARD_ID must identify a manifest shard") from exc
        self._fleet_descriptor = read_descriptor(os.environ.get("CI_FLEET_SUITE_DESCRIPTOR_PATH", ""))
        assert_suite_runtime(self._fleet_manifest, self._fleet_descriptor, shard_id, root=Path.cwd())
        if list(sys.argv) != django_arguments(self._fleet_descriptor["command"]):
            raise ValueError("actual Django invocation differs from the source-bound descriptor")
        self._fleet_expected = self._fleet_manifest.shards[shard_id - 1]
        output = os.environ.get("CI_FLEET_SHARD_RECEIPT_PATH", "")
        if not output or Path(output).exists():
            raise ValueError("a new CI_FLEET_SHARD_RECEIPT_PATH is required")
        failures = super().run_tests(test_labels, **kwargs)  # type: ignore[misc]
        if failures:
            return failures
        if tuple(sorted(self._fleet_terminal)) != expected_cases(
            self._fleet_manifest, self._fleet_descriptor, shard_id
        ):
            raise ValueError("Django executed tests differ from the manifest shard")
        if not any(outcome in {"passed", "expected-failure"} for outcome in self._fleet_terminal.values()):
            raise ValueError("Django shard produced no executable passing native case")
        receipt = make_shard_receipt(
            self._fleet_manifest, shard_id, self._fleet_selected, case_results=self._fleet_terminal
        )
        _write_new(output, receipt_to_json(receipt))
        return 0

    def build_suite(self, test_labels: Any = None, **kwargs: Any) -> Any:
        suite = super().build_suite(test_labels, **kwargs)  # type: ignore[misc]
        cases = _cases(suite)
        owned = TrackedSources(Path.cwd())
        for case in cases:
            source = inspect.getsourcefile(type(case))
            if source is None:
                raise ValueError("Django collected a test case outside the checked-out source")
            owned.require(Path(source))
        identifiers = [case.id() for case in cases]
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("Django collection is empty or contains duplicate test identities")
        self._fleet_collection = {
            case.id(): {
                "cases": [case.id()],
                "skipped": False,
                "case_modes": {
                    case.id(): "skip"
                    if getattr(type(case), "__unittest_skip__", False)
                    or getattr(getattr(case, case._testMethodName), "__unittest_skip__", False)
                    else "run"
                },
            }
            for case in cases
        }
        if self._fleet_mode == "collect":
            self._fleet_selected = tuple(sorted(identifiers))
            return suite
        if self._fleet_collection != self._fleet_descriptor["collection"]:
            raise ValueError("Django collection differs from the complete manifest universe")
        selected = [case for case in cases if case.id() in self._fleet_expected]
        self._fleet_selected = tuple(sorted(case.id() for case in selected))
        for case in selected:
            for label in (
                f"setUpClass ({type(case).__module__}.{type(case).__qualname__})",
                f"setUpModule ({type(case).__module__})",
            ):
                self._fleet_skip_groups.setdefault(label, []).append(case.id())
        return self.test_suite(selected)  # type: ignore[attr-defined]

    def get_resultclass(self) -> Any:
        base = super().get_resultclass() or self.test_runner.resultclass  # type: ignore[misc,attr-defined]
        observed = self._fleet_started
        terminal, skip_groups = self._fleet_terminal, self._fleet_skip_groups

        class RecordingResult(base):  # type: ignore[misc,valid-type]
            def startTest(self, test: unittest.TestCase) -> None:
                observed.append(test.id())
                super().startTest(test)

            def addSuccess(self, test: unittest.TestCase) -> None:
                terminal[test.id()] = "passed"
                super().addSuccess(test)

            def addExpectedFailure(self, test: unittest.TestCase, err: Any) -> None:
                terminal[test.id()] = "expected-failure"
                super().addExpectedFailure(test, err)

            def addSkip(self, test: unittest.TestCase, reason: str) -> None:
                identifiers = skip_groups.get(test.id(), [test.id()])
                for identifier in identifiers:
                    terminal[identifier] = "skipped"
                super().addSkip(test, reason)

        return RecordingResult
