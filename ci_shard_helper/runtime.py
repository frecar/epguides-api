"""Common format-2 execution identity checks for every framework adapter."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .manifest import ShardManifest, validate_manifest


def assert_runtime_identity(manifest: ShardManifest, shard_id: int, *, root: Path) -> None:
    validate_manifest(manifest)
    if manifest.format_version != 2 or type(shard_id) is not int or not 1 <= shard_id <= manifest.shard_total:
        raise ValueError("execution requires a format-2 manifest and valid shard identity")
    expected = {
        "CI_FLEET_REPOSITORY_ID": str(manifest.repository_id),
        "GITHUB_REPOSITORY": str(manifest.repository),
        "CI_FLEET_CAPABILITY": str(manifest.capability),
        "CI_FLEET_SUITE": str(manifest.suite),
        "CI_FLEET_COMMAND_CONFIG_SHA256": str(manifest.command_config_sha256),
        "CI_FLEET_MANIFEST_DIGEST": manifest.digest,
        "CI_FLEET_MANIFEST_SOURCE_SHA": manifest.source_sha,
        "SHARD_ID": str(shard_id),
        "SHARD_TOTAL": str(manifest.shard_total),
    }
    for name, wanted in expected.items():
        actual = os.environ.get(name, "")
        if name == "GITHUB_REPOSITORY":
            actual, wanted = actual.casefold(), wanted.casefold()
        if actual != wanted:
            raise ValueError(f"runtime {name} identity differs from the source-bound manifest")
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True)
    if result.stdout.strip() != manifest.source_sha:
        raise ValueError("checked-out source SHA differs from the manifest")
