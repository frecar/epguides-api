"""Public CI binds complete test evidence without changing application coverage."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ci_shard_helper.bundle import verify_bundle
from scripts import ci_pytest_shards as ci

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def metadata(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "frecar/epguides-api")
    monkeypatch.setenv("GITHUB_REPOSITORY_ID", "10174577")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("CI_FORK_PR", "false")
    monkeypatch.setenv("CI_FLEET_UNTRUSTED_ENABLED", "true")
    monkeypatch.setenv("CI_QUALIFIED_DOCKER_CAPACITY", "3")


@pytest.mark.parametrize("value", ["", "0", "-1", "01", "1.0", "true", "١", "1025"])
def test_invalid_qualification_refuses_before_collection(metadata, monkeypatch, tmp_path, value):
    monkeypatch.setenv("CI_QUALIFIED_DOCKER_CAPACITY", value)
    monkeypatch.setattr(ci, "helper", lambda *_: pytest.fail("collected before positive qualification"))
    assert ci.main(["plan", "--directory", str(tmp_path / "new")]) == 1
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize(
    "fork,flag,wanted",
    [("true", "true", False), ("", "true", False), ("false", "false", False), ("false", "true", True)],
)
def test_hosted_fork_and_default_boundary(metadata, monkeypatch, fork, flag, wanted):
    monkeypatch.setenv("CI_FORK_PR", fork)
    monkeypatch.setenv("CI_FLEET_UNTRUSTED_ENABLED", flag)
    assert ci.fleet_requested() is wanted
    ci.gate("success" if wanted else "skipped", "success" if wanted else "skipped")
    with pytest.raises(ValueError):
        ci.gate("failure", "skipped")


@pytest.mark.parametrize(
    "repository,number",
    [("", "1"), ("owner", "1"), ("owner/repo", "0"), ("owner/repo", "01"), ("owner/repo", str(2**63))],
)
def test_runtime_repository_identity_is_not_guessed(metadata, monkeypatch, repository, number):
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    monkeypatch.setenv("GITHUB_REPOSITORY_ID", number)
    with pytest.raises(ValueError):
        ci.identity()


def test_generated_payload_manifest_covers_every_byte_and_refuses_missing_extra_or_changed_source(tmp_path):
    bundle = tmp_path / "helper"
    shutil.copytree(ROOT / "ci_shard_helper", bundle, ignore=shutil.ignore_patterns("__pycache__"))
    verify_bundle(bundle)
    payload = bundle / "manifest.py"
    original = payload.read_bytes()
    payload.write_bytes(original + b"\n# drift\n")
    with pytest.raises(ValueError):
        verify_bundle(bundle)
    payload.write_bytes(original)
    payload.unlink()
    with pytest.raises(ValueError):
        verify_bundle(bundle)
    payload.write_bytes(original)
    (bundle / "unexpected.py").write_text("pass\n")
    with pytest.raises(ValueError):
        verify_bundle(bundle)


def test_workflow_retains_hosted_default_services_fixed_floor_and_qualified_public_route():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    spec = json.loads((ROOT / ci.SPEC).read_text())
    assert "--cov=app" in spec["argv"] and "--cov-fail-under=95" in spec["argv"]
    assert spec["argv"][spec["argv"].index("-n") + 1] == "auto"
    assert "scripts/compute_xdist_workers.py" in spec["config_files"]
    assert "vars.CI_FLEET_UNTRUSTED_LINUX_DOCKER_X64_COMPATIBLE_CAPACITY" in workflow
    assert "vars.CI_FLEET_COMPATIBLE_CAPACITY" not in workflow
    assert "fleet-pooled-untrusted-linux-docker-x64" in workflow
    assert "github.event.pull_request.head.repo.full_name != github.repository" in workflow
    assert "needs: [test-plan, test-shard]" in workflow and "if: always() && !cancelled()" in workflow
    assert workflow.count("image: redis:7.4.11-alpine@sha256:") == 3
    assert "include-hidden-files: true" in workflow and "fail-fast: false" in workflow
    assert "name: Test\n" in workflow and "needs: [audit, lint, typecheck, test," in workflow


@pytest.fixture
def native_checkout(tmp_path, metadata):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "scripts").mkdir()
    (root / ".github").mkdir()
    (root / "tests").mkdir()
    shutil.copytree(ROOT / "ci_shard_helper", root / "ci_shard_helper", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "scripts/ci_pytest_shards.py", root / "scripts/ci_pytest_shards.py")
    (root / "calc.py").write_text("def value(flag):\n    if flag:\n        return 1\n    return 2\n")
    (root / "tests/test_one.py").write_text("from calc import value\ndef test_one():\n    assert value(True) == 1\n")
    (root / "tests/test_two.py").write_text("from calc import value\ndef test_two():\n    assert value(False) == 2\n")
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath=["."]\n[tool.coverage.run]\nsource=["calc"]\nrelative_files=true\n[tool.coverage.report]\nfail_under=95\n'
    )
    spec = {
        "argv": ["pytest", "tests", "--cov=calc", "--cov-fail-under=95", "-q"],
        "config_files": [ci.SPEC, "pyproject.toml"],
        "environment": [],
    }
    (root / ci.SPEC).write_text(json.dumps(spec))
    # Commit hooks export repository locations. A fixture must never inherit
    # their index or object directory when creating its independent repository.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    for args in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", *args], cwd=root, env=environment, check=True, capture_output=True)

    def run(*args, success=True, extra_env=None):
        result = subprocess.run(
            [sys.executable, "scripts/ci_pytest_shards.py", *args],
            cwd=root,
            env={**environment, **(extra_env or {})},
            capture_output=True,
            text=True,
            timeout=60,
        )
        if success:
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            assert result.returncode != 0
        return result

    return root, run, environment


@pytest.mark.parametrize("capacity,expected", [(1, 1), (2, 1), (3, 2), (4, 3), (1024, 5)])
def test_native_plan_reserves_one_compatible_position_with_single_position_exception(
    native_checkout, capacity, expected
):
    root, run, environment = native_checkout
    for number in range(3, 6):
        (root / f"tests/test_extra_{number}.py").write_text(f"def test_extra_{number}():\n    assert True\n")
    for arguments in (
        ["add", "tests"],
        ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", *arguments], cwd=root, env=environment, check=True, capture_output=True)
    run("plan", "--directory", "plan", extra_env={"CI_QUALIFIED_DOCKER_CAPACITY": str(capacity)})
    manifest = json.loads((root / "plan/manifest.json").read_text())
    descriptor = json.loads((root / "plan/suite.json").read_text())
    assert len(descriptor["collection"]) == 5
    assert manifest["shard_total"] == expected


def test_real_complete_native_shards_seal_combine_and_refuse_tampered_coverage(native_checkout):
    root, run, _environment = native_checkout
    run("plan", "--directory", "plan")
    manifest = json.loads((root / "plan/manifest.json").read_text())
    descriptor = json.loads((root / "plan/suite.json").read_text())
    assert manifest["format"] == 2 and manifest["shard_total"] == 2
    assert sum(len(unit["cases"]) for unit in descriptor["collection"].values()) == 2
    for shard in (1, 2):
        run("run", "--directory", "plan", "--shard", str(shard))
    pair = root / "plan/artifacts/shard-1/receipt.coverage.json"
    data = root / "plan/artifacts/shard-1/.coverage"
    sealed = data.read_bytes()
    data.write_bytes(sealed + b"tamper")
    run("combine", "--directory", "plan", "--artifacts", "plan/artifacts", success=False)
    data.write_bytes(sealed)
    run("combine", "--directory", "plan", "--artifacts", "plan/artifacts")
    assert (root / "plan/combined.coverage").is_file()
    assert json.loads(pair.read_text())["manifest_digest"] == manifest["digest"]


def test_native_missing_receipt_and_changed_invocation_fail_closed(native_checkout):
    root, run, _environment = native_checkout
    run("plan", "--directory", "plan")
    run("run", "--directory", "plan", "--shard", "1")
    run("combine", "--directory", "plan", "--artifacts", "plan/artifacts", success=False)
    spec = root / ci.SPEC
    source = spec.read_bytes()
    spec.write_bytes(source + b"\n")
    run("run", "--directory", "plan", "--shard", "2", success=False)
    assert not (root / "plan/artifacts/shard-2/receipt.json").exists()


def test_native_changed_environment_cannot_reuse_a_collection_descriptor(native_checkout):
    root, run, _environment = native_checkout
    run("plan", "--directory", "plan")
    run("run", "--directory", "plan", "--shard", "1", extra_env={"PYTEST_ADDOPTS": "-k test_one"}, success=False)
    assert not (root / "plan/artifacts/shard-1/receipt.json").exists()


@pytest.mark.parametrize("empty", [False, True])
def test_native_empty_or_entirely_skipped_suite_never_produces_a_plan(native_checkout, empty):
    root, run, environment = native_checkout
    for name in ("test_one.py", "test_two.py"):
        target = root / "tests" / name
        if empty:
            target.write_text("# no executable cases\n")
        else:
            target.write_text("import pytest\npytestmark = pytest.mark.skip(reason='fixture')\n" + target.read_text())
    for args in (
        ["add", "tests"],
        ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", *args], cwd=root, env=environment, check=True, capture_output=True)
    run("plan", "--directory", "plan", success=False)
    assert not (root / "plan/manifest.json").exists()


def test_generated_bundle_fingerprint_is_stable():
    manifest = (ROOT / "ci_shard_helper/MANIFEST.sha256").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == "6dfc297a2d58fb1e0c7fa344ee5556b637dbd4956dd1713b0d91bb7f5ca0040c"
