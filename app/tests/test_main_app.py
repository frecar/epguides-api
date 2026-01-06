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
        mock_settings.OPENAI_API_KEY = None
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
    assert "internal error" in response.json()["detail"].lower()


def test_external_service_exception_handler():
    """Test custom exception handler for ExternalServiceError."""

    @app.get("/test-external-error")
    async def raise_external_error():
        raise ExternalServiceError("External service failed")

    response = client.get("/test-external-error")
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


# =============================================================================
# Lifespan Tests
# =============================================================================


@pytest.mark.asyncio
async def test_lifespan_startup_shutdown():
    """Test application lifespan context manager."""
    from app.main import lifespan

    mock_app = AsyncMock()

    with patch("app.main.close_redis_pool") as mock_close:
        async with lifespan(mock_app):
            # Startup completed
            pass
        # Shutdown should call close_redis_pool
        mock_close.assert_called_once()


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
