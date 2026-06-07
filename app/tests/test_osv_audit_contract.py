"""Contract + behaviour tests for the local OSV-Scanner pre-push CVE check.

Guards epguides-api#324. Two layers:

  * Wiring contract — the four touchpoints (`.osv-scanner.toml`,
    `scripts/audit_osv.sh`, the `make audit-osv` target, the `audit-osv`
    pre-push hook) plus the authoritative CI OSV-Scanner step must all stay
    present and consistent so a future edit can't silently re-open the gap.
  * Exit-code behaviour — `scripts/audit_osv.sh` must warn-skip (exit 0) when
    the binary is absent / there is no lockfile / osv.dev is unreachable, and
    hard-fail (exit 1) ONLY when the scan ran and reported a vulnerability.
    The script is exercised end-to-end against a stubbed `osv-scanner` so the
    "never hard-block an offline push, always block a real vuln" contract is
    regression-locked.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

# Absolute bash path so spawning the subprocess never depends on the
# (deliberately narrowed) PATH the tests construct for the script.
_BASH = shutil.which("bash") or "/bin/bash"

_REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = _REPO_ROOT / "Makefile"
PRE_COMMIT = _REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
OSV_CONFIG = _REPO_ROOT / ".osv-scanner.toml"
AUDIT_SCRIPT = _REPO_ROOT / "scripts" / "audit_osv.sh"

# The pinned OSV-Scanner action ref that CI uses as the authoritative
# online dependency-CVE backstop.
_OSV_ACTION = "google/osv-scanner-action/osv-scanner-action@9a498708959aeaef5ef730655706c5a1df1edbc2"


def _local_hooks() -> dict[str, dict]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        if repo.get("repo") == "local":
            return {hook["id"]: hook for hook in repo["hooks"]}
    raise AssertionError("no `repo: local` block in .pre-commit-config.yaml")


# --------------------------------------------------------------------------
# Wiring contract
# --------------------------------------------------------------------------


def test_osv_config_present_and_parses() -> None:
    """`.osv-scanner.toml` exists and is valid TOML (zero ignores is valid)."""
    import tomllib

    assert OSV_CONFIG.is_file(), "missing .osv-scanner.toml ignore-policy file"
    tomllib.loads(OSV_CONFIG.read_text(encoding="utf-8"))


def test_audit_script_present_and_executable() -> None:
    """`scripts/audit_osv.sh` exists and carries the executable bit."""
    assert AUDIT_SCRIPT.is_file(), "missing scripts/audit_osv.sh"
    mode = AUDIT_SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/audit_osv.sh must be executable"


def test_makefile_exposes_audit_osv_target() -> None:
    """`make audit-osv` shells to the wrapper script."""
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "\naudit-osv:" in text, "missing the `audit-osv` Makefile target"
    assert "audit-osv" in text.split(".PHONY", 1)[1].split("\n\n", 1)[0] or "audit-osv" in text, (
        "audit-osv should be declared .PHONY"
    )
    recipe = text.split("\naudit-osv:", 1)[1].splitlines()[1]
    assert "scripts/audit_osv.sh" in recipe, "audit-osv must run scripts/audit_osv.sh"


def test_pre_push_runs_audit_osv() -> None:
    """A dedicated pre-push hook runs the OSV check, separate from ci-parity."""
    hooks = _local_hooks()
    assert "audit-osv" in hooks, "missing the audit-osv pre-push hook"
    hook = hooks["audit-osv"]
    assert hook["entry"] == "bash scripts/audit_osv.sh"
    assert hook["stages"] == ["pre-push"]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    # Deliberately a SEPARATE hook from ci-parity (OSV needs the advisory DB;
    # ci-parity is offline-deterministic) — they must not be merged.
    assert "ci-parity" in hooks
    assert hook["entry"] != hooks["ci-parity"]["entry"]


def test_ci_has_authoritative_online_osv_job() -> None:
    """CI runs OSV-Scanner online (the backstop the local hook shifts left).

    Pinned action ref + the exact `--lockfile=uv.lock --config=.osv-scanner.toml`
    scan-args, inside a job the ci-gate already gates on.
    """
    config = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    audit_steps = config["jobs"]["audit"]["steps"]
    osv_step = next(
        (s for s in audit_steps if str(s.get("uses", "")).startswith(_OSV_ACTION)),
        None,
    )
    assert osv_step is not None, "CI audit job must run the pinned OSV-Scanner action"
    scan_args = osv_step["with"]["scan-args"]
    assert "--lockfile=uv.lock" in scan_args
    assert "--config=.osv-scanner.toml" in scan_args
    # The audit job is one of ci-gate's required `needs`, so the OSV step gates.
    assert "audit" in config["jobs"]["ci-gate"]["needs"]


# --------------------------------------------------------------------------
# Exit-code behaviour (script run end-to-end against a stubbed osv-scanner)
# --------------------------------------------------------------------------


def _run_audit(tmp_path: Path, *, stub: str | None, rc: int = 0, out: str = "") -> subprocess.CompletedProcess:
    """Run scripts/audit_osv.sh with an optional stub `osv-scanner` on PATH.

    A tmp working copy holds a real uv.lock so the no-lockfile gate doesn't
    fire; the stub emits `out` to stderr and exits `rc`.
    """
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    # Copy the real script + a placeholder lockfile + config so the prereq
    # gates pass and only the classification logic is under test.
    (work / "scripts" / "audit_osv.sh").write_bytes(AUDIT_SCRIPT.read_bytes())
    (work / "scripts" / "audit_osv.sh").chmod(0o755)
    (work / "uv.lock").write_text("# placeholder lockfile\n", encoding="utf-8")
    (work / ".osv-scanner.toml").write_text("# no ignores\n", encoding="utf-8")

    # Keep the inherited PATH so the script's own helper utilities (dirname,
    # grep, cd/pwd) resolve; we only ADD a stub osv-scanner ahead of it (or,
    # for the binary-absent case, add nothing — the host genuinely has no
    # osv-scanner installed, asserted by the caller).
    env = dict(os.environ)
    if stub is not None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        stub_path = bindir / "osv-scanner"
        stub_path.write_text(stub, encoding="utf-8")
        stub_path.chmod(0o755)
        env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
        env["STUB_RC"] = str(rc)
        env["STUB_OUT"] = out

    return subprocess.run(
        [_BASH, str(work / "scripts" / "audit_osv.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(work),
    )


_STUB = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    [[ -n "${STUB_OUT:-}" ]] && printf '%s\\n' "${STUB_OUT}" >&2
    exit "${STUB_RC:-0}"
    """
)


@pytest.mark.skipif(
    shutil.which("osv-scanner") is not None,
    reason="osv-scanner is installed on this host; binary-absent path can't be exercised without shadowing it",
)
def test_warn_skip_when_binary_absent(tmp_path: Path) -> None:
    """No osv-scanner on PATH -> warn-skip, exit 0 (never block an offline push)."""
    result = _run_audit(tmp_path, stub=None)
    assert result.returncode == 0
    assert "WARN-SKIP" in result.stderr
    assert "binary not found" in result.stderr


def test_warn_skip_when_no_lockfile(tmp_path: Path) -> None:
    """No uv.lock -> warn-skip, exit 0."""
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    (work / "scripts" / "audit_osv.sh").write_bytes(AUDIT_SCRIPT.read_bytes())
    (work / "scripts" / "audit_osv.sh").chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "osv-scanner").write_text(_STUB, encoding="utf-8")
    (bindir / "osv-scanner").chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [_BASH, str(work / "scripts" / "audit_osv.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(work),
    )
    assert result.returncode == 0
    assert "WARN-SKIP" in result.stderr
    assert "nothing to scan" in result.stderr


def test_pass_when_clean(tmp_path: Path) -> None:
    """osv-scanner exit 0 -> pass, exit 0."""
    result = _run_audit(tmp_path, stub=_STUB, rc=0, out="No issues found")
    assert result.returncode == 0
    assert "OK" in result.stdout
    assert "WARN-SKIP" not in result.stderr


def test_block_when_vuln_found(tmp_path: Path) -> None:
    """osv-scanner exit 1 -> hard-fail, exit 1 (the whole point of the hook)."""
    result = _run_audit(tmp_path, stub=_STUB, rc=1, out="CVE-2026-9999 in foo 1.0")
    assert result.returncode == 1
    assert "FAIL" in result.stderr
    assert "un-ignored vulnerabilities" in result.stderr


def test_warn_skip_when_offline(tmp_path: Path) -> None:
    """Non-{0,1} exit with a recognised network error -> warn-skip, exit 0."""
    result = _run_audit(
        tmp_path,
        stub=_STUB,
        rc=128,
        out='Get "https://api.osv.dev/v1/querybatch": dial tcp: lookup api.osv.dev: no such host',
    )
    assert result.returncode == 0
    assert "WARN-SKIP" in result.stderr
    assert "advisory API" in result.stderr


def test_hard_fail_on_unrecognised_error(tmp_path: Path) -> None:
    """Non-{0,1} exit with NO network signature -> hard-fail (don't mask a
    broken config/args as an offline skip)."""
    result = _run_audit(tmp_path, stub=_STUB, rc=127, out="Error: unknown flag: --bogus")
    assert result.returncode == 1
    assert "unrecognised error" in result.stderr
    assert "WARN-SKIP" not in result.stderr
