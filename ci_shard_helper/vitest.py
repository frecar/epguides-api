"""Vitest file discovery and exact shard execution helpers."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from .manifest import ShardManifest


def _parse_file_list(output: str, *, root: Path) -> tuple[str, ...]:
    root = root.resolve()
    units: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        if line != line.strip() or any(ord(char) < 32 for char in line):
            raise ValueError("Vitest --filesOnly output contains malformed file paths")
        candidate = Path(line)
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("Vitest discovered a file outside the checkout") from exc
        if not resolved.is_file() or PurePosixPath(relative).is_absolute() or relative in {"", "."}:
            raise ValueError("Vitest discovered a missing or invalid test file")
        units.append(relative)
    if not units:
        raise ValueError("Vitest --filesOnly produced an empty test-file universe")
    if len(set(units)) != len(units):
        raise ValueError("Vitest --filesOnly produced duplicate test files")
    return tuple(sorted(units))


def list_vitest_files(
    vitest_bin: str,
    *,
    root: Path,
    vitest_args: Sequence[str] = (),
    file_filters: Sequence[str] = (),
) -> tuple[str, ...]:
    """Ask the installed Vitest binary for its exact current file collection."""
    if not isinstance(vitest_bin, str) or not vitest_bin:
        raise ValueError("vitest_bin must be a nonempty command path")
    if isinstance(vitest_args, (str, bytes)) or any(not isinstance(arg, str) for arg in vitest_args):
        raise ValueError("vitest_args must be a sequence of strings")
    if isinstance(file_filters, (str, bytes)) or any(not isinstance(arg, str) for arg in file_filters):
        raise ValueError("file_filters must be a sequence of strings")
    result = subprocess.run(
        [vitest_bin, "list", "--filesOnly", *vitest_args, *file_filters],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"Vitest file collection failed with exit code {result.returncode}")
    if result.stderr.strip():
        raise ValueError("Vitest --filesOnly wrote unexpected stderr output")
    return _parse_file_list(result.stdout, root=root)


def run_vitest_shard(
    vitest_bin: str,
    *,
    manifest: ShardManifest,
    shard_id: int,
    root: Path,
    vitest_args: Sequence[str],
    observation_path: Path,
    blob_report_path: Path,
) -> tuple[str, ...]:
    """Re-list the selected files, run only them, and require reporter proof."""
    if manifest.framework != "Vitest-file" or manifest.format_version != 2:
        raise ValueError("Vitest execution requires an identity-bound format-2 Vitest-file manifest")
    if type(shard_id) is not int or shard_id < 1 or shard_id > manifest.shard_total:
        raise ValueError("shard_id is outside the manifest")
    selected = manifest.shards[shard_id - 1]
    selected_again = list_vitest_files(
        vitest_bin,
        root=root,
        vitest_args=vitest_args,
        file_filters=selected,
    )
    if selected_again != selected:
        raise ValueError("Vitest file filters selected files outside or missing from this manifest shard")
    if observation_path.exists():
        raise ValueError("Vitest observation output already exists")
    if blob_report_path.exists():
        raise ValueError("Vitest blob report output already exists")
    observation_path.parent.mkdir(parents=True, exist_ok=True)
    blob_report_path.parent.mkdir(parents=True, exist_ok=True)

    reporter = Path(__file__).with_name("vitest_reporter.mjs").resolve()
    environment = dict(os.environ)
    environment["CI_FLEET_VITEST_OBSERVATION_PATH"] = str(observation_path.resolve())
    command = [
        vitest_bin,
        "run",
        *vitest_args,
        *selected,
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
    result = subprocess.run(command, cwd=root, env=environment, check=False)
    if result.returncode != 0:
        raise ValueError(f"Vitest shard failed with exit code {result.returncode}")
    try:
        observed = json.loads(observation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("successful Vitest run did not produce valid reporter observations") from exc
    if not isinstance(observed, list) or any(not isinstance(unit, str) for unit in observed):
        raise ValueError("Vitest reporter observations must be a JSON array of file paths")
    if tuple(observed) != selected:
        raise ValueError("Vitest reporter observations differ from this manifest shard")
    if not blob_report_path.is_file():
        raise ValueError("successful Vitest shard did not produce its unique blob report")
    return tuple(observed)
