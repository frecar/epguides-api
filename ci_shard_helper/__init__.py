"""Public-safe, self-contained CI test-sharding primitives.

This package is generated into consumer repositories. Keep it independent of
the fleet controller, repository catalog, and any estate-specific config.
"""

from .manifest import (
    FRAMEWORK_KINDS,
    ShardManifest,
    ShardReceipt,
    assign_files_to_shards,
    build_shard_manifest,
    command_config_digest,
    make_shard_receipt,
    validate_manifest,
    verify_aggregate,
)

__all__ = [
    "FRAMEWORK_KINDS",
    "ShardManifest",
    "ShardReceipt",
    "assign_files_to_shards",
    "build_shard_manifest",
    "command_config_digest",
    "make_shard_receipt",
    "validate_manifest",
    "verify_aggregate",
]
