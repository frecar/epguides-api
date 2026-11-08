"""Merge sealed Vitest coverage from different source checkout directories.

Vitest 4 blob reports use flatted's JSON reference table. Only the documented
blob tuple's File.filepath and Istanbul coverage-map keys/path fields are
rebased. Test names, errors, arbitrary strings and module graphs stay intact.
Unknown coverage source ownership is refused rather than guessed.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .cli import read_json
from .coverage_merge import coverage_evidence
from .invocation import assert_descriptor, source_sha
from .manifest import ShardManifest
from .vitest_cases import _spec_args


def normalize_blob(path: Path, *, producer_root: str, root: Path, tracked: set[Path], expected_version: str) -> bytes:
    table = read_json(str(path))
    if not isinstance(table, list) or not table or not isinstance(table[0], list) or len(table[0]) != 6:
        raise ValueError("Vitest blob has an unsupported reference-table shape")
    report = table[0]

    def reference(value: Any, expected: type) -> Any:
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdecimal()
            or not 0 <= int(value) < len(table)
        ):
            raise ValueError("Vitest blob contains an invalid reference")
        result = table[int(value)]
        if not isinstance(result, expected):
            raise ValueError("Vitest blob reference has an unexpected type")
        return result

    if reference(report[0], str) != expected_version:
        raise ValueError("Vitest blob version differs from the installed merger")
    files, errors, coverage = reference(report[1], list), reference(report[2], list), reference(report[3], dict)
    if errors or not files or not coverage:
        raise ValueError("Vitest coverage blob has errors or no measured source")
    producer = PurePosixPath(producer_root)
    if not producer.is_absolute() or producer.as_posix() != producer_root or producer_root == "/":
        raise ValueError("Vitest coverage producer root is invalid")
    root = root.resolve()
    strings = {value: str(index) for index, value in enumerate(table) if isinstance(value, str)}

    def source_path(value: str) -> str:
        candidate = PurePosixPath(value)
        if not candidate.is_absolute() or candidate.as_posix() != value or ".." in candidate.parts:
            raise ValueError("Vitest coverage path is not canonical absolute source")
        try:
            relative = candidate.relative_to(producer)
        except ValueError as exc:
            raise ValueError("Vitest coverage path is outside its source checkout") from exc
        destination = root / relative.as_posix()
        if destination not in tracked or destination.is_symlink() or not destination.is_file():
            raise ValueError("Vitest coverage path has no identical tracked source in the aggregate checkout")
        return str(destination)

    def string_reference(value: str) -> str:
        if value not in strings:
            strings[value] = str(len(table))
            table.append(value)
        return strings[value]

    rebased = {}
    for original, data_reference in list(coverage.items()):
        if not isinstance(original, str):
            raise ValueError("Vitest coverage map path is malformed")
        destination = source_path(original)
        data = reference(data_reference, dict)
        if reference(data.get("path"), str) != original:
            raise ValueError("Vitest coverage map key and source identity differ")
        if not {"statementMap", "fnMap", "branchMap", "s", "f", "b"}.issubset(data):
            raise ValueError("Vitest blob is not an Istanbul coverage map")
        if destination in rebased:
            raise ValueError("Vitest coverage source aliases collide")
        data["path"] = string_reference(destination)
        rebased[destination] = data_reference
    coverage.clear()
    coverage.update(rebased)
    for file_reference in files:
        file = reference(file_reference, dict)
        file["filepath"] = string_reference(source_path(reference(file.get("filepath"), str)))
    return (json.dumps(table, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def combine_vitest_coverage(
    manifest: ShardManifest, descriptor: dict[str, Any], pairs: list[Path], *, root: Path
) -> None:
    assert_descriptor(manifest, descriptor)
    if manifest.framework != "Vitest-file" or source_sha(root) != manifest.source_sha:
        raise ValueError("Vitest aggregation source/framework differs from its suite")
    # Config bytes stay the consumer's authority. No shard-only zero threshold
    # override is accepted by the aggregate; the fixed full 95% floor applies.
    import hashlib

    for relative, digest in descriptor["command"]["config_files"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("Vitest aggregation configuration changed after collection")
    evidence = coverage_evidence(manifest, descriptor, pairs, kind="vitest-blob")
    package = json.loads((root / "node_modules/vitest/package.json").read_text())
    version = package.get("version")
    if not isinstance(version, str) or not version.startswith("4."):
        raise ValueError("installed Vitest has an unqualified blob format")
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.split("\0")
    tracked = {Path(repository) / relative for relative in listed if relative}
    binary = root / "node_modules/.bin/vitest"
    with tempfile.TemporaryDirectory(prefix="vitest-complete-blobs-") as directory:
        merged = Path(directory)
        for index, (blob, producer) in enumerate(evidence):
            (merged / f"shard-{index}.json").write_bytes(
                normalize_blob(blob, producer_root=producer, root=root, tracked=tracked, expected_version=version)
            )
        spec = {"argv": descriptor["command"]["argv"], "config_files": [], "environment": []}
        command = [
            str(binary),
            *_spec_args(spec),
            "--merge-reports",
            str(merged),
            *([] if "--coverage" in _spec_args(spec) else ["--coverage"]),
            "--coverage.thresholds.lines=95",
            "--coverage.thresholds.functions=95",
            "--coverage.thresholds.branches=95",
            "--coverage.thresholds.statements=95",
        ]
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode != 0:
            raise ValueError("complete Vitest coverage did not satisfy the fixed 95 percent floor")
