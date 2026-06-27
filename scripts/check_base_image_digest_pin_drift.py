#!/usr/bin/env python3
"""Fail-closed: every external image a Dockerfile pulls is pinned by digest.

A mutable tag (``FROM python:3.14.6-slim``) only adopts whatever digest the
registry serves at build time, so two builds minutes apart can build on
different bytes and a mutated/compromised upstream tag is adopted silently. A
digest pin makes the build reproducible and tamper-evident (the registry cannot
serve different bytes for a fixed ``@sha256:`` without the client detecting the
hash mismatch):

    FROM python:3.14.6-slim@sha256:<64hex>

This guard scans every tracked ``Dockerfile`` / ``Dockerfile.*`` and fails if any
**external** image reference is not of the form ``name:tag@sha256:<64hex>`` — it
must carry BOTH a tag AND a digest:

- the **digest** is the immutable provenance (the reproducibility this exists
  for);
- the **tag** keeps the version human-reviewable AND lets the docker dependency
  updater reason about + bump the pin (a bare ``name@sha256:`` is untracked and
  opaque in review).

It covers two kinds of external reference:

- ``FROM <image>`` — the base image of a build stage;
- ``COPY --from=<image>`` — an external image whose files are copied into the
  build (e.g. a static tool binary). A poisoned tool image is the same
  build-time supply-chain exposure as a poisoned base.

Intentionally NOT flagged (skipped, not failed):

- ``FROM scratch`` — the empty base; there is no upstream image to pin.
- An internal multi-stage reference — ``FROM <stage>`` / ``COPY --from=<stage>``
  where ``<stage>`` was declared by an earlier ``... AS <stage>``, or a stage
  index (``COPY --from=0``). These are local, not external pulls.

The digest must be resolved as the MULTI-ARCH INDEX digest (e.g. via
``docker buildx imagetools inspect <image>:<tag>``), NOT a single-platform
``docker inspect`` digest — a platform digest would fail to pull on a host of a
different architecture.

This guard enforces the SHAPE of a pin (a tag + a 64-hex digest), not the
IDENTITY of the image — pinning to a wrong or hostile digest still passes here
and is caught only by human review + the image vulnerability scan. It is a
drift-stopper, not an allowlist.

Run from the repo root::

    python3 scripts/check_base_image_digest_pin_drift.py

Exit non-zero on any unpinned external reference, or if no Dockerfile is found
(a wiring/path regression must fail loudly, not pass vacuously).

Stdlib-only; parses under Python 3.12 (the host-syntax guard) and 3.14.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Vendored / generated dirs that never host a source-of-truth Dockerfile.
_SKIP_DIR_PARTS = frozenset({".git", "node_modules", ".venv", "__pycache__"})

# A fully-pinned external reference: `name[:port]/path:tag@sha256:<64hex>`.
# `[^@\s]+:[^@\s/]+` requires a tag (a `:`-separated segment with no `/`, so a
# registry `host:port` prefix is not mistaken for the tag) and forbids an
# embedded `@` (so a bare `name@sha256:` with no tag fails).
_PINNED_RE = re.compile(r"^[^@\s]+:[^@\s/]+@sha256:[0-9a-f]{64}$")

# A leading FROM flag (`--platform=...`) to strip before the image token.
_FROM_FLAG_RE = re.compile(r"^--[a-z][a-z0-9-]*=\S+$")

# `COPY --from=<ref>` (also matches `COPY --chown=... --from=<ref>`).
_COPY_FROM_RE = re.compile(r"^\s*COPY\b.*?--from=(\S+)", re.IGNORECASE)


def find_dockerfiles(repo_root: Path) -> list[Path]:
    """Return every tracked ``Dockerfile`` / ``Dockerfile.*`` under ``repo_root``."""
    out: list[Path] = []
    for path in sorted(repo_root.rglob("Dockerfile*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(repo_root)
        except ValueError:  # pragma: no cover - rglob stays under repo_root
            continue
        if any(part in _SKIP_DIR_PARTS for part in rel.parts):
            continue
        name = path.name
        if name == "Dockerfile" or name.startswith("Dockerfile."):
            out.append(path)
    return out


def _parse_from(line: str) -> tuple[str, str | None] | None:
    """Parse a ``FROM`` directive into ``(image_ref, stage_alias)`` or ``None``."""
    tokens = line.strip().split()
    if not tokens or tokens[0].upper() != "FROM":
        return None
    rest = tokens[1:]
    while rest and _FROM_FLAG_RE.match(rest[0]):
        rest = rest[1:]
    if not rest:
        return None
    image_ref = rest[0]
    stage_alias: str | None = None
    if len(rest) >= 3 and rest[1].upper() == "AS":
        stage_alias = rest[2].lower()
    return image_ref, stage_alias


def _is_internal_copy_ref(ref: str, stage_aliases: set[str]) -> bool:
    """A ``COPY --from`` ref that points at an earlier build stage, not an image."""
    return ref.lower() in stage_aliases or ref.isdigit()


def find_unpinned(repo_root: Path) -> list[tuple[Path, int, str]]:
    """Return (path, lineno, raw_line) for every unpinned EXTERNAL image reference."""
    hits: list[tuple[Path, int, str]] = []
    for path in find_dockerfiles(repo_root):
        try:
            text = path.read_bytes().decode("utf-8", errors="ignore")
        except OSError:  # pragma: no cover - is_file() passed but read failed (race/perm)
            continue
        stage_aliases: set[str] = set()
        for lineno, raw in enumerate(text.splitlines(), start=1):
            parsed = _parse_from(raw)
            if parsed is not None:
                image_ref, stage_alias = parsed
                ref_l = image_ref.lower()
                if ref_l != "scratch" and ref_l not in stage_aliases:
                    if not _PINNED_RE.match(image_ref):
                        hits.append((path, lineno, raw.strip()))
                if stage_alias:
                    stage_aliases.add(stage_alias)
                continue
            copy_match = _COPY_FROM_RE.match(raw)
            if copy_match:
                ref = copy_match.group(1)
                if not _is_internal_copy_ref(ref, stage_aliases) and not _PINNED_RE.match(ref):
                    hits.append((path, lineno, raw.strip()))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="Repo checkout root to scan (default: this script's repo).",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    dockerfiles = find_dockerfiles(repo_root)
    if not dockerfiles:
        print(
            "ERROR: no Dockerfile found to check — this guard is wired into a repo "
            "that builds an image, so zero Dockerfiles means a path/wiring regression.",
            file=sys.stderr,
        )
        return 1

    unpinned = find_unpinned(repo_root)
    if unpinned:
        print(
            "ERROR: unpinned external image reference(s) — must be "
            "name:tag@sha256:<64hex> (FROM and COPY --from external images).",
            file=sys.stderr,
        )
        print(
            "       A digest pin makes the build reproducible and tamper-evident.",
            file=sys.stderr,
        )
        print(
            "       Resolve the multi-arch INDEX digest with "
            "`docker buildx imagetools inspect <image>:<tag>` (NOT `docker inspect`).",
            file=sys.stderr,
        )
        for path, lineno, line in unpinned:
            rel = path.relative_to(repo_root).as_posix()
            print(f"  {rel}:{lineno}: {line}", file=sys.stderr)
        return 1

    print(f"OK: all external image references are digest-pinned (tag@sha256) across {len(dockerfiles)} Dockerfile(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
