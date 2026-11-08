"""Exercise the actual checksum-pinned installer without network or executables."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CI = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
PIN = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
PAYLOAD = "verified archive fixture"


def _step() -> dict:
    return next(
        step
        for step in yaml.safe_load(CI.read_text())["jobs"]["gitleaks"]["steps"]
        if step.get("name") == "Install pinned gitleaks"
    )


def _release() -> dict:
    return {
        "tag_name": "v8.30.1",
        "assets": [{"id": 123, "name": "gitleaks_8.30.1_linux_x64.tar.gz", "state": "uploaded"}],
    }


def _run(tmp_path: Path, *, direct: int = 22, metadata: dict | None = None, **transport: str):
    step = _step()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    stubs = {
        "curl": (
            f'printf "curl %s\\n" "$*" >> {log}\n'
            'while [ $# -gt 1 ]; do [ "$1" = -o ] && printf "%s" "$PAYLOAD" > "$2"; shift; done\n'
            'exit "$DIRECT_RC"\n'
        ),
        "gh": (
            f'printf "gh %s\\n" "$*" >> {log}\n'
            'case "$2" in\n'
            "  */tags/*)\n"
            '    [ "${METADATA_RC:-0}" = 0 ] || exit "$METADATA_RC"\n'
            '    while [ "$1" != --jq ]; do shift; done\n'
            f'    printf "%s" "$METADATA" | {shutil.which("jq")} -er "$2" ;;\n'
            '  */assets/*) printf "%s" "$PAYLOAD"; exit "${ASSET_RC:-0}" ;;\n'
            "  *) exit 99 ;;\n"
            "esac\n"
        ),
        "tar": f'printf "tar %s\\n" "$*" >> {log}\n',
        "install": f'printf "install %s\\n" "$*" >> {log}\n',
    }
    for name, body in stubs.items():
        path = bin_dir / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)
    for name in ("mktemp", "rm", "sha256sum"):
        (bin_dir / name).symlink_to(shutil.which(name))
    env = {
        **{key: str(value) for key, value in step["env"].items()},
        "PATH": str(bin_dir),
        "TMPDIR": str(tmp_path),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_PATH": str(tmp_path / "github_path"),
        "GITLEAKS_SHA256": hashlib.sha256(PAYLOAD.encode()).hexdigest(),
        "DIRECT_RC": str(direct),
        "METADATA": json.dumps(_release() if metadata is None else metadata),
        "PAYLOAD": PAYLOAD,
        **transport,
    }
    result = subprocess.run(
        [shutil.which("bash"), "-c", step["run"]], env=env, capture_output=True, text=True, check=False
    )
    assert not list(tmp_path.glob("tmp.*")), "temporary downloads must be removed on every exit"
    return result, log.read_text()


def test_source_pin_and_job_token_remain_explicit() -> None:
    assert _step()["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GITLEAKS_VERSION": "8.30.1",
        "GITLEAKS_SHA256": PIN,
    }


@pytest.mark.parametrize("direct", [0, 22])
def test_success_checks_bytes_before_install_and_uses_only_one_alternate_path(direct, tmp_path) -> None:
    result, calls = _run(tmp_path, direct=direct)
    assert result.returncode == 0, result.stderr
    lines = calls.splitlines()
    assert lines[0].startswith("curl -fsSL --connect-timeout 10 --max-time 60 ")
    assert "--retry" not in calls
    assert sum(line.startswith("curl ") for line in lines) == 1
    assert sum(line.startswith("gh ") for line in lines) == (2 if direct else 0)
    if direct:
        assert lines[2] == "gh api repos/gitleaks/gitleaks/releases/assets/123 -H Accept: application/octet-stream"
    assert lines[-2].startswith("tar ") and lines[-1].startswith("install ")
    assert "${{ github.token }}" not in calls + result.stdout + result.stderr


@pytest.mark.parametrize(
    "failure",
    ["metadata", "download", "missing", "empty", "duplicate", "foreign", "unuploaded", "tag", "id", "checksum"],
)
def test_unsafe_or_failed_fallback_never_extracts_or_installs(failure, tmp_path) -> None:
    release = _release()
    transport = {}
    if failure == "metadata":
        transport["METADATA_RC"] = "1"
    elif failure == "download":
        transport["ASSET_RC"] = "1"
    elif failure == "missing":
        del release["assets"]
    elif failure == "empty":
        release["assets"] = []
    elif failure == "duplicate":
        release["assets"] *= 2
    elif failure == "foreign":
        release["assets"][0]["name"] = "foreign.tar.gz"
    elif failure == "unuploaded":
        release["assets"][0]["state"] = "open"
    elif failure == "tag":
        release["tag_name"] = "v999.0.0"
    elif failure == "id":
        release["assets"][0]["id"] = "123/foreign"
    elif failure == "checksum":
        transport["PAYLOAD"] = "corrupt bytes"
    result, calls = _run(tmp_path, metadata=release, **transport)
    assert result.returncode != 0
    assert "tar " not in calls and "install " not in calls
    assert sum(line.startswith("gh ") for line in calls.splitlines()) <= 2
    assert not (tmp_path / "github_path").exists()
