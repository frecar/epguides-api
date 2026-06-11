"""
Tests for main application module.

Tests lifespan, exception handlers, and health endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.exceptions import EpguidesAPIException, ExternalServiceError
from app.main import app

client = TestClient(app)


# =============================================================================
# Health Endpoint Tests
# =============================================================================


def test_health_check():
    """Test basic health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_health_llm_without_config():
    """Test LLM health check without API key configured."""
    with patch("app.main.settings") as mock_settings:
        mock_settings.LLM_ENABLED = False
        mock_settings.LLM_API_URL = None
        mock_settings.LLM_MODEL_NAME = "auto"
        mock_settings.LLM_ALLOW_EXTERNAL = False
        response = client.get("/health/llm")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_cache_health_endpoint():
    """Test cache health endpoint returns stats."""
    mock_stats = {
        "status": "connected",
        "total_keys": 10,
        "cached_items": {"shows": 5, "episodes": 3, "seasons": 2},
    }
    with patch("app.main.get_cache_stats", return_value=mock_stats):
        response = client.get("/health/cache")
        assert response.status_code == 200


# =============================================================================
# Exception Handler Tests
# =============================================================================


def test_epguides_exception_handler():
    """Test custom exception handler for EpguidesAPIException."""

    # Create a test route that raises our exception
    @app.get("/test-epguides-error")
    async def raise_epguides_error():
        raise EpguidesAPIException("Test error")

    response = client.get("/test-epguides-error")
    assert response.status_code == 500
    data = response.json()
    assert "internal error" in data["detail"].lower()
    assert "request_id" in data


def test_external_service_exception_handler():
    """Test custom exception handler for ExternalServiceError."""

    @app.get("/test-external-error")
    async def raise_external_error():
        raise ExternalServiceError("External service failed")

    response = client.get("/test-external-error")
    assert response.status_code == 503
    data = response.json()
    assert "unavailable" in data["detail"].lower()
    assert "request_id" in data


def test_validation_error_includes_request_id():
    """Test that validation errors include request_id."""
    response = client.get("/shows/search?query=x")  # Too short (min_length=2)
    assert response.status_code == 422
    data = response.json()
    assert "request_id" in data
    assert "errors" in data


def test_not_found_returns_json_with_request_id():
    """Test that 404 errors return clean JSON with request_id."""
    response = client.get("/nonexistent-path")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "request_id" in data


# =============================================================================
# Request ID Tests
# =============================================================================


def test_request_id_header_present():
    """Test that X-Request-ID header is present on all responses."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) == 32  # UUID4 hex


def test_request_id_unique_per_request():
    """Test that each request gets a unique request ID."""
    response1 = client.get("/health")
    response2 = client.get("/health")
    assert response1.headers["X-Request-ID"] != response2.headers["X-Request-ID"]


def test_request_id_on_error_responses():
    """Test that X-Request-ID header is present on error responses."""
    response = client.get("/nonexistent-path")
    assert "X-Request-ID" in response.headers


def test_get_request_id_fallback():
    """Test get_request_id returns unknown when no request_id in state."""
    from app.core.middleware import get_request_id

    class FakeRequest:
        class state:
            pass

    assert get_request_id(FakeRequest()) == "unknown"


# =============================================================================
# Lifespan Tests
# =============================================================================


@pytest.mark.asyncio
async def test_lifespan_startup_shutdown():
    """Test application lifespan context manager."""
    from app.main import lifespan

    mock_app = AsyncMock()

    with (
        patch("app.main.close_redis_pool") as mock_close,
        patch("app.main.refresh_cache_age_gauges", new_callable=AsyncMock),
    ):
        async with lifespan(mock_app):
            pass
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_cache_age_refresh_loop_calls_refresh_then_sleeps():
    """The background loop calls refresh once before sleeping."""
    import asyncio

    from app.main import _cache_age_refresh_loop

    with (
        patch("app.main.refresh_cache_age_gauges", new_callable=AsyncMock) as mock_refresh,
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
    ):
        with pytest.raises(asyncio.CancelledError):
            await _cache_age_refresh_loop()
    mock_refresh.assert_called_once()


def test_middleware_exception_handling():
    """Test middleware logs and re-raises exceptions."""

    # Create a test route that raises an exception
    @app.get("/test-middleware-error")
    async def raise_error():
        raise RuntimeError("Test middleware error")

    # The middleware logs the error and re-raises it
    # TestClient will re-raise the exception
    with pytest.raises(RuntimeError, match="Test middleware error"):
        client.get("/test-middleware-error")


def test_initialize_logging_fallback():
    """Test logging initialization fallback."""
    from app.main import _initialize_logging

    # Test that it works with normal setup
    _initialize_logging()

    # Test fallback when setup_logging fails
    with patch("app.core.logging_config.setup_logging", side_effect=Exception("Config error")):
        # Should not raise - falls back to basicConfig
        _initialize_logging()


# =============================================================================
# Security Headers Tests
# =============================================================================


def test_security_headers_present():
    """Test that security headers are added to all responses."""
    response = client.get("/health")
    assert response.status_code == 200

    # Verify all security headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "0"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains; preload"


def test_docs_paths_get_relaxed_csp():
    """/docs and /redoc need a CSP that allows the jsdelivr CDN + inline init
    scripts to load Swagger UI / ReDoc assets. Anything else stays strict (#223)."""
    for path in ("/docs", "/redoc"):
        response = client.get(path)
        csp = response.headers["Content-Security-Policy"]
        # Must allow jsdelivr CDN (where Swagger UI bundle + ReDoc live)
        assert "https://cdn.jsdelivr.net" in csp, f"{path}: missing CDN allowance ({csp})"
        # Must allow inline scripts for SwaggerUIBundle / Redoc init blocks
        assert "'unsafe-inline'" in csp, f"{path}: missing unsafe-inline ({csp})"
        # Strict default still applies
        assert "default-src 'none'" in csp, f"{path}: lost default-src 'none' ({csp})"


def test_non_docs_paths_keep_strict_csp():
    """Verify the docs CSP relaxation is path-scoped — non-docs endpoints
    keep the strict default-src 'none' CSP."""
    response = client.get("/health")
    assert response.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_security_headers_on_error_responses():
    """Test that security headers are present even on error responses."""
    response = client.get("/shows/nonexistentshow")
    assert response.status_code == 404

    # Security headers should still be present
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains; preload"


# =============================================================================
# CORS Tests
# =============================================================================


def test_cors_allows_all_origins():
    """Test that CORS allows all origins for this public API."""
    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "*"


def test_cors_only_allows_get_options():
    """Test that CORS only allows GET and OPTIONS methods."""
    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    allowed = response.headers.get("access-control-allow-methods", "")
    assert "GET" in allowed


# =============================================================================
# OpenAPI & Documentation Tests
# =============================================================================


def test_openapi_json_accessible():
    """Test that OpenAPI schema is accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "paths" in data
    assert "info" in data
    assert data["info"]["title"] == "Epguides API"


def test_redoc_accessible():
    """Test that ReDoc documentation is accessible."""
    response = client.get("/redoc")
    assert response.status_code == 200


def test_root_redirects_to_docs():
    """Test that root URL redirects to /docs."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


# =============================================================================
# Health Endpoint Detail Tests
# =============================================================================


def test_health_check_response_structure():
    """Test health check returns correct structure with version."""
    response = client.get("/health")
    data = response.json()
    assert "status" in data
    assert "service" in data
    assert "version" in data
    assert data["service"] == "epguides-api"
    assert isinstance(data["version"], str)


def test_llm_health_check_response_structure():
    """Test LLM health check returns expected fields."""
    response = client.get("/health/llm")
    data = response.json()
    assert "enabled" in data
    assert "configured" in data
    assert "api_url" in data
    assert "model" in data
    assert "allow_external" in data


# =============================================================================
# Error Handler Edge Cases
# =============================================================================


def test_404_returns_detail_field():
    """Test that 404 responses always have a detail field."""
    response = client.get("/completely/unknown/path")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)


def test_404_returns_json_content_type():
    """Test that 404 responses return JSON content type."""
    response = client.get("/nonexistent")
    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]


def test_validation_error_returns_errors_list():
    """Test that validation errors include an errors list."""
    response = client.get("/shows/search?query=x")  # Too short
    assert response.status_code == 422
    data = response.json()
    assert "errors" in data
    assert isinstance(data["errors"], list)
    assert len(data["errors"]) > 0


# =============================================================================
# Readiness (/health/ready) Tests
# =============================================================================


@pytest.mark.asyncio
async def test_readiness_ok_when_redis_and_upstream_fresh():
    """Both checks healthy → status 'ok', HTTP 200."""
    import time

    from app.main import _READINESS_UPSTREAM

    with (
        patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(True, 1.5))),
        patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=time.time() - 60)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["overall_ok"] is True
    assert data["service"] == "epguides-api"
    assert data["checks"]["redis"]["status"] == "ok"
    assert data["checks"]["redis"]["round_trip_ms"] == 1.5
    assert data["checks"]["upstream"]["status"] == "ok"
    assert data["checks"]["upstream"]["source"] == _READINESS_UPSTREAM
    assert data["checks"]["upstream"]["last_success_age_seconds"] >= 0


@pytest.mark.asyncio
async def test_readiness_degraded_when_redis_down_but_upstream_fresh():
    """Redis down but upstream fresh → 'degraded', HTTP 200 (still serving)."""
    import time

    with (
        patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(False, None))),
        patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=time.time() - 60)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["overall_ok"] is False
    assert data["checks"]["redis"]["status"] == "unavailable"
    assert "round_trip_ms" not in data["checks"]["redis"]
    assert data["checks"]["upstream"]["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_unready_when_upstream_stale():
    """Upstream older than the threshold → 'unready', HTTP 503 with a reason."""
    import time

    # 48h old against a 24h default threshold.
    stale_ts = time.time() - (48 * 3600)

    with (
        patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(True, 2.0))),
        patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=stale_ts)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unready"
    assert data["overall_ok"] is False
    assert data["checks"]["upstream"]["status"] == "stale"
    assert "reason" in data["checks"]["upstream"]
    assert data["checks"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_unready_takes_priority_over_redis_degraded():
    """Stale upstream is fatal even if Redis is also down → 503 'unready'."""
    import time

    stale_ts = time.time() - (48 * 3600)

    with (
        patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(False, None))),
        patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=stale_ts)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unready"
    assert data["overall_ok"] is False


@pytest.mark.asyncio
async def test_readiness_bootstrapping_within_cold_start_grace():
    """Absent marker within the cold-start grace window → 200, 'ok' overall."""
    import time

    # Pretend the process just started so we are inside the grace window.
    with (
        patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(True, 1.0))),
        patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=None)),
        patch("app.main._PROCESS_START_TIME", time.time()),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["overall_ok"] is True
    assert data["checks"]["upstream"]["status"] == "bootstrapping"
    assert "grace" in data["checks"]["upstream"]["reason"]


@pytest.mark.asyncio
async def test_readiness_stale_when_no_fetch_after_grace_window():
    """Absent marker past the grace window → 503 'unready' (never reached upstream)."""
    import time

    from app.main import settings as main_settings

    # Process started long ago: grace window has elapsed with no success.
    long_ago = time.time() - (main_settings.UPSTREAM_FRESHNESS_COLD_START_GRACE_SECONDS + 60)

    with (
        patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(True, 1.0))),
        patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=None)),
        patch("app.main._PROCESS_START_TIME", long_ago),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unready"
    assert data["overall_ok"] is False
    assert data["checks"]["upstream"]["status"] == "stale"
    assert "since startup" in data["checks"]["upstream"]["reason"]


@pytest.mark.asyncio
async def test_readiness_overall_ok_is_collision_proof_on_degraded_body():
    """The exact false-pass `overall_ok` exists to prevent, as a regression test.

    A *degraded* body still contains the raw substring ``"status": "ok"`` (the
    healthy upstream sub-check), so a substring/regex monitor asserting on it
    false-passes. ``overall_ok`` must (a) be False on that same body and (b)
    never appear inside nested check objects — that's what makes a regex on it
    collision-proof.
    """
    import time

    with (
        patch("app.main.probe_redis_round_trip", new=AsyncMock(return_value=(False, None))),
        patch("app.main.get_upstream_last_success", new=AsyncMock(return_value=time.time() - 60)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    # The unsound substring assertion would false-pass on this degraded body:
    assert data["status"] == "degraded"
    assert '"status":"ok"' in response.text.replace(" ", "")
    # ...while the collision-proof marker correctly reads unhealthy:
    assert data["overall_ok"] is False
    # And the key exists ONLY at the top level — never in nested check objects.
    assert all("overall_ok" not in check for check in data["checks"].values())


def test_readiness_listed_in_openapi():
    """The deep readiness endpoint is part of the documented public surface."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/health/ready" in response.json()["paths"]
