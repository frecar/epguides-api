"""The deployed stack pulls a prebuilt image; only the build overlay builds it."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]


def _service(filename: str) -> dict:
    return yaml.safe_load((_ROOT / filename).read_text())["services"]["epguides-api"]


def test_prod_compose_pulls_a_prebuilt_image_and_never_builds() -> None:
    service = _service("docker-compose.prod.yml")
    assert "build" not in service
    image = service["image"]
    assert "${IMAGE_TAG" in image and "${IMAGE_REGISTRY" in image
    assert image.split("/", 1)[1].startswith("apps/epguides/api:")


def test_build_overlay_carries_the_security_epoch_arg() -> None:
    build = _service("docker-compose.build.yml")["build"]
    assert build["context"] == "."
    assert "OS_SECURITY_EPOCH" in build["args"]


def test_every_apt_stage_consumes_the_security_epoch() -> None:
    text = (_ROOT / "Dockerfile").read_text()
    assert text.count("ARG OS_SECURITY_EPOCH") == text.count("apt-get update") == 2
    assert text.count("${OS_SECURITY_EPOCH:?") == 2
