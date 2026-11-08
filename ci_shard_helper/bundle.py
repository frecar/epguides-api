"""Verify a generated standalone helper payload without private dependencies."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path, PurePosixPath

MANIFEST_NAME = "MANIFEST.sha256"
_ENTRY = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9_./-]+)\Z")


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        value in {"", ".", ".."}
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("bundle manifest contains an invalid relative path")
    return value


def bundle_manifest(files: dict[str, bytes]) -> bytes:
    return (
        "\n".join(f"{hashlib.sha256(data).hexdigest()}  {_relative(path)}" for path, data in sorted(files.items()))
        + "\n"
    ).encode("ascii")


def verify_bundle(root: Path) -> None:
    root = root.resolve()
    entries: dict[str, str] = {}
    manifest = root / MANIFEST_NAME
    if manifest.is_symlink():
        raise ValueError("bundle manifest must be a regular file")
    for line in manifest.read_text(encoding="ascii").splitlines():
        match = _ENTRY.fullmatch(line)
        if match is None:
            raise ValueError("bundle manifest contains a malformed digest entry")
        digest, relative = match.groups()
        _relative(relative)
        if relative == MANIFEST_NAME or relative in entries:
            raise ValueError("bundle manifest contains a duplicate or self entry")
        entries[relative] = digest
    if "__init__.py" not in entries:
        raise ValueError("bundle manifest is empty or lacks the package initializer")
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("bundle contains a symlink")
        if not path.is_file():
            continue
        # Python creates these after importing the verified source. They are
        # runtime products, not generated source or manifest membership.
        if path.parent.name == "__pycache__" and path.suffix == ".pyc":
            continue
        relative = path.relative_to(root).as_posix()
        if relative != MANIFEST_NAME:
            actual.add(relative)
    if actual != set(entries):
        raise ValueError("bundle files differ from the generated manifest")
    for relative, digest in entries.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("bundle source differs from its generated digest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    try:
        verify_bundle(args.root)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, f"helper bundle verification refused: {exc}\n")
    sys.stdout.write("helper bundle verified\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
