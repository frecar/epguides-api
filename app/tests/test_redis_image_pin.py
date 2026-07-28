"""Regression test: every Redis image reference stays pinned + at the CVE-fixed floor.

A floating major-version tag (``redis:7`` / ``redis:7-alpine``) is repointed by
upstream on every release within the 7.x line — a fresh pull can silently move
past (or, via any registry content change, drift off) whatever build was
audited, with zero record of which bytes actually ran. Redis's July 2026
patch round (``6.2.23``, ``7.2.15``, ``7.4.10``, ``8.2.8``, ``8.4.5``,
``8.6.5``, ``8.8.1``) fixed a set of post-auth memory-safety CVEs; ``7.4.10``
is the fixed release for this repo's 7.4 line. ``7.4.9`` was itself a named
vulnerable stock build (Streams shared-NACK use-after-free) targeted by public
authenticated RCE proofs of concept.

This test enforces two invariants across every place this repo declares a
Redis image (``docker-compose.yml``, ``docker-compose.prod.yml``, and the CI
workflow's ``redis`` service container):

  * the image is pinned to an exact ``tag@sha256:<64hex>`` — never a bare/
    floating tag, so the digest is reproducible and tamper-evident; and
  * the pinned version is ``>= 7.4.10`` (the CVE-2026 fixed floor) — so a
    future edit can't silently regress to a pre-fix build.

A future major-line bump (e.g. redis 8.x) only needs ``MIN_REDIS_VERSION``
raised here.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]

MIN_REDIS_VERSION = (7, 4, 10)

# name:tag@sha256:<64hex> — both a human-reviewable tag AND an immutable digest.
_PINNED_RE = re.compile(r"^[^@\s:]+:[^@\s]+@sha256:[0-9a-f]{64}$")


def _parse_redis_version(image: str) -> tuple[int, int, int] | None:
    # Strip the @sha256:<digest> pin before extracting the tag, otherwise a
    # naive rsplit(":") would grab the digest hex instead of the version.
    ref = image.rsplit("@", maxsplit=1)[0]
    tag = ref.rsplit(":", maxsplit=1)[-1]
    version = tag.split("-", maxsplit=1)[0]
    parts = version.split(".")
    if len(parts) < 3 or not all(part.isdigit() for part in parts[:3]):
        return None
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _compose_redis_image(compose_path: Path) -> str:
    compose = yaml.safe_load(compose_path.read_text()) or {}
    service = (compose.get("services") or {}).get("redis") or {}
    image = service.get("image")
    assert image, f"{compose_path}: expected a top-level 'redis' service with an image"
    return str(image)


def _ci_workflow_redis_image() -> str:
    workflow_path = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text()) or {}
    jobs = workflow.get("jobs") or {}
    test_job = jobs.get("test") or {}
    services = test_job.get("services") or {}
    redis_service = services.get("redis") or {}
    image = redis_service.get("image")
    assert image, f"{workflow_path}: expected jobs.test.services.redis.image"
    return str(image)


def _redis_image_sources() -> list[tuple[str, str]]:
    return [
        ("docker-compose.yml", _compose_redis_image(_REPO_ROOT / "docker-compose.yml")),
        ("docker-compose.prod.yml", _compose_redis_image(_REPO_ROOT / "docker-compose.prod.yml")),
        (".github/workflows/ci.yml (jobs.test.services.redis)", _ci_workflow_redis_image()),
    ]


def test_redis_images_are_digest_pinned() -> None:
    sources = _redis_image_sources()
    assert sources

    failures = [
        f"{location}: {image!r} is not pinned as name:tag@sha256:<64hex>"
        for location, image in sources
        if not _PINNED_RE.match(image)
    ]
    assert not failures, "Redis images must carry both a tag and a @sha256: digest:\n" + "\n".join(failures)


def test_redis_images_are_at_or_above_the_cve_2026_fixed_floor() -> None:
    """CVE-2026 fixed 7.x floor is 7.4.10 — see the module docstring for the CVE list."""
    sources = _redis_image_sources()
    assert sources

    failures = []
    for location, image in sources:
        version = _parse_redis_version(image)
        if version is None or version < MIN_REDIS_VERSION:
            failures.append(f"{location}: {image!r}")

    assert not failures, f"Redis images must be pinned to {'.'.join(map(str, MIN_REDIS_VERSION))}+:\n" + "\n".join(
        failures
    )
