"""Portable deterministic manifests and exact completion receipts.

The module has no repository, runner, credential, or controller dependency so
the source bundle can be copied into public and private consumer repositories.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

FRAMEWORK_KINDS = frozenset({"pytest-file", "Django-label", "Vitest-file", "shell-file"})
_SOURCE_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CAPABILITY = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_SUITE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def assign_files_to_shards(costs: Mapping[str, int], shard_total: int) -> dict[str, int]:
    """Deterministic LPT assignment; estimates affect placement only."""
    _positive_int(shard_total, "shard_total")
    loads = [0] * shard_total
    assignment: dict[str, int] = {}
    for name in sorted(costs, key=lambda item: (-costs[item], item)):
        if type(costs[name]) is not int or costs[name] < 1:
            raise ValueError(f"cost for {name!r} must be a positive integer")
        slot = loads.index(min(loads))
        assignment[name] = slot + 1
        loads[slot] += costs[name]
    return assignment


def _normalize_unit(kind: str, unit: str) -> str:
    if not isinstance(unit, str):
        raise ValueError(f"test units must be strings, got {type(unit).__name__}")
    normalized = unicodedata.normalize("NFC", unit)
    if not normalized or normalized != normalized.strip() or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"invalid test unit: {unit!r}")
    if kind == "Django-label":
        return normalized
    if "\\" in normalized:
        raise ValueError(f"file test units must use normalized POSIX paths: {unit!r}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"file test units must be relative normalized paths: {unit!r}")
    canonical = path.as_posix()
    if canonical in {"", "."}:
        raise ValueError(f"invalid file test unit: {unit!r}")
    return canonical


def _unit_universe(kind: str, units: Iterable[str]) -> tuple[str, ...]:
    if not isinstance(kind, str) or kind not in FRAMEWORK_KINDS:
        raise ValueError(f"unsupported framework kind: {kind!r}")
    if isinstance(units, (str, bytes)):
        raise ValueError("units must be an iterable of complete test-unit identifiers")
    normalized = tuple(_normalize_unit(kind, unit) for unit in units)
    if not normalized:
        raise ValueError("test-unit universe must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("test-unit universe contains duplicate normalized units")
    return tuple(sorted(normalized))


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def command_config_payload(
    argv: Sequence[str],
    *,
    root: Path,
    config_files: Iterable[str] = (),
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Canonical command, selected file hashes, and relevant environment inputs."""
    if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError("argv must be a nonempty sequence of strings")
    root_path = root.resolve()
    raw_config_files = tuple(config_files)
    files: dict[str, str] = {}
    for raw_path in raw_config_files:
        relative = _normalize_unit("pytest-file", raw_path)
        path = root_path / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"command config must be an existing regular file: {relative}")
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(files) != len(raw_config_files):
        raise ValueError("command config file list contains duplicates")
    payload = {
        "format": 1,
        "argv": list(argv),
        "config_files": files,
        "environment": dict(sorted((environment or {}).items())),
    }
    return payload


def command_config_digest(
    argv: Sequence[str], *, root: Path, config_files: Iterable[str] = (), environment: Mapping[str, str] | None = None
) -> str:
    return hashlib.sha256(
        _canonical_json(command_config_payload(argv, root=root, config_files=config_files, environment=environment))
    ).hexdigest()


@dataclass(frozen=True)
class ShardManifest:
    """Immutable assignment. Format 1 remains readable during migration."""

    source_sha: str
    framework: str
    units: tuple[str, ...]
    shards: tuple[tuple[str, ...], ...]
    digest: str
    format_version: int = 1
    repository_id: int | None = None
    repository: str | None = None
    capability: str | None = None
    suite: str | None = None
    command_config_sha256: str | None = None

    @property
    def shard_total(self) -> int:
        return len(self.shards)

    def _payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "format": self.format_version,
            "source_sha": self.source_sha,
            "framework": self.framework,
            "shard_total": self.shard_total,
            "units": list(self.units),
            "shards": [list(shard) for shard in self.shards],
        }
        if self.format_version == 2:
            payload.update(
                repository_id=self.repository_id,
                repository=self.repository,
                capability=self.capability,
                suite=self.suite,
                command_config_sha256=self.command_config_sha256,
            )
        return payload

    def computed_digest(self) -> str:
        return hashlib.sha256(_canonical_json(self._payload())).hexdigest()


@dataclass(frozen=True)
class ShardReceipt:
    """A successful job's exact completion claim for one immutable manifest."""

    manifest_digest: str
    source_sha: str
    shard_id: int
    completed_units: tuple[str, ...]
    format_version: int = 1
    repository_id: int | None = None
    repository: str | None = None
    capability: str | None = None
    suite: str | None = None
    command_config_sha256: str | None = None
    status: str = "success"
    case_results: tuple[tuple[str, str], ...] | None = None

    @property
    def completed_cases(self) -> tuple[str, ...] | None:
        return tuple(case for case, _ in self.case_results) if self.case_results is not None else None

    def __post_init__(self) -> None:
        if not isinstance(self.completed_units, tuple):
            object.__setattr__(self, "completed_units", tuple(self.completed_units))


def build_shard_manifest(
    *,
    source_sha: str,
    framework: str,
    units: Iterable[str],
    shard_total: int,
    costs: Mapping[str, int] | None = None,
    repository_id: int | None = None,
    repository: str | None = None,
    capability: str | None = None,
    suite: str | None = None,
    command_config_sha256: str | None = None,
) -> ShardManifest:
    """Build a canonical partition from the caller's complete collected units.

    Omitting all identity fields creates a format-1 compatibility manifest.
    New consumers must supply all identity fields and receive format 2.
    """
    _positive_int(shard_total, "shard_total")
    if not isinstance(source_sha, str) or not _SOURCE_SHA.fullmatch(source_sha):
        raise ValueError("source_sha must be a lowercase 40- or 64-character Git object id")
    identity_values = (repository_id, repository, capability, suite, command_config_sha256)
    if all(value is None for value in identity_values):
        format_version = 1
    elif any(value is None for value in identity_values):
        raise ValueError("format 2 requires repository_id, repository, capability, suite, and command_config_sha256")
    else:
        format_version = 2
        _positive_int(repository_id, "repository_id")  # type: ignore[arg-type]
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
            raise ValueError("repository must be a canonical owner/name slug")
        if not isinstance(capability, str) or not _CAPABILITY.fullmatch(capability):
            raise ValueError("capability must be a normalized portable selector")
        if not isinstance(suite, str) or not _SUITE.fullmatch(suite):
            raise ValueError("suite must be a normalized nonempty identifier")
        if not isinstance(command_config_sha256, str) or not _SHA256.fullmatch(command_config_sha256):
            raise ValueError("command_config_sha256 must be a lowercase SHA-256 digest")

    universe = _unit_universe(framework, units)
    if shard_total > len(universe):
        raise ValueError("shard_total exceeds the unit count and would create empty shards")

    if costs is None:
        normalized_costs = dict.fromkeys(universe, 1)
    else:
        normalized_costs: dict[str, int] = {}
        for raw_unit, cost in costs.items():
            unit = _normalize_unit(framework, raw_unit)
            if unit in normalized_costs:
                raise ValueError(f"duplicate normalized cost unit: {unit!r}")
            _positive_int(cost, f"cost for {unit!r}")
            normalized_costs[unit] = cost
        if set(normalized_costs) != set(universe):
            raise ValueError("cost keys must exactly match the complete test-unit universe")

    assignment = assign_files_to_shards(normalized_costs, shard_total)
    shards = tuple(
        tuple(unit for unit in universe if assignment[unit] == shard_id) for shard_id in range(1, shard_total + 1)
    )
    if any(not shard for shard in shards):
        raise ValueError("assignment produced an empty shard")

    draft = ShardManifest(
        source_sha,
        framework,
        universe,
        shards,
        "",
        format_version,
        repository_id if format_version == 2 else None,
        repository if format_version == 2 else None,
        capability if format_version == 2 else None,
        suite if format_version == 2 else None,
        command_config_sha256 if format_version == 2 else None,
    )
    return ShardManifest(
        draft.source_sha,
        draft.framework,
        draft.units,
        draft.shards,
        draft.computed_digest(),
        draft.format_version,
        draft.repository_id,
        draft.repository,
        draft.capability,
        draft.suite,
        draft.command_config_sha256,
    )


def make_shard_receipt(
    manifest: ShardManifest,
    shard_id: int,
    completed_units: Iterable[str],
    *,
    case_results: Mapping[str, str] | None = None,
) -> ShardReceipt:
    validate_manifest(manifest)
    _positive_int(shard_id, "shard_id")
    if shard_id > manifest.shard_total:
        raise ValueError("shard_id is outside the manifest")
    units = tuple(sorted(_normalize_unit(manifest.framework, unit) for unit in completed_units))
    if len(set(units)) != len(units):
        raise ValueError("receipt contains duplicate normalized units")
    cases = tuple(sorted(case_results.items())) if case_results is not None else None
    if cases is not None and any(
        not isinstance(case, str) or not case or outcome not in {"passed", "skipped", "expected-failure"}
        for case, outcome in cases
    ):
        raise ValueError("receipt contains invalid native case outcomes")
    return ShardReceipt(
        manifest.digest,
        manifest.source_sha,
        shard_id,
        units,
        manifest.format_version,
        manifest.repository_id,
        manifest.repository,
        manifest.capability,
        manifest.suite,
        manifest.command_config_sha256,
        "success",
        cases,
    )


def validate_manifest(manifest: ShardManifest) -> None:
    if not isinstance(manifest, ShardManifest):
        raise ValueError("expected a ShardManifest")
    if type(manifest.format_version) is not int or manifest.format_version not in {1, 2}:
        raise ValueError("manifest format must be 1 or 2")
    if not isinstance(manifest.source_sha, str) or not _SOURCE_SHA.fullmatch(manifest.source_sha):
        raise ValueError("manifest source_sha is invalid")
    if manifest.format_version == 1:
        if any(
            value is not None
            for value in (
                manifest.repository_id,
                manifest.repository,
                manifest.capability,
                manifest.suite,
                manifest.command_config_sha256,
            )
        ):
            raise ValueError("format 1 manifest cannot carry format 2 identity fields")
    else:
        _positive_int(manifest.repository_id, "repository_id")  # type: ignore[arg-type]
        if not isinstance(manifest.repository, str) or not _REPOSITORY.fullmatch(manifest.repository):
            raise ValueError("manifest repository is invalid")
        if not isinstance(manifest.capability, str) or not _CAPABILITY.fullmatch(manifest.capability):
            raise ValueError("manifest capability is invalid")
        if not isinstance(manifest.suite, str) or not _SUITE.fullmatch(manifest.suite):
            raise ValueError("manifest suite is invalid")
        if not isinstance(manifest.command_config_sha256, str) or not _SHA256.fullmatch(manifest.command_config_sha256):
            raise ValueError("manifest command_config_sha256 is invalid")
    _positive_int(manifest.shard_total, "manifest shard_total")
    universe = _unit_universe(manifest.framework, manifest.units)
    if universe != manifest.units:
        raise ValueError("manifest unit universe is not canonical")
    if manifest.shard_total > len(universe):
        raise ValueError("manifest contains more shards than test units")
    if len(manifest.shards) != manifest.shard_total or any(not shard for shard in manifest.shards):
        raise ValueError("manifest shards must be nonempty and match shard_total")
    seen: list[str] = []
    for shard in manifest.shards:
        normalized = tuple(_normalize_unit(manifest.framework, unit) for unit in shard)
        if normalized != shard or len(set(normalized)) != len(normalized):
            raise ValueError("manifest shard units must be canonical and unique")
        seen.extend(normalized)
    if len(seen) != len(set(seen)) or set(seen) != set(universe):
        raise ValueError("manifest shards must be a complete disjoint partition of the unit universe")
    if not isinstance(manifest.digest, str) or not _SHA256.fullmatch(manifest.digest):
        raise ValueError("manifest digest is invalid")
    if manifest.digest != manifest.computed_digest():
        raise ValueError("manifest digest does not match its immutable contents")


def verify_aggregate(manifest: ShardManifest, receipts: Iterable[ShardReceipt]) -> None:
    """Require one successful, source- and identity-bound receipt per shard."""
    validate_manifest(manifest)
    if isinstance(receipts, (str, bytes)):
        raise ValueError("receipts must be an iterable of shard receipts")
    received: dict[int, ShardReceipt] = {}
    completed: list[str] = []
    for receipt in receipts:
        if not isinstance(receipt, ShardReceipt):
            raise ValueError("aggregate contains a non-ShardReceipt value")
        _positive_int(receipt.shard_id, "receipt shard_id")
        if receipt.shard_id > manifest.shard_total:
            raise ValueError(f"receipt has foreign shard id {receipt.shard_id}")
        if receipt.status != "success":
            raise ValueError(f"receipt for shard {receipt.shard_id} is not a successful pytest session")
        if receipt.shard_id in received:
            raise ValueError(f"duplicate receipt for shard {receipt.shard_id}")
        identity = (
            receipt.format_version,
            receipt.repository_id,
            receipt.repository,
            receipt.capability,
            receipt.suite,
            receipt.command_config_sha256,
        )
        expected_identity = (
            manifest.format_version,
            manifest.repository_id,
            manifest.repository,
            manifest.capability,
            manifest.suite,
            manifest.command_config_sha256,
        )
        if identity != expected_identity:
            raise ValueError(f"receipt for shard {receipt.shard_id} has foreign repository/capability/suite identity")
        if receipt.manifest_digest != manifest.digest:
            raise ValueError(f"receipt for shard {receipt.shard_id} has a foreign manifest digest")
        if receipt.source_sha != manifest.source_sha:
            raise ValueError(f"receipt for shard {receipt.shard_id} has a foreign source SHA")
        units = tuple(_normalize_unit(manifest.framework, unit) for unit in receipt.completed_units)
        if len(set(units)) != len(units):
            raise ValueError(f"receipt for shard {receipt.shard_id} contains duplicate units")
        expected = manifest.shards[receipt.shard_id - 1]
        if set(units) != set(expected) or len(units) != len(expected):
            raise ValueError(f"receipt for shard {receipt.shard_id} does not exactly match its assigned units")
        received[receipt.shard_id] = receipt
        completed.extend(units)

    expected_shards = set(range(1, manifest.shard_total + 1))
    if set(received) != expected_shards:
        missing = sorted(expected_shards - set(received))
        raise ValueError(f"aggregate is missing shard receipts: {missing}")
    if len(completed) != len(set(completed)) or set(completed) != set(manifest.units):
        raise ValueError("aggregate completion is not an exact partition of the test-unit universe")
