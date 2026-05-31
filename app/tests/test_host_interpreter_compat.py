"""Guard the host-interpreter syntax-drift regression class for this repo.

Every `scripts/*.py` is invoked by the system `python3` (a developer's machine
or CI runner, which may be older than 3.14) via the `language: system`
pre-commit hooks (`python3 scripts/check_no_external_llm.py`) and
`make ci`/`ci-parity`, NOT the 3.14 `uv` venv the app itself runs in. The repo
is `requires-python >=3.14` + ruff `target-version=py314`, so the 3.14 toolchain
(incl. `ruff format`) happily emits 3.14-only syntax — most dangerously by
rewriting `except (A, B):` into PEP 758 unparenthesized `except A, B:`, a hard
SyntaxError on any interpreter older than 3.14.

The test suite itself runs on the 3.14 interpreter (`requires-python >=3.14`),
where PEP 758 is valid — so merely importing or compiling these scripts under
the test interpreter does NOT prove they parse on an older host. We compile them
under a REAL CPython 3.12 to mirror the minimum supported host interpreter.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

# Minimum system interpreter the host-run scripts must stay parseable under.
_HOST_PYTHON_VERSION = "3.12"


def _host_python_compile_cmd() -> list[str] | None:
    """Build a command that compiles a file under a real CPython 3.12, or None
    if no 3.12 interpreter is reachable.

    Prefers a `python3.12` already on PATH (fast, no network); falls back to
    `uv run --python 3.12 --no-project` (uv fetches the interpreter on the fly,
    `--no-project` sidesteps the repo's `requires-python >=3.14` gate since
    py_compile needs only the interpreter grammar, no project deps)."""
    direct = shutil.which(f"python{_HOST_PYTHON_VERSION}")
    if direct:
        return [direct, "-m", "py_compile"]
    if shutil.which("uv"):
        return ["uv", "run", "--python", _HOST_PYTHON_VERSION, "--no-project", "python", "-m", "py_compile"]
    return None


def _compile_under_host_python(path: Path) -> subprocess.CompletedProcess[str]:
    cmd = _host_python_compile_cmd()
    if cmd is None:  # pragma: no cover - CI always has 3.12 or uv
        pytest.skip(f"No Python {_HOST_PYTHON_VERSION} interpreter reachable for host-compat check")
    return subprocess.run([*cmd, str(path)], capture_output=True, text=True, timeout=120)


_HOST_SCRIPTS = sorted(_SCRIPTS_DIR.glob("*.py"))


def test_repo_has_host_scripts() -> None:
    """Sanity: the guard is meaningless if scripts/ has no Python files. If this
    fails the parametrized test below silently passes (empty parametrization)."""
    assert _HOST_SCRIPTS, f"expected at least one host-run script under {_SCRIPTS_DIR}"


@pytest.mark.parametrize("script", _HOST_SCRIPTS, ids=lambda p: p.name)
def test_host_scripts_compile_under_host_python_312(script: Path) -> None:
    """Every scripts/*.py must stay parseable by the host Python 3.12 — it runs
    there via the `language: system` pre-commit hooks + make targets, not the
    3.14 `uv` venv. 3.14-only syntax (e.g. PEP 758 `except A, B:`) would break
    it on any system interpreter older than 3.14."""
    result = _compile_under_host_python(script)
    assert result.returncode == 0, (
        f"{script.name} must compile under host Python {_HOST_PYTHON_VERSION} "
        f"(it runs there via pre-commit / make, not the 3.14 container).\n"
        f"stderr:\n{result.stderr}"
    )


def test_guard_rejects_314_only_syntax(tmp_path: Path) -> None:
    """Prove the guard actually catches the regression: an unparenthesized
    multi-except is valid on 3.14 but a SyntaxError on the host 3.12. If this
    passes, the guard is real — not a no-op that would also pass on bad code."""
    probe = tmp_path / "probe.py"
    source = "try:\n    pass\nexcept ValueError, TypeError:\n    pass\n"
    probe.write_text(source)
    # Sanity: PEP 758 IS valid on the test interpreter (the 3.14 container,
    # where the suite runs) — confirms the bug is purely an interpreter-version
    # mismatch, not malformed code. `requires-python >=3.14` guarantees this.
    assert sys.version_info >= (3, 14)
    compile(source, str(probe), "exec")
    result = _compile_under_host_python(probe)
    assert result.returncode != 0, "host-3.12 guard must reject PEP 758 `except A, B:`"
    assert "parenthesized" in result.stderr.lower()
