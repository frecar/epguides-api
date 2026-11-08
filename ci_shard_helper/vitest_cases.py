"""Source-bound native-case collection and execution for Vitest shards."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .manifest import ShardManifest


def _spec_args(spec: Mapping[str, Any]) -> tuple[str, ...]:
    if not isinstance(spec, Mapping) or set(spec) != {"argv", "config_files", "environment"}:
        raise ValueError("Vitest spec requires exactly argv/config_files/environment")
    argv = spec["argv"]
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError("Vitest argv must be a nonempty string array")
    if argv[0] != "vitest":
        raise ValueError("Vitest logical argv must start with 'vitest'")
    if isinstance(spec["config_files"], (str, bytes)) or not isinstance(spec["config_files"], list):
        raise ValueError("Vitest config_files must be a string array")
    if any(not isinstance(value, str) for value in spec["config_files"]):
        raise ValueError("Vitest config_files must be a string array")
    if isinstance(spec["environment"], (str, bytes)) or not isinstance(spec["environment"], list):
        raise ValueError("Vitest environment must be a string array")
    if any(not isinstance(value, str) for value in spec["environment"]):
        raise ValueError("Vitest environment must be a string array")
    args = argv[1:]
    return tuple(args[1:] if args and args[0] == "run" else args)


def _vitest_bin(root: Path, override: str | None) -> str:
    if override is not None:
        if not isinstance(override, str) or not override:
            raise ValueError("vitest_bin override must be a nonempty command path")
        return override
    candidate = root.resolve() / "node_modules" / ".bin" / "vitest"
    if not candidate.is_file():
        raise ValueError("installed Vitest binary was not found in the consumer checkout")
    return str(candidate)


def _clean_unit(unit: str, *, root: Path) -> str:
    if not isinstance(unit, str) or not unit or "\\" in unit or any(ord(char) < 32 for char in unit):
        raise ValueError("Vitest returned a malformed relative module identity")
    path = PurePosixPath(unit)
    if path.is_absolute() or path.as_posix() != unit or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Vitest returned a non-normalized relative module identity")
    resolved = (root / Path(*path.parts)).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Vitest discovered a module outside the checkout") from exc
    if not resolved.is_file():
        raise ValueError("Vitest discovered a missing module")
    return unit


def _validate_collection(value: Any, *, root: Path) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("Vitest native collection is empty or malformed")
    result: dict[str, dict[str, Any]] = {}
    all_ids: set[str] = set()
    for raw_unit, entry in value.items():
        unit = _clean_unit(raw_unit, root=root)
        if unit in result or not isinstance(entry, dict) or set(entry) != {"cases", "case_modes", "skipped"}:
            raise ValueError("Vitest native collection entry is malformed")
        cases = entry["cases"]
        modes = entry["case_modes"]
        if (
            not isinstance(cases, list)
            or any(not isinstance(case, str) for case in cases)
            or cases != sorted(set(cases))
            or not isinstance(modes, dict)
            or set(modes) != set(cases)
            or type(entry["skipped"]) is not bool
            or any(not isinstance(mode, str) or mode not in {"run", "only", "skip", "todo"} for mode in modes.values())
        ):
            raise ValueError("Vitest case IDs, modes, or skipped marker are malformed")
        for case in cases:
            try:
                parsed = json.loads(case)
            except json.JSONDecodeError as exc:
                raise ValueError("Vitest canonical case ID is not JSON") from exc
            if (
                not isinstance(parsed, list)
                or len(parsed) != 3
                or any(not isinstance(part, str) for part in parsed)
                or not parsed[1]
                or not parsed[2]
                or parsed[1] != unit
                or json.dumps(parsed, ensure_ascii=False, separators=(",", ":")) != case
            ):
                raise ValueError("Vitest canonical case ID is not a normalized project/module/native-ID tuple")
            if case in all_ids:
                raise ValueError("Vitest canonical case ID appears more than once")
            all_ids.add(case)
        result[unit] = {"cases": cases, "case_modes": modes, "skipped": entry["skipped"]}
    return dict(sorted(result.items()))


def _collect(spec: Mapping[str, Any], *, root: Path, file_filters: Sequence[str] = ()) -> dict[str, dict[str, Any]]:
    root = root.resolve()
    args = _spec_args(spec)
    if isinstance(file_filters, (str, bytes)) or any(not isinstance(value, str) for value in file_filters):
        raise ValueError("Vitest file filters must be a string array")
    helper = Path(__file__).with_name("vitest_collect.mjs").resolve()
    result = subprocess.run(
        ["node", str(helper), str(root), *args, *file_filters],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"Vitest native collection failed with exit code {result.returncode}: {result.stderr.strip()}")
    if result.stderr.strip():
        raise ValueError("Vitest native collector wrote unexpected stderr output")
    try:
        collected = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Vitest native collector did not return JSON") from exc
    return _validate_collection(collected, root=root)


def collect_vitest_cases(
    spec: Mapping[str, Any], *, root: Path, vitest_bin: str | None = None
) -> dict[str, dict[str, Any]]:
    """Collect every module and case using the consumer checkout's installed Vitest."""
    _vitest_bin(root, vitest_bin)  # Ensure discovery and execution resolve the same consumer installation.
    return _collect(spec, root=root)


def _selected_collection(
    manifest: ShardManifest, descriptor: dict[str, Any], shard_id: int
) -> dict[str, dict[str, Any]]:
    from .invocation import expected_cases

    expected_cases(manifest, descriptor, shard_id)
    return {unit: descriptor["collection"][unit] for unit in manifest.shards[shard_id - 1]}


def run_vitest_cases(
    manifest: ShardManifest,
    descriptor: dict[str, Any],
    *,
    root: Path,
    shard_id: int,
    observation_path: Path,
    blob_report_path: Path,
    vitest_bin: str | None = None,
) -> dict[str, Any]:
    """Rediscover the bound suite, run assigned files, and require native case proof."""
    from .invocation import assert_suite_runtime

    root = root.resolve()
    assert_suite_runtime(manifest, descriptor, shard_id, root=root)
    if manifest.framework != "Vitest-file":
        raise ValueError("Vitest case execution requires a Vitest-file manifest")
    binary = _vitest_bin(root, vitest_bin)
    command = descriptor["command"]["argv"]
    spec = {
        "argv": command,
        "config_files": list(descriptor["command"]["config_files"]),
        "environment": list(descriptor["command"]["environment"]),
    }
    full = collect_vitest_cases(spec, root=root, vitest_bin=binary)
    if full != descriptor["collection"]:
        raise ValueError("Vitest full native collection changed after descriptor construction")
    selected_units = tuple(manifest.shards[shard_id - 1])
    selected = _selected_collection(manifest, descriptor, shard_id)
    if any(not selected[unit]["cases"] for unit in selected_units):
        raise ValueError("Vitest shard contains a zero-case module that cannot complete a native run")
    selected_again = _collect(spec, root=root, file_filters=selected_units)
    if selected_again != selected:
        raise ValueError("Vitest file filters selected modules/cases outside or missing from this manifest shard")
    if any(path.exists() or path.is_symlink() for path in (observation_path, blob_report_path)):
        raise ValueError("Vitest observation or blob output already exists")
    observation_path.parent.mkdir(parents=True, exist_ok=True)
    blob_report_path.parent.mkdir(parents=True, exist_ok=True)

    reporter = Path(__file__).with_name("vitest_case_reporter.mjs").resolve()
    with tempfile.TemporaryDirectory(prefix="ci-vitest-cases-") as temporary:
        expected_path = Path(temporary) / "expected.json"
        expected_cases = sorted(case for entry in selected.values() for case in entry["cases"])
        expected_modes = {case: entry["case_modes"][case] for entry in selected.values() for case in entry["cases"]}
        expected_path.write_text(json.dumps({"cases": expected_cases, "case_modes": expected_modes}), encoding="utf-8")
        environment = dict(os.environ)
        environment["CI_FLEET_VITEST_CASE_OBSERVATION_PATH"] = str(observation_path.resolve())
        environment["CI_FLEET_VITEST_CASE_EXPECTED_PATH"] = str(expected_path)
        environment["CI_FLEET_VITEST_CASE_ROOT"] = str(root)
        args = _spec_args(spec)
        command_line = [
            binary,
            "run",
            *args,
            *selected_units,
            "--coverage.thresholds.lines=0",
            "--coverage.thresholds.functions=0",
            "--coverage.thresholds.branches=0",
            "--coverage.thresholds.statements=0",
            "--coverage.thresholds.perFile=false",
            "--reporter=default",
            "--reporter=github-actions",
            "--reporter=blob",
            f"--outputFile.blob={blob_report_path.resolve()}",
            f"--reporter={reporter}",
        ]
        result = subprocess.run(command_line, cwd=root, env=environment, check=False)
    if result.returncode != 0:
        raise ValueError(f"Vitest case shard failed with exit code {result.returncode}")
    try:
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("successful Vitest run did not produce valid native case observations") from exc
    if not isinstance(observation, dict) or set(observation) != {"case_results"}:
        raise ValueError("Vitest case reporter observation is malformed")
    outcomes = observation["case_results"]
    if not isinstance(outcomes, dict) or set(outcomes) != set(expected_cases):
        raise ValueError("Vitest case reporter did not observe every assigned native case")
    if any(value not in {"passed", "skipped", "expected-failure"} for value in outcomes.values()):
        raise ValueError("Vitest case reporter returned an invalid terminal outcome")
    for case, mode in expected_modes.items():
        if mode in {"skip", "todo"} and outcomes[case] != "skipped":
            raise ValueError("Vitest skipped/todo case did not report an intentional skipped outcome")
        if mode in {"run", "only"} and outcomes[case] not in {"passed", "expected-failure"}:
            raise ValueError("Vitest executable case did not report a successful outcome")
    if not any(value in {"passed", "expected-failure"} for value in outcomes.values()):
        raise ValueError("Vitest shard completed no passing or expected-failure case")
    if not blob_report_path.is_file():
        raise ValueError("successful Vitest shard did not produce its unique blob report")
    return {"collection": selected, "case_results": outcomes}
