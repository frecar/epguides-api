"""Bind per-shard coverage bytes to native receipts before a full 95% merge."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from .cli import _write_json, read_json, read_receipt
from .invocation import assert_descriptor, descriptor_digest, expected_cases, source_sha, verify_execution_aggregate
from .manifest import ShardManifest
from .source import TrackedSources


def _file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError("coverage evidence must be a nonempty regular file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_python_sources(path: Path, *, root: Path, producer_root: str) -> None:
    from coverage import CoverageData
    from coverage.exceptions import CoverageException

    before = _file_digest(path)
    data = CoverageData(basename=str(path.resolve()))
    try:
        data.read()
        files = data.measured_files()
    except CoverageException as exc:
        raise ValueError("Python coverage data cannot be verified") from exc
    if not files:
        raise ValueError("Python coverage has no measured source")
    owned = TrackedSources(root)
    for filename in files:
        candidate = Path(filename)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(Path(producer_root))
            except ValueError as exc:
                raise ValueError("Python coverage source is outside its producer checkout") from exc
        owned.require(candidate)
    if _file_digest(path) != before:
        raise ValueError("Python coverage changed while validating source ownership")


def seal_coverage(
    manifest: ShardManifest,
    descriptor: dict[str, Any],
    *,
    shard_id: int,
    receipt_path: Path,
    coverage_files: list[Path],
    output: Path,
    kind: str = "python",
    root: Path,
) -> None:
    assert_descriptor(manifest, descriptor)
    if source_sha(root) != manifest.source_sha:
        raise ValueError("coverage producer checkout differs from its source manifest")
    receipt = read_receipt(str(receipt_path))
    if (
        receipt.shard_id != shard_id
        or receipt.manifest_digest != manifest.digest
        or receipt.completed_cases != expected_cases(manifest, descriptor, shard_id)
    ):
        raise ValueError("coverage receipt differs from its native execution")
    if kind not in {"python", "vitest-blob"} or not coverage_files:
        raise ValueError("coverage kind or artifact set is invalid")
    if receipt_path.parent.resolve() != output.parent.resolve() or any(
        path.parent.resolve() != output.parent.resolve() for path in coverage_files
    ):
        raise ValueError("coverage evidence must share one shard artifact directory")
    if len({path.name for path in coverage_files}) != len(coverage_files):
        raise ValueError("coverage evidence contains duplicate artifact paths")
    if kind == "python":
        for path in coverage_files:
            validate_python_sources(path, root=root, producer_root=str(root.resolve()))
    payload = {
        "format": 1,
        "kind": kind,
        "manifest_digest": manifest.digest,
        "descriptor_digest": descriptor_digest(descriptor),
        "source_sha": manifest.source_sha,
        "producer_root": str(root.resolve()),
        "shard_id": shard_id,
        "case_receipt": {"file": receipt_path.name, "sha256": _file_digest(receipt_path)},
        "artifacts": [{"file": path.name, "sha256": _file_digest(path)} for path in coverage_files],
    }
    _write_json(str(output), payload)


def coverage_evidence(
    manifest: ShardManifest, descriptor: dict[str, Any], pairs: list[Path], *, kind: str
) -> list[tuple[Path, str]]:
    assert_descriptor(manifest, descriptor)
    receipts, artifacts, seen = [], [], set()
    for pair in pairs:
        raw = read_json(str(pair))
        fields = {
            "format",
            "kind",
            "manifest_digest",
            "descriptor_digest",
            "source_sha",
            "shard_id",
            "case_receipt",
            "artifacts",
            "producer_root",
        }
        if not isinstance(raw, dict) or set(raw) != fields or type(raw["format"]) is not int or raw["format"] != 1:
            raise ValueError("coverage pair has missing or broadened fields")
        if (raw["kind"], raw["manifest_digest"], raw["descriptor_digest"], raw["source_sha"]) != (
            kind,
            manifest.digest,
            descriptor_digest(descriptor),
            manifest.source_sha,
        ):
            raise ValueError("coverage pair has foreign source/suite/kind identity")
        shard = raw["shard_id"]
        if type(shard) is not int or shard in seen or not 1 <= shard <= manifest.shard_total:
            raise ValueError("coverage pair has duplicate or invalid shard identity")
        seen.add(shard)
        producer = raw["producer_root"]
        if (
            not isinstance(producer, str)
            or not Path(producer).is_absolute()
            or producer in {"/", ""}
            or str(Path(producer)) != producer
        ):
            raise ValueError("coverage producer root is invalid")

        def verified_file(entry: Any, parent: Path = pair.parent) -> Path:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"file", "sha256"}
                or not isinstance(entry["file"], str)
                or Path(entry["file"]).name != entry["file"]
                or entry["file"] in {"", ".", ".."}
            ):
                raise ValueError("coverage pair contains an invalid artifact reference")
            path = parent / entry["file"]
            if _file_digest(path) != entry["sha256"]:
                raise ValueError("coverage artifact differs from the sealed native execution")
            return path

        receipt = read_receipt(str(verified_file(raw["case_receipt"])))
        if receipt.shard_id != shard:
            raise ValueError("coverage pair and case receipt shard identities differ")
        receipts.append(receipt)
        if not isinstance(raw["artifacts"], list) or not raw["artifacts"]:
            raise ValueError("coverage pair has no artifacts")
        paths = [verified_file(entry) for entry in raw["artifacts"]]
        if len({path.resolve() for path in paths}) != len(paths):
            raise ValueError("coverage pair repeats an artifact")
        artifacts.extend((path, producer) for path in paths)
    verify_execution_aggregate(manifest, descriptor, receipts)
    if len({path.resolve() for path, _ in artifacts}) != len(artifacts):
        raise ValueError("coverage artifact path was reused across shards")
    return artifacts


def coverage_inputs(manifest: ShardManifest, descriptor: dict[str, Any], pairs: list[Path], *, kind: str) -> list[Path]:
    return [path for path, _ in coverage_evidence(manifest, descriptor, pairs, kind=kind)]


def combine_python_coverage(
    manifest: ShardManifest, descriptor: dict[str, Any], pairs: list[Path], *, root: Path, output: Path
) -> None:
    if source_sha(root) != manifest.source_sha:
        raise ValueError("coverage aggregation checkout differs from the source manifest")
    # Only the reporter's source config is needed here; test services/env do
    # not need to remain alive after every native shard has completed.
    for relative, digest in descriptor["command"]["config_files"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("coverage aggregation config changed after collection")
    evidence = coverage_evidence(manifest, descriptor, pairs, kind="python")
    for path, producer in evidence:
        validate_python_sources(path, root=root, producer_root=producer)
    files = [path for path, _producer in evidence]
    if output.exists():
        raise ValueError("combined coverage output already exists")
    combined = subprocess.run(
        [sys.executable, "-m", "coverage", "combine", "--keep", "--data-file", str(output.resolve()), *map(str, files)],
        cwd=root,
        check=False,
    )
    if combined.returncode != 0:
        raise ValueError("complete Python coverage combination failed")
    report = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "report",
            "--precision=2",
            "--fail-under=95",
            "--data-file",
            str(output.resolve()),
        ],
        cwd=root,
        check=False,
    )
    if report.returncode != 0:
        raise ValueError("complete Python coverage did not satisfy the fixed 95 percent floor")
