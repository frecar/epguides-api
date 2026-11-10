#!/usr/bin/env python3
"""Create isolated Compose build tags and resolve them to immutable image IDs."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

if __package__:
    from .isolate import _build_secret_sources, _service_context_references, isolate_build_model
else:
    # Direct execution resolves the co-published sibling, independently of cwd.
    spec = importlib.util.spec_from_file_location("compose_build_isolate", Path(__file__).with_name("isolate.py"))
    if spec is None or spec.loader is None:
        raise ImportError("missing co-published Compose isolation helper")
    isolation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolation)
    _build_secret_sources = isolation._build_secret_sources
    _service_context_references = isolation._service_context_references
    isolate_build_model = isolation.isolate_build_model

_JOB_NAMESPACE_RE = re.compile(r"ci-[a-f0-9]{32}\Z")
_IMAGE_TAG_RE = re.compile(r"(?P<namespace>ci-[a-f0-9]{32}):image-[1-9][0-9]*\Z")
_IMAGE_ID_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_CONFIG_TIMEOUT_SECONDS = 60
_INSPECT_TIMEOUT_SECONDS = 20


def _validate_compose_args(prefix: list[str], profiles: list[str]) -> None:
    if not isinstance(prefix, list) or len(prefix) < 2 or prefix[:2] != ["docker", "compose"]:
        raise ValueError("Compose prefix must begin with docker compose")
    if any(not isinstance(part, str) or not part for part in prefix):
        raise ValueError("Compose prefix must contain only non-empty strings")
    if not isinstance(profiles, list) or any(not isinstance(item, str) or not item for item in profiles):
        raise ValueError("Compose profiles must be a list of non-empty strings")


def _profile_args(profiles: list[str]) -> list[str]:
    return [part for profile in profiles for part in ("--profile", profile)]


def _compose_config(prefix: list[str], profiles: list[str]) -> dict[str, Any]:
    command = [*prefix, *_profile_args(profiles), "config", "--no-env-resolution", "--format", "json"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=_CONFIG_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("could not resolve Compose config") from exc
    if result.returncode != 0:
        raise ValueError(f"Compose config exited with status {result.returncode}")
    try:
        model = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Compose config returned invalid JSON") from exc
    if not isinstance(model, dict):
        raise ValueError("Compose config must return a JSON object")
    return model


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        with suppress(OSError):
            path.unlink()
        raise


def _assert_round_trip(
    original: dict[str, Any],
    reparsed: dict[str, Any],
    service_tags: dict[str, str],
) -> None:
    original_services = original.get("services")
    actual_services = reparsed.get("services")
    if not isinstance(original_services, dict) or not isinstance(actual_services, dict):
        raise ValueError("Compose config services must be mappings")

    expected_names = set(service_tags)
    # isolate_build_model retains image-only services used by service: contexts.
    for name in service_tags:
        build = original_services[name].get("build")
        if isinstance(build, dict):
            expected_names.update(_service_context_references(build, name))
    if set(actual_services) != expected_names:
        raise ValueError("isolated Compose round trip changed the retained service set")

    for name in expected_names:
        before = original_services.get(name)
        after = actual_services.get(name)
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError(f"isolated Compose round trip lost retained service {name!r}")
        if before.get("build") != after.get("build"):
            raise ValueError(f"isolated Compose round trip changed build inputs for {name!r}")
        for key in ("platform", "profiles"):
            if before.get(key) != after.get(key) or (key in before) != (key in after):
                raise ValueError(f"isolated Compose round trip changed {key} for {name!r}")
        expected_image = service_tags.get(name, before.get("image"))
        if after.get("image") != expected_image:
            raise ValueError(f"isolated Compose round trip changed image for {name!r}")

    original_secrets = original.get("secrets", {})
    actual_secrets = reparsed.get("secrets", {})
    if not isinstance(original_secrets, dict) or not isinstance(actual_secrets, dict):
        raise ValueError("Compose config secrets must be mappings")
    used_secrets: set[str] = set()
    for name in service_tags:
        build = original_services[name].get("build")
        if isinstance(build, dict):
            used_secrets.update(_build_secret_sources(build, name))
    expected_secrets = {name: original_secrets[name] for name in used_secrets if name in original_secrets}
    if set(expected_secrets) != used_secrets or actual_secrets != expected_secrets:
        raise ValueError("isolated Compose round trip changed used build secret definitions")


def prepare(prefix: list[str], directory: Path, namespace: str, profiles: list[str]) -> dict[str, Any]:
    """Resolve production Compose, write an isolated private model and state."""
    _validate_compose_args(prefix, profiles)
    if not isinstance(namespace, str) or not _JOB_NAMESPACE_RE.fullmatch(namespace):
        raise ValueError("namespace must match ci- followed by 32 lowercase hex digits")
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError("Compose isolation directory must already exist")
    if directory.stat().st_mode & 0o077:
        raise ValueError("Compose isolation directory must be private")
    compose_path = directory / "compose.json"
    state_path = directory / "state.json"
    if compose_path.exists() or state_path.exists():
        raise FileExistsError("Compose isolation files already exist")

    original = _compose_config(prefix, profiles)
    isolated, service_tags = isolate_build_model(original, namespace)
    isolated["name"] = namespace
    _write_private_json(compose_path, isolated)

    isolated_prefix = [*prefix[:2], "-f", str(compose_path), *_profile_args(profiles)]
    try:
        reparsed = _compose_config(isolated_prefix, profiles=[])
        _assert_round_trip(original, reparsed, service_tags)
    except BaseException:
        compose_path.unlink(missing_ok=True)
        raise

    state = {
        "namespace": namespace,
        "prefix": isolated_prefix,
        "service_tags": service_tags,
    }
    try:
        _write_private_json(state_path, state)
    except BaseException:
        compose_path.unlink(missing_ok=True)
        raise
    return state


def capture(directory: Path) -> dict[str, list[str]]:
    """Inspect only job-unique tags and return their immutable image IDs."""
    state_path = Path(directory) / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read Compose isolation state") from exc
    if not isinstance(state, dict):
        raise ValueError("Compose isolation state must be an object")
    namespace = state.get("namespace")
    service_tags = state.get("service_tags")
    prefix = state.get("prefix")
    if not isinstance(namespace, str) or not _JOB_NAMESPACE_RE.fullmatch(namespace):
        raise ValueError("Compose isolation state has an invalid job namespace")
    if not isinstance(prefix, list) or any(not isinstance(item, str) or not item for item in prefix):
        raise ValueError("Compose isolation state has an invalid prefix")
    if not isinstance(service_tags, dict) or not service_tags:
        raise ValueError("Compose isolation state has no image tags")

    tag_values = list(service_tags.values())
    for tag in tag_values:
        match = _IMAGE_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
        if match is None or match.group("namespace") != namespace:
            raise ValueError("Compose isolation state contains an invalid isolated image tag")
    unique_tags = list(dict.fromkeys(tag_values))

    image_ids: list[str] = []
    for tag in unique_tags:
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
                capture_output=True,
                text=True,
                check=False,
                timeout=_INSPECT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"could not inspect isolated image {tag}") from exc
        if result.returncode != 0:
            raise ValueError(f"could not inspect isolated image {tag} (status {result.returncode})")
        image_id = result.stdout.strip()
        if not _IMAGE_ID_RE.fullmatch(image_id):
            raise ValueError(f"Docker returned an invalid image ID for {tag}")
        if image_id not in image_ids:
            image_ids.append(image_id)
    return {"image-tags": unique_tags, "image-ids": image_ids}


def cleanup(tags: object) -> int:
    """Remove existing job-owned tags, preserving shared parent layers."""
    if not isinstance(tags, list):
        raise ValueError("image tags must be a JSON list")
    if not tags:
        return 0
    matches = [_IMAGE_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None for tag in tags]
    if any(match is None for match in matches):
        raise ValueError("cleanup accepts only job-owned image tags")
    namespaces = {match.group("namespace") for match in matches if match is not None}
    if len(namespaces) != 1:
        raise ValueError("cleanup tags must belong to one job namespace")
    namespace = next(iter(namespaces))
    result = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}", "--filter", f"reference={namespace}:image-*"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    available = set(result.stdout.splitlines())
    owned = [tag for tag in dict.fromkeys(tags) if tag in available]
    if owned:
        subprocess.run(["docker", "image", "rm", "--no-prune", *owned], check=True, timeout=20)
    return 0


def _read_json_list(path: Path, label: str) -> list[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label} JSON") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} JSON must be a list of non-empty strings")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--directory", type=Path, required=True)
    prepare_parser.add_argument("--namespace", required=True)
    prepare_parser.add_argument("--prefix-json", type=Path, required=True)
    prepare_parser.add_argument("--profiles-json", type=Path, required=True)
    prefix_parser = commands.add_parser("prefix")
    prefix_parser.add_argument("--directory", type=Path, required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--directory", type=Path, required=True)
    cleanup_parser = commands.add_parser("cleanup")
    cleanup_parser.add_argument("--tags-json", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "prepare":
            prefix = _read_json_list(args.prefix_json, "prefix")
            profiles = _read_json_list(args.profiles_json, "profiles")
            state = prepare(prefix, args.directory, args.namespace, profiles)
            output: Any = {"prefix": state["prefix"], "service_tags": state["service_tags"]}
        elif args.command == "prefix":
            state = json.loads((args.directory / "state.json").read_text(encoding="utf-8"))
            output = state["prefix"]
        elif args.command == "cleanup":
            return cleanup(json.loads(args.tags_json))
        else:
            output = capture(args.directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"compose image isolation: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
