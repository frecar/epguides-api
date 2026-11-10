#!/usr/bin/env python3
"""Scan isolated local Docker images by immutable ID with Trivy."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_IMAGE_ID_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_SEVERITIES = {"CRITICAL": "1", "HIGH": "0"}
_SCAN_TIMEOUT_SECONDS = 600


def _validated_image_ids(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("image IDs must be a non-empty JSON list")
    unique: list[str] = []
    for image_id in value:
        if not isinstance(image_id, str) or not _IMAGE_ID_RE.fullmatch(image_id):
            raise ValueError("every image ID must be sha256 followed by 64 lowercase hex digits")
        if image_id not in unique:
            unique.append(image_id)
    return unique


def scan(image_ids: object, severity: str, ignorefile: Path, *, env: dict[str, str] | None = None) -> int:
    """Run one local-Docker Trivy scan per distinct immutable image ID."""
    ids = _validated_image_ids(image_ids)
    if severity not in _SEVERITIES:
        raise ValueError("severity must be CRITICAL or HIGH")
    ignorefile = Path(ignorefile)
    if not ignorefile.is_file():
        raise ValueError("Trivy ignorefile does not exist or is not a file")

    scan_env = dict(os.environ if env is None else env)
    cache_dir = scan_env.get("TRIVY_CACHE_DIR")
    if not cache_dir:
        raise ValueError("TRIVY_CACHE_DIR is required")

    exit_code = _SEVERITIES[severity]
    failed = False
    for image_id in ids:
        command = [
            "trivy",
            "image",
            "--image-src",
            "docker",
            "--ignore-unfixed",
            "--format",
            "table",
            "--scanners",
            "vuln,secret",
            "--severity",
            severity,
            "--exit-code",
            exit_code,
            "--ignorefile",
            str(ignorefile),
            "--cache-dir",
            cache_dir,
            "--timeout",
            "10m",
            image_id,
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                env=scan_env,
                timeout=_SCAN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            sys.stderr.write(f"Trivy failed or timed out scanning immutable image {image_id}\n")
            failed = True
            continue
        if result.returncode != 0:
            failed = True
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-ids", type=Path, required=True, help="JSON file containing immutable image IDs")
    parser.add_argument("--severity", choices=sorted(_SEVERITIES), required=True)
    parser.add_argument("--ignorefile", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        image_ids = json.loads(args.image_ids.read_text(encoding="utf-8"))
        return scan(image_ids, args.severity, args.ignorefile)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write(f"Trivy image scan: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
