import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts import images, isolate, scan_images


def test_isolation_rejects_invalid_service_build_shape():
    model: dict[str, Any] = {"services": {"api": {"build": []}}}

    with pytest.raises(isolate.InvalidComposeService, match="service 'api': build must be a mapping") as caught:
        isolate.isolate_build_model(model, "example-job")

    assert caught.value.service == "api"
    assert caught.value.observed_type is list
    assert isinstance(caught.value, ValueError)


def test_isolation_reports_undefined_build_references():
    model = {"services": {"api": {"build": {"secrets": ["missing-key"]}}}}

    with pytest.raises(isolate.UndefinedComposeBuildReferences, match="undefined top-level secrets.*missing-key"):
        isolate.isolate_build_model(model, "example-job")


def test_prepare_rejects_unowned_namespace(tmp_path):
    with pytest.raises(isolate.InvalidComposeNamespace, match="ci- followed by 32 lowercase hex digits"):
        images.prepare(["docker", "compose"], tmp_path, "shared", [])


def test_compose_config_preserves_os_error_as_cause():
    failure = FileNotFoundError("docker")

    with (
        patch.object(images.subprocess, "run", side_effect=failure),
        pytest.raises(images.ComposeConfigError, match="could not resolve Compose config") as caught,
    ):
        images._compose_config(["docker", "compose"], [])

    assert caught.value.__cause__ is failure


def test_capture_cli_reports_the_state_path_from_an_isolated_interpreter(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-I", str(Path(images.__file__)), "capture", "--directory", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Compose isolation state must be an object" in result.stderr
    assert str(state_file) in result.stderr


def test_scan_reports_the_bad_id_position_without_printing_its_value(tmp_path):
    with pytest.raises(scan_images.InvalidScanImages, match="image ID at index 0 must be sha256") as caught:
        scan_images.scan(["not-an-image-id"], "HIGH", tmp_path / "ignore")

    assert caught.value.index == 0
    assert "not-an-image-id" not in str(caught.value)


def test_cleanup_rejects_tags_from_multiple_jobs():
    tags = [f"ci-{'a' * 32}:image-1", f"ci-{'b' * 32}:image-1"]

    with pytest.raises(images.InvalidCleanupTags, match="must belong to one job namespace"):
        images.cleanup(tags)
