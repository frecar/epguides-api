"""API contract regression-gate (runs inside the required ``Test`` CI job).

This is the per-PR shift-left half of the route-contract story: it boots the
real FastAPI app in-process (``TestClient``, no deploy, no network egress) and
asserts every anonymous, no-required-param GET route still returns ``200`` with
a body that validates against its *declared* OpenAPI ``200`` schema. A route
that starts ``500``ing, returns a non-JSON/HTML error stub, drifts its response
shape away from the published schema, or disappears from the schema entirely
FAILS this test — and therefore the PR — before it can merge.

Hermetic by construction: the dependency-bearing routes (``/shows/`` →
upstream scrape + Redis; ``/health/ready`` → Redis round-trip + upstream
freshness; ``/health/cache`` → Redis stats) have their service/dependency seams
mocked to deterministic-healthy values, using the same patch targets the rest
of the suite uses. So the gate exercises the full FastAPI path (routing, query
parsing, ``response_model`` serialization, the OpenAPI schema generation) with
zero reliance on a warmed cache or the public internet — a clean, fast, repeatable
contract check rather than a flaky live smoke.

The engine itself (``app.contract_engine``, a deliberate vendored copy of the
shared OpenAPI contract engine — this public repo cannot take a private
dependency) is a thin in-process peer of the deployed scheduled probe: same
anonymous-GET eligibility filter, same ``MUST_COVER`` floor (owned by
``app.contract``), same declared-200-schema validation — so the two surfaces
share one notion of "the contract" and cannot silently diverge.
"""

import time
from collections.abc import Iterator
from contextlib import ExitStack
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.contract import MUST_COVER
from app.contract_engine import (
    ContractResult,
    RouteProbeResult,
    assert_no_document_level_security,
    build_validator,
    eligible_get_routes,
    run_contract,
)
from app.main import app
from app.models.schemas import create_show_schema


def _make_fetch(client: TestClient):
    """Adapt a ``TestClient`` to the engine's ``fetch(path) -> (status, body)``.

    The body is decoded as JSON; a non-JSON 200 body surfaces as ``None`` so the
    engine reports it as a contract failure (the "200 but HTML error stub" class).
    """

    def fetch(path: str) -> tuple[int, Any]:
        response = client.get(path)
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        return response.status_code, body

    return fetch


@pytest.fixture
def hermetic_app() -> Iterator[TestClient]:
    """A ``TestClient`` with every anonymous-route dependency mocked healthy.

    This makes the contract probe deterministic and network-free while still
    running the real route handlers + FastAPI serialization. Patch targets match
    the established conventions elsewhere in the suite (the route reads
    ``show_service.get_shows_page``; ``app.main`` imports the cache helpers by
    name, so they are patched on ``app.main``).
    """
    mock_shows = [
        create_show_schema(epguides_key="contract-1", title="Contract Test Show 1", network="Net A"),
        create_show_schema(epguides_key="contract-2", title="Contract Test Show 2", network="Net B"),
    ]
    mock_cache_stats: dict[str, Any] = {
        "status": "connected",
        "total_keys": 2,
        "cached_items": {"shows": 2, "episodes": 0, "seasons": 0, "searches": 0},
    }
    with ExitStack() as stack:
        # /shows/ — deterministic show page, no upstream scrape, no Redis.
        stack.enter_context(
            patch(
                "app.services.show_service.get_shows_page",
                new=AsyncMock(return_value=(mock_shows, len(mock_shows))),
            )
        )
        # /health/ready — Redis round-trip healthy + a fresh upstream success.
        stack.enter_context(patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(True, 1.0))))
        stack.enter_context(patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=time.time() - 60)))
        # /health/cache — deterministic stats, no live Redis.
        stack.enter_context(patch("app.main.get_cache_stats", new=AsyncMock(return_value=mock_cache_stats)))
        with TestClient(app) as client:
            yield client


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


def test_api_contract_holds_for_all_anonymous_get_routes(hermetic_app: TestClient) -> None:
    """Every anonymous GET route: HTTP 200 + body matches its declared schema.

    This is the regression gate. A 500, a schema drift, a non-JSON body, or a
    MUST_COVER route vanishing from the schema all fail here (and so fail the PR).
    """
    schema = app.openapi()
    # The vendored engine has no app-specific default: the floor is passed
    # explicitly so it can never silently inherit another app's.
    result = run_contract(schema, _make_fetch(hermetic_app), must_cover=MUST_COVER)
    assert result.ok, "API contract regression:\n" + "\n".join(result.failures())


def test_must_cover_routes_are_all_eligible_in_the_generated_schema() -> None:
    """Each MUST_COVER path is present + anonymous-GET-eligible in the schema.

    Guards the "a public route was renamed / deleted / made to require a param,
    but nobody updated the contract floor" class — independent of any live probe.
    """
    eligible = eligible_get_routes(app.openapi())
    missing = sorted(path for path in MUST_COVER if path not in eligible)
    assert not missing, f"MUST_COVER routes no longer anonymous-GET-eligible: {missing}"


def test_search_route_is_excluded_required_query_param() -> None:
    """/shows/search has a required ``query`` param, so it must NOT be probed.

    Confirms the eligibility filter excludes required-param routes (there is no
    safe synthetic value to fill ``query`` with) — a guard against the filter
    silently widening to probe routes it cannot satisfy.
    """
    eligible = eligible_get_routes(app.openapi())
    assert "/shows/search" not in eligible
    # Path-templated routes are excluded for the same reason.
    assert "/shows/{epguides_key}" not in eligible


# ---------------------------------------------------------------------------
# Engine unit coverage (failure modes the gate above never triggers on a
# healthy app, but which MUST work when a real regression lands).
# ---------------------------------------------------------------------------

_MINIMAL_SCHEMA: dict[str, Any] = {
    "openapi": "3.1.0",
    "paths": {
        "/ok": {
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
                            }
                        }
                    }
                }
            }
        }
    },
}


def test_run_contract_flags_a_500() -> None:
    result = run_contract(
        _MINIMAL_SCHEMA,
        lambda _path: (500, {"detail": "boom"}),
        must_cover=("/ok",),
    )
    assert not result.ok
    assert any("HTTP 500" in line for line in result.failures())


def test_run_contract_flags_a_schema_drift() -> None:
    # 200 but the body omits the required field -> schema failure.
    result = run_contract(
        _MINIMAL_SCHEMA,
        lambda _path: (200, {"unexpected": "value"}),
        must_cover=("/ok",),
    )
    assert not result.ok
    assert any("schema" in line for line in result.failures())


def test_run_contract_passes_a_valid_body() -> None:
    result = run_contract(
        _MINIMAL_SCHEMA,
        lambda _path: (200, {"a": "hello"}),
        must_cover=("/ok",),
    )
    assert result.ok
    assert result.failures() == []


def test_run_contract_flags_non_json_200() -> None:
    result = run_contract(
        _MINIMAL_SCHEMA,
        lambda _path: (200, None),
        must_cover=("/ok",),
    )
    assert not result.ok
    assert any("non-JSON" in line for line in result.failures())


def test_run_contract_flags_transport_exception() -> None:
    def boom(_path: str) -> tuple[int, Any]:
        raise RuntimeError("connection refused")

    result = run_contract(_MINIMAL_SCHEMA, boom, must_cover=("/ok",))
    assert not result.ok
    assert any("RuntimeError" in line for line in result.failures())


def test_run_contract_flags_missing_must_cover_route() -> None:
    result = run_contract(_MINIMAL_SCHEMA, lambda _p: (200, {"a": "x"}), must_cover=("/gone",))
    assert not result.ok
    assert any("MUST_COVER" in line for line in result.failures())


def test_run_contract_flags_zero_eligible_routes() -> None:
    result = run_contract({"openapi": "3.1.0", "paths": {}}, lambda _p: (200, {}), must_cover=())
    assert not result.ok
    assert any("zero anonymous" in line for line in result.failures())


def test_run_contract_rejects_skip_of_must_cover_route() -> None:
    result = run_contract(
        _MINIMAL_SCHEMA,
        lambda _p: (200, {"a": "x"}),
        must_cover=("/ok",),
        skip_routes=frozenset({"/ok"}),
    )
    assert not result.ok
    assert any("skip_routes must not include MUST_COVER" in line for line in result.failures())


def test_run_contract_honours_skip_routes_for_non_floor_route() -> None:
    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "paths": {
            "/keep": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}}},
            "/drop": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}}},
        },
    }
    probed: list[str] = []

    def fetch(path: str) -> tuple[int, Any]:
        probed.append(path)
        return 200, {}

    result = run_contract(schema, fetch, must_cover=("/keep",), skip_routes=frozenset({"/drop"}))
    assert result.ok
    assert probed == ["/keep"]


def test_eligible_routes_skip_required_param_and_templated_paths() -> None:
    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "paths": {
            "/free": {"get": {"responses": {"200": {}}}},
            "/needs-q": {
                "get": {
                    "parameters": [{"name": "q", "in": "query", "required": True}],
                    "responses": {"200": {}},
                }
            },
            "/shared-required": {
                "parameters": [{"name": "p", "in": "query", "required": True}],
                "get": {"responses": {"200": {}}},
            },
            "/item/{id}": {"get": {"responses": {"200": {}}}},
            "/post-only": {"post": {"responses": {"200": {}}}},
        },
    }
    assert eligible_get_routes(schema) == {"/free"}


def test_eligible_routes_ignore_malformed_path_items() -> None:
    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "paths": {
            "/bad-item": ["not", "a", "dict"],
            "/no-get": {"get": "not-a-dict"},
            "/good": {"get": {"responses": {"200": {}}}},
        },
    }
    assert eligible_get_routes(schema) == {"/good"}


def test_build_validator_returns_none_without_a_json_200_schema() -> None:
    # No content at all.
    assert build_validator({"paths": {"/x": {"get": {"responses": {"200": {}}}}}, "$defs": {}}, "/x") is None
    # 200 present but no application/json schema.
    schema: dict[str, Any] = {
        "paths": {"/x": {"get": {"responses": {"200": {"content": {"text/plain": {}}}}}}},
    }
    assert build_validator(schema, "/x") is None


def test_build_validator_resolves_component_refs() -> None:
    schema: dict[str, Any] = {
        "components": {
            "schemas": {"Item": {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}}
        },
        "paths": {
            "/x": {
                "get": {
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}}}
                    }
                }
            }
        },
    }
    validator = build_validator(schema, "/x")
    assert validator is not None
    assert list(validator.iter_errors({"a": "ok"})) == []
    assert list(validator.iter_errors({}))  # missing required 'a'


def test_build_validator_returns_none_on_invalid_schema() -> None:
    schema: dict[str, Any] = {
        "paths": {"/x": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": 123}}}}}}}},
    }
    # A type value of 123 is not a valid JSON Schema -> unusable -> skipped.
    assert build_validator(schema, "/x") is None


def test_build_validator_accepts_2xx_range_key() -> None:
    schema: dict[str, Any] = {
        "paths": {
            "/x": {"get": {"responses": {"2XX": {"content": {"application/json": {"schema": {"type": "object"}}}}}}}
        },
    }
    assert build_validator(schema, "/x") is not None


def test_build_validator_returns_none_without_a_200_response() -> None:
    # Operation declares only a 404 — no 200/2XX response to validate against.
    schema: dict[str, Any] = {
        "paths": {"/x": {"get": {"responses": {"404": {"content": {"application/json": {"schema": {}}}}}}}},
    }
    assert build_validator(schema, "/x") is None


def test_build_validator_resolves_top_level_defs_ref() -> None:
    # OpenAPI 3.1 allows $defs at the document root; the composed validation
    # schema must carry them so a #/$defs/... $ref resolves.
    schema: dict[str, Any] = {
        "$defs": {"Item": {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}},
        "paths": {
            "/x": {
                "get": {"responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/$defs/Item"}}}}}}
            }
        },
    }
    validator = build_validator(schema, "/x")
    assert validator is not None
    assert list(validator.iter_errors({"a": "ok"})) == []
    assert list(validator.iter_errors({}))  # missing required 'a'


def test_contract_result_helpers() -> None:
    ok_probe = RouteProbeResult(
        route="/x", ok=True, status_ok=True, schema_ok=True, schema_skipped=False, http_status=200, message="ok"
    )
    bad_probe = RouteProbeResult(
        route="/y", ok=False, status_ok=False, schema_ok=True, schema_skipped=False, http_status=500, message="HTTP 500"
    )
    healthy = ContractResult(schema_ok=True, schema_message="ok", probes=(ok_probe,))
    assert healthy.ok
    assert healthy.failures() == []
    broken = ContractResult(schema_ok=True, schema_message="ok", probes=(ok_probe, bad_probe))
    assert not broken.ok
    assert broken.failures() == ["/y: HTTP 500"]


def test_probe_skips_schema_validation_when_no_declared_schema() -> None:
    # A route with no usable 200 JSON schema is probed for 200-ness only.
    schema: dict[str, Any] = {"openapi": "3.1.0", "paths": {"/x": {"get": {"responses": {"200": {}}}}}}
    result = run_contract(schema, lambda _p: (200, {"anything": True}), must_cover=("/x",))
    assert result.ok
    assert result.probes[0].schema_skipped is True


# ---------------------------------------------------------------------------
# Seeded violations against the LIVE schema (the cutover acceptance bar: the
# vendored engine must still FAIL the gate the way the pre-cutover engine did,
# not merely pass a healthy app).
# ---------------------------------------------------------------------------


def test_seeded_must_cover_deletion_fails_the_vendored_gate(hermetic_app: TestClient) -> None:
    """A MUST_COVER route silently vanishing from the live schema fails."""
    schema = deepcopy(app.openapi())
    del schema["paths"]["/shows/"]
    result = run_contract(schema, _make_fetch(hermetic_app), must_cover=MUST_COVER)
    assert not result.ok
    assert any("MUST_COVER" in line and "/shows/" in line for line in result.failures())


def test_seeded_schema_violation_body_fails_the_vendored_gate(hermetic_app: TestClient) -> None:
    """A live route serving a schema-violating body fails the vendored gate."""
    live_fetch = _make_fetch(hermetic_app)

    def fetch(path: str) -> tuple[int, Any]:
        status, body = live_fetch(path)
        if path == "/health":
            # /health declares an object schema — a top-level array cannot validate.
            return status, ["not", "an", "object"]
        return status, body

    result = run_contract(app.openapi(), fetch, must_cover=MUST_COVER)
    assert not result.ok
    assert any("/health" in line and "schema" in line for line in result.failures())


# ---------------------------------------------------------------------------
# Inherited engine behaviours (pins for the three deliberate supersets the
# vendored engine carries over the pre-cutover local one).
# ---------------------------------------------------------------------------


def test_eligible_routes_exclude_operation_level_authed_routes() -> None:
    """A GET operation carrying ``security`` is NOT anonymous, NOT probed."""
    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "paths": {
            "/free": {"get": {"responses": {"200": {}}}},
            "/authed": {"get": {"security": [{"bearerAuth": []}], "responses": {"200": {}}}},
            "/explicitly-open": {"get": {"security": [], "responses": {"200": {}}}},
        },
    }
    assert eligible_get_routes(schema) == {"/free", "/explicitly-open"}


def test_document_level_security_fails_loud() -> None:
    """A top-level ``security`` requirement raises instead of inverting."""
    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "security": [{"bearerAuth": []}],
        "paths": {"/x": {"get": {"responses": {"200": {}}}}},
    }
    with pytest.raises(AssertionError, match="top-level `security`"):
        assert_no_document_level_security(schema)
    with pytest.raises(AssertionError, match="top-level `security`"):
        run_contract(schema, lambda _p: (200, {}), must_cover=("/x",))


def test_build_validator_accepts_integer_200_key() -> None:
    """Some generators key responses under integer ``200`` — still validated."""
    schema: dict[str, Any] = {
        "paths": {
            "/x": {"get": {"responses": {200: {"content": {"application/json": {"schema": {"type": "object"}}}}}}}
        },
    }
    assert build_validator(schema, "/x") is not None
