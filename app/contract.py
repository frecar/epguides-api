"""In-process OpenAPI route-contract engine (the PR regression-gate half).

Why this exists
---------------
A route can break (start returning ``500``) or its response shape can drift
away from the published OpenAPI schema while the process still boots and
``/health`` stays green. A health endpoint returning ``200`` proves the process
is alive, not that any real ``/shows`` or ``/health/*`` route still honours its
contract. Catching that *after* deploy (a scheduled external probe) is the
backstop; catching it *before merge* — failing the PR that introduces the
regression — is the shift-left gate this module powers.

What it does
------------
Given the app's generated OpenAPI document (``app.openapi()``), it:

1. **Enumerates the anonymous, read-only, parameter-free GET routes** safe to
   probe: a GET operation whose path has no path-template (``{...}``) and whose
   parameters (path- or query-level) are all optional. A required query param
   (e.g. ``/shows/search?query=``) is excluded because there is no safe
   synthetic value to fill it with — the same strict filter the deployed
   scheduled probe uses, so the two notions of "the anonymous contract" cannot
   diverge.
2. **Enforces a ``MUST_COVER`` floor**: every path in that tuple MUST still be
   present *and* eligible in the freshly-generated schema. A ``MUST_COVER``
   route silently disappearing from the schema (renamed, deleted, or made to
   require a param) FAILS the contract even though the schema itself is
   well-formed — the generated schema can never be the sole source of truth.
3. **For each probed route, validates the live response body** against the
   route's *declared* ``200`` response schema (local ``$ref`` resolved against
   the document's ``components``/``$defs``). HTTP-200-ness and schema-validity
   are tracked as separate facets so a ``500`` and a schema drift are
   distinguishable signals.

The HTTP transport is injected (a callable ``path -> (status_code, json_body)``)
so the same engine drives a FastAPI ``TestClient`` in CI *and* a real ``httpx``
client against a deployed URL, with zero engine change. The module is
dependency-light on purpose (``jsonschema`` only) so it stays a thin, vendorable
peer of the deployed reference engine rather than importing app internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import exceptions as jsonschema_exceptions

# The floor: every path here MUST stay an anonymous, no-required-param, no-path-
# template GET in the generated schema. These are the routes whose 500 / schema-
# drift / disappearance is the regression we refuse to let merge. Listing them
# explicitly is what makes "a route silently vanished from the schema" a hard
# failure rather than a quiet pass (the generated schema alone can't catch its
# own omission). Routes added to the public anonymous surface should be added
# here too.
MUST_COVER: tuple[str, ...] = (
    "/shows/",
    "/health",
    "/health/ready",
    "/health/llm",
    "/health/cache",
)

# Cap a single validation-error message so a deeply-nested mismatch can't
# produce an unreadable multi-kilobyte assertion failure.
VALIDATION_ERROR_MESSAGE_LIMIT = 400


@dataclass(frozen=True)
class RouteProbeResult:
    """Outcome of probing one anonymous GET route.

    ``status_ok`` — HTTP 200 with a JSON body (the "route 500s / serves an HTML
    error stub" signal). ``schema_ok`` — the JSON body validated against the
    route's declared 200 response schema, OR there was no usable schema to
    validate against (``schema_skipped`` set, ``schema_ok`` True by default — a
    route without a declared 200 schema is reported, not failed). A route's
    overall ``ok`` requires both.
    """

    route: str
    ok: bool
    status_ok: bool
    schema_ok: bool
    schema_skipped: bool
    http_status: int | None
    message: str


@dataclass(frozen=True)
class ContractResult:
    """Aggregate result: schema-eligibility + every probed route.

    ``schema_ok`` is False when a ``MUST_COVER`` route is missing/ineligible in
    the generated schema, or when zero eligible routes were discovered (an app
    that suddenly exposes no probeable anonymous route is itself a regression,
    never a silent pass).
    """

    schema_ok: bool
    schema_message: str
    probes: tuple[RouteProbeResult, ...] = ()

    @property
    def ok(self) -> bool:
        return self.schema_ok and all(probe.ok for probe in self.probes)

    def failures(self) -> list[str]:
        """Human-readable lines for every facet that failed (empty when ok)."""
        lines: list[str] = []
        if not self.schema_ok:
            lines.append(f"schema: {self.schema_message}")
        for probe in self.probes:
            if not probe.ok:
                lines.append(f"{probe.route}: {probe.message}")
        return lines


def eligible_get_routes(schema: dict[str, Any]) -> set[str]:
    """Paths whose GET operation is anonymous, read-only and parameter-free.

    Eligible = a GET operation with NO path-templating (``{...}``) and NO
    required parameter (declared at the path-item level or the operation level).
    Path-templated routes and required-query-param routes are excluded because
    there is no safe synthetic value to fill them with.
    """
    eligible: set[str] = set()
    for path, item in schema.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        operation = item.get("get")
        if not isinstance(operation, dict):
            continue
        if "{" in path or "}" in path:
            continue
        if _has_required_parameter(item, operation):
            continue
        eligible.add(path)
    return eligible


def _has_required_parameter(path_item: dict[str, Any], operation: dict[str, Any]) -> bool:
    # Parameters can live at the path-item level (shared across methods) or the
    # operation level. Any required one anywhere disqualifies the route.
    for source in (path_item.get("parameters"), operation.get("parameters")):
        if not isinstance(source, list):
            continue
        for param in source:
            if isinstance(param, dict) and param.get("required"):
                return True
    return False


def _extract_200_json_schema(schema: dict[str, Any], path: str) -> dict[str, Any] | None:
    operation = schema.get("paths", {}).get(path, {}).get("get", {})
    responses = operation.get("responses", {}) if isinstance(operation, dict) else {}
    response = None
    for key in ("200", "2XX"):
        candidate = responses.get(key)
        if isinstance(candidate, dict):
            response = candidate
            break
    if not isinstance(response, dict):
        return None
    content = response.get("content")
    if not isinstance(content, dict):
        return None
    json_content = content.get("application/json")
    if not isinstance(json_content, dict):
        return None
    response_schema = json_content.get("schema")
    return response_schema if isinstance(response_schema, dict) else None


def build_validator(schema: dict[str, Any], path: str) -> Draft202012Validator | None:
    """Validator for a route's declared 200 schema, or ``None`` if unusable.

    OpenAPI 3.1 response schemas ARE JSON Schema (draft 2020-12). Local
    ``#/components/...`` / ``#/$defs/...`` ``$ref``s are resolved by composing
    the route's response schema with the document's ``components`` + ``$defs``
    bag under a single root, so references resolve with no network fetch. A
    route with no usable JSON 200 schema, or whose composed schema is itself
    invalid, returns ``None`` — validation is skipped for it (reported as
    ``schema_skipped``, never a failure; the 200 check still applies).
    """
    response_schema = _extract_200_json_schema(schema, path)
    if response_schema is None:
        return None
    composed = dict(response_schema)
    components = schema.get("components")
    if isinstance(components, dict):
        composed.setdefault("components", components)
    defs = schema.get("$defs")
    if isinstance(defs, dict):
        composed.setdefault("$defs", defs)
    try:
        Draft202012Validator.check_schema(composed)
    except jsonschema_exceptions.SchemaError:
        return None
    return Draft202012Validator(composed)


def _first_validation_error(validator: Draft202012Validator, body: Any) -> str | None:
    errors = sorted(validator.iter_errors(body), key=lambda err: list(err.absolute_path))
    if not errors:
        return None
    first = errors[0]
    location = "/".join(str(part) for part in first.absolute_path) or "<root>"
    detail = f"{location}: {first.message}"
    return detail[:VALIDATION_ERROR_MESSAGE_LIMIT]


def _probe_route(
    path: str,
    *,
    fetch: Callable[[str], tuple[int, Any]],
    validator: Draft202012Validator | None,
) -> RouteProbeResult:
    schema_skipped = validator is None
    status_ok = False
    schema_ok = True
    http_status: int | None = None
    messages: list[str] = []
    try:
        http_status, body = fetch(path)
    except Exception as exc:  # transport blew up entirely
        return RouteProbeResult(
            route=path,
            ok=False,
            status_ok=False,
            schema_ok=False,
            schema_skipped=schema_skipped,
            http_status=None,
            message=f"{type(exc).__name__}: {exc}",
        )

    if http_status != 200:
        messages.append(f"HTTP {http_status}")
    elif body is None:
        # 200 but the transport could not decode a JSON body.
        messages.append("200 but non-JSON body")
    else:
        status_ok = True
        if validator is not None:
            error = _first_validation_error(validator, body)
            if error is not None:
                schema_ok = False
                messages.append(f"schema: {error}")

    ok = status_ok and schema_ok
    if ok and not messages:
        messages.append("200 (schema skipped)" if schema_skipped else "200 + schema ok")
    return RouteProbeResult(
        route=path,
        ok=ok,
        status_ok=status_ok,
        schema_ok=schema_ok,
        schema_skipped=schema_skipped,
        http_status=http_status,
        message="; ".join(messages),
    )


def run_contract(
    schema: dict[str, Any],
    fetch: Callable[[str], tuple[int, Any]],
    *,
    must_cover: tuple[str, ...] = MUST_COVER,
    skip_routes: frozenset[str] = frozenset(),
) -> ContractResult:
    """Run the anonymous GET contract against ``schema`` using ``fetch``.

    ``fetch(path) -> (status_code, json_body_or_None)`` performs the request and
    decodes the JSON body (returning ``None`` for a non-JSON body). Injecting it
    lets the same engine run in-process (FastAPI ``TestClient``) for the CI gate
    and over the wire (``httpx``) for a deployed probe.

    ``skip_routes`` excludes paths that are eligible by shape but should not be
    probed (e.g. a route known-expensive or side-effecting on GET). It must not
    overlap ``must_cover`` — skipping a floor route would silently drop coverage.
    An empty default ``frozenset()`` is safe as a default argument because it is
    immutable.
    """
    eligible = eligible_get_routes(schema)

    missing_cover = sorted(path for path in must_cover if path not in eligible)
    if missing_cover:
        return ContractResult(
            schema_ok=False,
            schema_message=(
                "MUST_COVER routes missing or no longer anonymous-GET-eligible "
                f"in the generated schema: {', '.join(missing_cover)}"
            ),
        )

    overlap = sorted(set(must_cover) & skip_routes)
    if overlap:
        return ContractResult(
            schema_ok=False,
            schema_message=f"skip_routes must not include MUST_COVER routes: {', '.join(overlap)}",
        )

    probeable = sorted(path for path in eligible if path not in skip_routes)
    if not probeable:
        return ContractResult(
            schema_ok=False,
            schema_message="schema generated but zero anonymous no-required-param GET routes were discovered",
        )

    probes = tuple(_probe_route(path, fetch=fetch, validator=build_validator(schema, path)) for path in probeable)
    return ContractResult(
        schema_ok=True,
        schema_message=f"schema ok; {len(probes)} anonymous GET route(s) probed",
        probes=probes,
    )
