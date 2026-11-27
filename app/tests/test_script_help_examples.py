import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
ARGPARSE_SCRIPTS = sorted(path for path in SCRIPTS_DIR.glob("*.py") if "argparse.ArgumentParser(" in path.read_text())


def test_argparse_scripts_are_discovered():
    assert len(ARGPARSE_SCRIPTS) >= 4, f"expected argparse scripts under {SCRIPTS_DIR}, found {ARGPARSE_SCRIPTS}"


@pytest.mark.parametrize("script", ARGPARSE_SCRIPTS, ids=lambda path: path.name)
def test_script_help_shows_runnable_example(script: Path):
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, f"{script.name} --help failed: {result.stderr}"
    assert "Example:" in result.stdout, f"{script.name} --help must end with an 'Example:' epilog"
    assert f"scripts/{script.name}" in result.stdout, f"{script.name} example must invoke scripts/{script.name}"
