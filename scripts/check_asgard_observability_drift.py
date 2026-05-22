#!/usr/bin/env python3
"""Compare vendored asgard_observability/ against asgard sibling checkout.

The shared observability module lives canonically in `frecar/asgard` at
`asgard_observability/` (see asgard#588). This repo vendors a copy at
`asgard_observability/` (top-level). This script flags drift between the
two copies, so a developer with both checkouts can spot when the canonical
copy has moved ahead of the vendored one.

Usage:
    python scripts/check_asgard_observability_drift.py            # report
    python scripts/check_asgard_observability_drift.py --update   # resync

Exit codes:
    0 — no drift (or --update succeeded)
    1 — drift detected
    2 — asgard checkout not found (skipped, not an error)

CI does NOT run this script (CI doesn't have asgard checked out). It's
operator-side hygiene + a pre-merge sanity check.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDORED_DIR = REPO_ROOT / "asgard_observability"
DEFAULT_ASGARD_DIR = Path.home() / "code" / "asgard" / "asgard_observability"

# Files that are llm-router-local additions, NOT part of the upstream copy.
# Skip these when comparing.
LOCAL_ONLY: frozenset[str] = frozenset({"VENDORED.md"})

# Top-level subdirectories under the vendored module that are llm-router-local
# (tests live in `asgard_observability/tests/` here because pytest discovery is
# scoped per-package; asgard ships them at the repo's top-level tests/ dir
# under a different filename so the path can't be reused as-is).
LOCAL_ONLY_DIRS: frozenset[str] = frozenset({"tests"})

# Top-level entries to skip on BOTH sides (cache dirs, etc.).
SKIP_NAMES: frozenset[str] = frozenset({"__pycache__"})


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_files(root: Path) -> dict[str, Path]:
    """Map of relative-path-string → absolute Path, skipping caches + dirs."""
    out: dict[str, Path] = {}
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        parts = entry.relative_to(root).parts
        if any(part in SKIP_NAMES for part in parts):
            continue
        if parts and parts[0] in LOCAL_ONLY_DIRS:
            continue
        rel = entry.relative_to(root).as_posix()
        if rel in LOCAL_ONLY:
            continue
        out[rel] = entry
    return out


def _diff(vendored_files: dict[str, Path], canonical_files: dict[str, Path]) -> list[str]:
    """Return list of human-readable drift messages (empty == no drift)."""
    msgs: list[str] = []
    vendored_keys = set(vendored_files)
    canonical_keys = set(canonical_files)

    for missing in sorted(canonical_keys - vendored_keys):
        msgs.append(f"  - MISSING in vendored copy:  {missing}")
    for extra in sorted(vendored_keys - canonical_keys):
        msgs.append(f"  - EXTRA in vendored copy:    {extra}")
    for shared in sorted(vendored_keys & canonical_keys):
        v_hash = _hash_file(vendored_files[shared])
        c_hash = _hash_file(canonical_files[shared])
        if v_hash != c_hash:
            msgs.append(f"  - CONTENT DIFFERS:           {shared}")
    return msgs


def _update(vendored_root: Path, canonical_root: Path) -> None:
    """Resync vendored_root from canonical_root.

    Preserves both top-level LOCAL_ONLY files (e.g. VENDORED.md) and entire
    LOCAL_ONLY_DIRS subtrees (e.g. tests/) so a resync doesn't blow them away.
    """
    preserved_files: dict[str, bytes] = {}
    for rel in LOCAL_ONLY:
        path = vendored_root / rel
        if path.exists():
            preserved_files[rel] = path.read_bytes()
    preserved_dirs: dict[str, Path] = {}
    tmp_root = vendored_root.parent / f".{vendored_root.name}.preserved-tmp"
    for sub in LOCAL_ONLY_DIRS:
        src = vendored_root / sub
        if src.is_dir():
            dst = tmp_root / sub
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
            preserved_dirs[sub] = dst

    # Wipe + recopy. shutil.copytree refuses to merge into an existing dir.
    shutil.rmtree(vendored_root)
    shutil.copytree(canonical_root, vendored_root, ignore=shutil.ignore_patterns(*SKIP_NAMES))

    for rel, blob in preserved_files.items():
        (vendored_root / rel).write_bytes(blob)
    for sub, tmpdir in preserved_dirs.items():
        shutil.copytree(tmpdir, vendored_root / sub)
    if tmp_root.exists():
        shutil.rmtree(tmp_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--asgard-dir",
        type=Path,
        default=DEFAULT_ASGARD_DIR,
        help=f"Path to asgard's asgard_observability/ (default: {DEFAULT_ASGARD_DIR})",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Resync vendored copy from asgard (preserves VENDORED.md).",
    )
    args = parser.parse_args()

    if not args.asgard_dir.is_dir():
        print(
            f"asgard checkout not found at {args.asgard_dir}; skipping drift check.",
            file=sys.stderr,
        )
        return 2

    if not VENDORED_DIR.is_dir():
        print(
            f"vendored copy not found at {VENDORED_DIR}; something is broken.",
            file=sys.stderr,
        )
        return 1

    if args.update:
        _update(VENDORED_DIR, args.asgard_dir)
        print(f"Resynced {VENDORED_DIR} from {args.asgard_dir}.")
        print("Remember to update VENDORED.md with the new source commit SHA.")
        return 0

    vendored_files = _list_files(VENDORED_DIR)
    canonical_files = _list_files(args.asgard_dir)
    drift = _diff(vendored_files, canonical_files)

    if not drift:
        print(f"No drift between {VENDORED_DIR} and {args.asgard_dir}.")
        return 0

    print(f"Drift detected between vendored copy and {args.asgard_dir}:")
    for msg in drift:
        print(msg)
    print()
    print("Resync with:  python scripts/check_asgard_observability_drift.py --update")
    return 1


if __name__ == "__main__":
    sys.exit(main())
