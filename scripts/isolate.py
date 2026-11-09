"""Build-only Compose model isolation for production image scans.

The caller must pass the resolved, profile-filtered output of
``docker compose config --format json``. Runtime configuration is deliberately
discarded so build secrets and services can be handled independently.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

_NAMESPACE_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")


def _build_secret_sources(build: dict[str, Any], service_name: str) -> set[str]:
    raw = build.get("secrets", [])
    if not isinstance(raw, list):
        raise ValueError(f"service {service_name!r}: build.secrets must be a list")
    sources: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            source = entry
        elif isinstance(entry, dict):
            source = entry.get("source")
        else:
            source = None
        if not isinstance(source, str) or not source:
            raise ValueError(f"service {service_name!r}: malformed build secret {entry!r}")
        sources.add(source)
    return sources


def _service_context_references(build: dict[str, Any], service_name: str) -> set[str]:
    raw = build.get("additional_contexts", {})
    if isinstance(raw, dict):
        values = list(raw.values())
    elif isinstance(raw, list):
        values = []
        for entry in raw:
            if not isinstance(entry, str) or "=" not in entry:
                raise ValueError(f"service {service_name!r}: malformed build.additional_contexts entry {entry!r}")
            values.append(entry.split("=", 1)[1])
    else:
        raise ValueError(f"service {service_name!r}: build.additional_contexts must be a mapping or list")

    references: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"service {service_name!r}: malformed additional context {value!r}")
        if value.startswith("service:"):
            target = value.removeprefix("service:")
            if not target:
                raise ValueError(f"service {service_name!r}: empty service additional-context reference")
            references.add(target)
    return references


def isolate_build_model(model: dict[str, Any], namespace: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Keep only Compose build inputs and assign unique scan image tags.

    Explicit aliases for one original image share a generated tag; services
    without an explicit image remain distinct. Image-only services referenced
    as ``service:NAME`` additional contexts are retained as minimal image
    declarations so Compose can resolve those references.
    """
    if not isinstance(model, dict):
        raise ValueError("resolved Compose model must be a mapping")
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise ValueError(f"unsafe image namespace {namespace!r}")
    services = model.get("services")
    if not isinstance(services, dict) or not services:
        raise ValueError("resolved Compose model must contain a non-empty services mapping")

    secrets = model.get("secrets", {})
    if not isinstance(secrets, dict):
        raise ValueError("resolved Compose model secrets must be a mapping")

    builds: dict[str, dict[str, Any]] = {}
    refs: set[str] = set()
    secret_sources: set[str] = set()
    for name, service in services.items():
        if not isinstance(name, str) or not name or not isinstance(service, dict):
            raise ValueError(f"malformed Compose service entry {name!r}")
        build = service.get("build")
        if build is None:
            continue
        if not isinstance(build, dict):
            raise ValueError(f"service {name!r}: build must be a mapping")
        if build.get("tags"):
            raise ValueError(f"service {name!r}: additional build tags would escape the isolated job namespace")
        builds[name] = build
        refs.update(_service_context_references(build, name))
        secret_sources.update(_build_secret_sources(build, name))

    if not builds:
        raise ValueError("resolved Compose model has no buildable services")

    missing_secrets = sorted(secret_sources - set(secrets))
    if missing_secrets:
        raise ValueError(f"build references undefined top-level secrets: {missing_secrets}")
    missing_contexts = sorted(refs - set(services))
    if missing_contexts:
        raise ValueError(f"build references undefined service additional contexts: {missing_contexts}")

    tags_by_image: dict[tuple[str, str], str] = {}
    isolated: dict[str, Any] = {}
    service_tags: dict[str, str] = {}
    for name, service in services.items():
        if name in builds:
            original_image = service.get("image")
            if original_image is not None and (not isinstance(original_image, str) or not original_image):
                raise ValueError(f"service {name!r}: image must be a non-empty string")
            image_key = ("explicit", original_image) if original_image is not None else ("implicit", name)
            if image_key not in tags_by_image:
                tags_by_image[image_key] = f"{namespace}:image-{len(tags_by_image) + 1}"
            tag = tags_by_image[image_key]
            service_tags[name] = tag
            kept: dict[str, Any] = {"image": tag, "build": deepcopy(builds[name])}
            for key in ("platform", "profiles"):
                if key in service:
                    kept[key] = deepcopy(service[key])
            isolated[name] = kept
        elif name in refs:
            image = service.get("image")
            if not isinstance(image, str) or not image:
                raise ValueError(f"service additional-context target {name!r} must declare an image")
            kept = {"image": image}
            for key in ("platform", "profiles"):
                if key in service:
                    kept[key] = deepcopy(service[key])
            isolated[name] = kept

    # Preserve only top-level metadata relevant to Compose project identity
    # and the declarations required by the retained build graph.
    result: dict[str, Any] = {}
    for key in ("name", "version"):
        if key in model:
            result[key] = deepcopy(model[key])
    result["services"] = isolated
    if secret_sources:
        result["secrets"] = {name: deepcopy(secrets[name]) for name in sorted(secret_sources)}
    # Compose config already escapes literal dollars for a subsequent parse.
    # Preserve its output verbatim; escaping again changes build arguments.
    return result, service_tags
