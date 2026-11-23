"""Build-only Compose model isolation for production image scans.

The caller must pass the resolved, profile-filtered output of
``docker compose config --format json``. Runtime configuration is deliberately
discarded so build secrets and services can be handled independently.
"""

from __future__ import annotations

import re
from copy import deepcopy
from enum import StrEnum
from typing import Any

_NAMESPACE_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")


class ComposeIsolationError(ValueError):
    pass


class ComposeModelIssue(StrEnum):
    MODEL = "resolved Compose model must be a mapping"
    SERVICES = "resolved Compose model must contain a non-empty services mapping"
    SECRETS = "resolved Compose model secrets must be a mapping"
    BUILDS = "resolved Compose model has no buildable services"


class InvalidComposeModel(ComposeIsolationError):
    def __init__(self, issue: ComposeModelIssue) -> None:
        self.issue = issue
        super().__init__(f"{issue}. Check the output of docker compose config.")


class ComposeServiceIssue(StrEnum):
    ENTRY = "malformed Compose service entry, expected a mapping under a non-empty name"
    BUILD = "build must be a mapping"
    BUILD_TAGS = "additional build tags would escape the isolated job namespace, remove build.tags"
    SECRETS = "build.secrets must be a list"
    SECRET_ENTRY = "malformed build secret, expected a name or a mapping with a non-empty source"
    CONTEXT_LIST = "build.additional_contexts must be a mapping or list"
    CONTEXT_ENTRY = "malformed build.additional_contexts entry, expected NAME=VALUE"
    CONTEXT_VALUE = "malformed additional context, expected a string"
    CONTEXT_TARGET = "empty service additional-context reference, expected service:NAME"
    CONTEXT_IMAGE = "service additional-context target must declare an image"
    IMAGE = "image must be a non-empty string"


class InvalidComposeService(ComposeIsolationError):
    def __init__(self, service: object, issue: ComposeServiceIssue, *, observed_type: type | None = None) -> None:
        self.service = service
        self.issue = issue
        self.observed_type = observed_type
        observed = f" (received {observed_type.__name__})" if observed_type is not None else ""
        super().__init__(f"service {service!r}: {issue}{observed}. Correct the service in the Compose file.")


class ComposeNamespaceFormat(StrEnum):
    IMAGE = "lowercase alphanumeric segments separated by '.', '_' or '-'"
    JOB = "ci- followed by 32 lowercase hex digits"


class InvalidComposeNamespace(ComposeIsolationError):
    def __init__(self, namespace: object, expected: ComposeNamespaceFormat) -> None:
        self.namespace = namespace
        self.expected = expected
        super().__init__(
            f"unsafe image namespace {namespace!r}: namespace must match {expected}. Use a job-owned name."
        )


class ComposeReferenceKind(StrEnum):
    SECRETS = "top-level secrets"
    CONTEXTS = "service additional contexts"


class UndefinedComposeBuildReferences(ComposeIsolationError):
    def __init__(self, kind: ComposeReferenceKind, names: list[str]) -> None:
        self.kind = kind
        self.names = names
        super().__init__(f"build references undefined {kind}: {names}. Declare each reference in the Compose file.")


def _build_secret_sources(build: dict[str, Any], service_name: str) -> set[str]:
    raw = build.get("secrets", [])
    if not isinstance(raw, list):
        raise InvalidComposeService(service_name, ComposeServiceIssue.SECRETS, observed_type=type(raw))
    sources: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            source = entry
        elif isinstance(entry, dict):
            source = entry.get("source")
        else:
            source = None
        if not isinstance(source, str) or not source:
            raise InvalidComposeService(service_name, ComposeServiceIssue.SECRET_ENTRY, observed_type=type(entry))
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
                raise InvalidComposeService(service_name, ComposeServiceIssue.CONTEXT_ENTRY, observed_type=type(entry))
            values.append(entry.split("=", 1)[1])
    else:
        raise InvalidComposeService(service_name, ComposeServiceIssue.CONTEXT_LIST, observed_type=type(raw))

    references: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise InvalidComposeService(service_name, ComposeServiceIssue.CONTEXT_VALUE, observed_type=type(value))
        if value.startswith("service:"):
            target = value.removeprefix("service:")
            if not target:
                raise InvalidComposeService(service_name, ComposeServiceIssue.CONTEXT_TARGET)
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
        raise InvalidComposeModel(ComposeModelIssue.MODEL)
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise InvalidComposeNamespace(namespace, ComposeNamespaceFormat.IMAGE)
    services = model.get("services")
    if not isinstance(services, dict) or not services:
        raise InvalidComposeModel(ComposeModelIssue.SERVICES)

    secrets = model.get("secrets", {})
    if not isinstance(secrets, dict):
        raise InvalidComposeModel(ComposeModelIssue.SECRETS)

    builds: dict[str, dict[str, Any]] = {}
    refs: set[str] = set()
    secret_sources: set[str] = set()
    for name, service in services.items():
        if not isinstance(name, str) or not name or not isinstance(service, dict):
            raise InvalidComposeService(name, ComposeServiceIssue.ENTRY, observed_type=type(service))
        build = service.get("build")
        if build is None:
            continue
        if not isinstance(build, dict):
            raise InvalidComposeService(name, ComposeServiceIssue.BUILD, observed_type=type(build))
        if build.get("tags"):
            raise InvalidComposeService(name, ComposeServiceIssue.BUILD_TAGS)
        builds[name] = build
        refs.update(_service_context_references(build, name))
        secret_sources.update(_build_secret_sources(build, name))

    if not builds:
        raise InvalidComposeModel(ComposeModelIssue.BUILDS)

    missing_secrets = sorted(secret_sources - set(secrets))
    if missing_secrets:
        raise UndefinedComposeBuildReferences(ComposeReferenceKind.SECRETS, missing_secrets)
    missing_contexts = sorted(refs - set(services))
    if missing_contexts:
        raise UndefinedComposeBuildReferences(ComposeReferenceKind.CONTEXTS, missing_contexts)

    tags_by_image: dict[tuple[str, str], str] = {}
    isolated: dict[str, Any] = {}
    service_tags: dict[str, str] = {}
    for name, service in services.items():
        if name in builds:
            original_image = service.get("image")
            if original_image is not None and (not isinstance(original_image, str) or not original_image):
                raise InvalidComposeService(name, ComposeServiceIssue.IMAGE, observed_type=type(original_image))
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
                raise InvalidComposeService(name, ComposeServiceIssue.CONTEXT_IMAGE, observed_type=type(image))
            kept = {"image": image}
            for key in ("platform", "profiles"):
                if key in service:
                    kept[key] = deepcopy(service[key])
            isolated[name] = kept

    result: dict[str, Any] = {}
    for key in ("name", "version"):
        if key in model:
            result[key] = deepcopy(model[key])
    result["services"] = isolated
    if secret_sources:
        result["secrets"] = {name: deepcopy(secrets[name]) for name in sorted(secret_sources)}
    return result, service_tags
