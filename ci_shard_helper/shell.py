"""Source-bound discovery and serial execution for shell-file shards.

Shell test files are process-isolated but may share checkout state. Each shard
therefore runs its assigned scripts serially in one checkout and runs the
repository's final cleanup invariant after all selected scripts.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

from .cli import _write_json, receipt_to_json
from .manifest import ShardManifest, make_shard_receipt, validate_manifest

DEFAULT_TESTS_DIR = "tests"
DEFAULT_PREFLIGHT_SCRIPT = "tests/run_tests.sh"
DEFAULT_CLEANUP_SCRIPT = "tests/test_suite_leaves_tree_clean.sh"


def _normalized_relative_path(value: str, *, description: str) -> str:
    if not isinstance(value, str) or value in {"", ".", ".."} or "\\" in value:
        raise ValueError(f"{description} must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{description} must be a normalized relative POSIX path")
    if any(ord(char) < 32 for char in value) or value != value.strip():
        raise ValueError(f"{description} contains invalid whitespace or control characters")
    return value


def _regular_file(root: Path, relative: str, *, description: str) -> Path:
    relative = _normalized_relative_path(relative, description=description)
    current = root
    parts = PurePosixPath(relative).parts
    for part in parts[:-1]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ValueError(f"{description} does not exist: {relative}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError(f"{description} has a symlink or non-directory path component: {relative}")
    candidate = current / parts[-1]
    try:
        mode = candidate.lstat().st_mode
    except OSError as exc:
        raise ValueError(f"{description} does not exist: {relative}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"{description} must be a regular non-symlink file: {relative}")
    return candidate


def _checkout_root(root: str | Path) -> Path:
    try:
        checkout = Path(root).resolve(strict=True)
    except OSError as exc:
        raise ValueError("shell shard checkout root does not exist") from exc
    if not checkout.is_dir():
        raise ValueError("shell shard checkout root must be a directory")
    return checkout


def collect_shell_files(
    root: str | Path,
    *,
    tests_dir: str = DEFAULT_TESTS_DIR,
    cleanup_script: str = DEFAULT_CLEANUP_SCRIPT,
) -> tuple[str, ...]:
    """Derive the complete sorted direct-child ``test_*.sh`` universe.

    The cleanup invariant is required to exist and is excluded from ordinary
    partition units. Matching symlinks and non-regular entries are errors;
    they are never silently omitted from collection.
    """
    checkout = _checkout_root(root)
    tests_dir = _normalized_relative_path(tests_dir, description="tests_dir")
    cleanup_script = _normalized_relative_path(cleanup_script, description="cleanup_script")
    tests_path = checkout / tests_dir
    try:
        mode = tests_path.lstat().st_mode
    except OSError as exc:
        raise ValueError(f"shell test directory does not exist: {tests_dir}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError(f"shell test directory must be a regular non-symlink directory: {tests_dir}")

    _regular_file(checkout, cleanup_script, description="cleanup script")
    units: list[str] = []
    try:
        entries = sorted(tests_path.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise ValueError(f"cannot list shell test directory: {tests_dir}") from exc
    for entry in entries:
        if not entry.name.startswith("test_") or not entry.name.endswith(".sh"):
            continue
        relative = entry.relative_to(checkout).as_posix()
        _regular_file(checkout, relative, description="shell test unit")
        if relative != cleanup_script:
            units.append(relative)
    if not units:
        raise ValueError("shell test collection produced an empty test-file universe")
    if len(set(units)) != len(units):
        raise ValueError("shell test collection produced duplicate paths")
    return tuple(units)


def _tracked_tree_was_clean(root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError("cannot inspect tracked checkout state before shell tests")
    return not result.stdout.strip()


def _run_bash_script(
    root: Path,
    relative: str,
    *,
    environment: dict[str, str],
    arguments: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    script = _regular_file(root, relative, description="shell script")
    return subprocess.run(
        ["bash", str(script), *arguments],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _report_result(name: str, result: subprocess.CompletedProcess[str], *, verbose: bool) -> None:
    if result.returncode == 0:
        sys.stdout.write(f"PASS {name}\n")
        if verbose:
            if result.stdout:
                sys.stdout.write("".join(f"    {line}" for line in result.stdout.splitlines(keepends=True)))
            if result.stderr:
                sys.stdout.write("".join(f"    {line}" for line in result.stderr.splitlines(keepends=True)))
    else:
        sys.stdout.write(f"FAIL {name}\n")
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)


def run_shell_shard(
    root: str | Path,
    *,
    manifest: ShardManifest,
    shard_id: int,
    preflight_script: str = DEFAULT_PREFLIGHT_SCRIPT,
    cleanup_script: str = DEFAULT_CLEANUP_SCRIPT,
    receipt_path: str | Path,
    tests_dir: str = DEFAULT_TESTS_DIR,
) -> tuple[str, ...]:
    """Run one assigned shard and write its receipt only after final cleanup.

    ``preflight_script`` is invoked with ``--preflight`` once per shard. Each
    assigned file then runs in its own Bash process, serially in ``root``. The
    cleanup invariant is run last even if one or more assigned scripts failed,
    matching the repository driver's failure-collection behavior.
    """
    checkout = _checkout_root(root)
    if not isinstance(manifest, ShardManifest):
        raise ValueError("shell execution requires a ShardManifest")
    validate_manifest(manifest)
    if manifest.framework != "shell-file" or manifest.format_version != 2:
        raise ValueError("shell execution requires an identity-bound format-2 shell-file manifest")
    if type(shard_id) is not int or not 1 <= shard_id <= manifest.shard_total:
        raise ValueError("shard_id is outside the manifest")

    discovered = collect_shell_files(checkout, tests_dir=tests_dir, cleanup_script=cleanup_script)
    if discovered != manifest.units:
        raise ValueError("shell manifest units differ from the complete checkout test-file universe")
    preflight_script = _normalized_relative_path(preflight_script, description="preflight_script")
    _regular_file(checkout, preflight_script, description="preflight script")
    _regular_file(checkout, cleanup_script, description="cleanup script")

    output = Path(receipt_path)
    if output.exists() or output.is_symlink():
        raise ValueError("shell receipt output already exists")

    # Import at execution time so the portable module has one shared runtime
    # identity authority and collection-only callers need no runtime context.
    from .runtime import assert_runtime_identity

    assert_runtime_identity(manifest, shard_id, root=checkout)

    preflight = _run_bash_script(checkout, preflight_script, environment=dict(os.environ), arguments=("--preflight",))
    if preflight.returncode != 0:
        _report_result("shell preflight", preflight, verbose=True)
        raise ValueError(f"shell preflight failed with exit code {preflight.returncode}")

    environment = dict(os.environ)
    environment.pop("DOTFILES_TREE_WAS_CLEAN", None)
    if _tracked_tree_was_clean(checkout):
        environment["DOTFILES_TREE_WAS_CLEAN"] = "1"

    selected = manifest.shards[shard_id - 1]
    failures: list[str] = []
    verbose = environment.get("VERBOSE", "0") == "1"
    for unit in selected:
        result = _run_bash_script(checkout, unit, environment=environment)
        _report_result(Path(unit).name, result, verbose=verbose)
        if result.returncode != 0:
            failures.append(f"{unit} (exit {result.returncode})")

    cleanup = _run_bash_script(checkout, cleanup_script, environment=environment)
    _report_result(Path(cleanup_script).name, cleanup, verbose=verbose)
    if cleanup.returncode != 0:
        failures.append(f"{cleanup_script} (exit {cleanup.returncode})")
    if failures:
        raise ValueError("shell shard failed: " + ", ".join(failures))

    receipt = make_shard_receipt(manifest, shard_id, selected)
    _write_json(str(output), receipt_to_json(receipt))
    return tuple(selected)
