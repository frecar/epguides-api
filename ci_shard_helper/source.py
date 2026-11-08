"""Tracked regular-file ownership for source-bound native suite evidence."""

from __future__ import annotations

import stat
from pathlib import Path
from subprocess import CalledProcessError
from subprocess import run as git_run


class TrackedSources:
    """One index snapshot per collection/seal, rather than one Git call per case."""

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        try:
            result = git_run(
                ["git", "ls-files", "--stage", "-z", "--", "."],
                cwd=self.root,
                capture_output=True,
                check=True,
            )
        except (OSError, CalledProcessError) as exc:
            raise ValueError("tracked source ownership is unavailable") from exc
        self.paths: set[str] = set()
        for entry in result.stdout.decode("utf-8").split("\0"):
            if not entry:
                continue
            metadata, relative = entry.split("\t", 1)
            mode, _blob, stage = metadata.split()
            if stage != "0":
                raise ValueError("source ownership index has unresolved entries")
            if mode in {"100644", "100755"}:
                self.paths.add(relative)

    def require(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self.root / path
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("source file is outside its tracked checkout") from exc
        if not relative.parts or any(part in {".", ".."} for part in relative.parts):
            raise ValueError("source file path is not canonical")
        current = self.root
        try:
            for part in relative.parts:
                current /= part
                if current.is_symlink():
                    raise ValueError("source file has a symlink path component")
            if not stat.S_ISREG(current.stat().st_mode) or relative.as_posix() not in self.paths:
                raise ValueError("source file is not a tracked regular checkout file")
        except OSError as exc:
            raise ValueError("tracked source file is missing or unreadable") from exc
        return current
