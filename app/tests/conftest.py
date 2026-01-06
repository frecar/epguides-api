"""
Pytest fixtures for test suite.

Provides async HTTP client and cache management.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import show_service


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear in-memory caches before each test for clean state."""
    show_service.clear_memory_caches()
    yield
    show_service.clear_memory_caches()


@pytest_asyncio.fixture
async def async_client():
    """Async HTTP client for testing endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
