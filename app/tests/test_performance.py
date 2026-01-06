"""
Performance tests for API endpoints.

Ensures all endpoints respond within acceptable time limits:
- Target: < 20ms (warning if exceeded)
- Hard limit: < 50ms (fail if exceeded)

These tests use mocked dependencies to measure endpoint overhead only,
not external service latency.
"""

import time
import warnings
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.schemas import EpisodeSchema, SeasonSchema, create_show_schema

# =============================================================================
# Constants
# =============================================================================

PERF_TARGET_MS = 20  # Target response time (warning if exceeded)
PERF_LIMIT_MS = 50  # Hard limit (fail if exceeded)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def perf_client():
    """Async HTTP client for performance testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_show():
    """Sample show for mocking."""
    return create_show_schema(epguides_key="testshow", title="Test Show")


@pytest.fixture
def mock_shows(mock_show):
    """List of sample shows for mocking."""
    return [mock_show for _ in range(100)]


@pytest.fixture
def mock_episodes():
    """List of sample episodes for mocking."""
    from datetime import date

    return [
        EpisodeSchema(
            season=1,
            number=i,
            title=f"Episode {i}",
            release_date=date(2020, 1, i),
            is_released=True,
        )
        for i in range(1, 11)
    ]


@pytest.fixture
def mock_seasons():
    """List of sample seasons for mocking."""
    from datetime import date

    return [
        SeasonSchema(
            number=i,
            episode_count=10,
            premiere_date=date(2020, i, 1),
            end_date=date(2020, i, 28),
            poster_url="https://example.com/poster.jpg",
            summary=f"Season {i} summary",
            api_episodes_url=f"http://test/shows/testshow/seasons/{i}/episodes",
        )
        for i in range(1, 6)
    ]


# =============================================================================
# Performance Assertion Helper
# =============================================================================


def assert_performance(elapsed_ms: float, endpoint: str) -> None:
    """
    Assert endpoint performance meets requirements.

    Args:
        elapsed_ms: Response time in milliseconds.
        endpoint: Endpoint name for error messages.

    Raises:
        AssertionError: If elapsed_ms > PERF_LIMIT_MS.
        UserWarning: If elapsed_ms > PERF_TARGET_MS (but within limit).
    """
    if elapsed_ms > PERF_LIMIT_MS:
        pytest.fail(f"{endpoint} exceeded {PERF_LIMIT_MS}ms limit: {elapsed_ms:.1f}ms")

    if elapsed_ms > PERF_TARGET_MS:
        warnings.warn(
            f"{endpoint} exceeded {PERF_TARGET_MS}ms target: {elapsed_ms:.1f}ms (limit: {PERF_LIMIT_MS}ms)",
            UserWarning,
            stacklevel=2,
        )


async def measure_endpoint(client: AsyncClient, method: str, url: str, **kwargs) -> float:
    """
    Measure endpoint response time.

    Returns:
        Response time in milliseconds.
    """
    start = time.perf_counter()
    if method.upper() == "GET":
        await client.get(url, **kwargs)
    elif method.upper() == "POST":
        await client.post(url, **kwargs)
    elapsed = (time.perf_counter() - start) * 1000
    return elapsed


# =============================================================================
# Health Endpoint Performance Tests
# =============================================================================


@pytest.mark.asyncio
async def test_perf_health_check(perf_client):
    """Test /health endpoint performance."""
    elapsed = await measure_endpoint(perf_client, "GET", "/health")
    assert_performance(elapsed, "GET /health")


@pytest.mark.asyncio
async def test_perf_health_llm(perf_client):
    """Test /health/llm endpoint performance."""
    elapsed = await measure_endpoint(perf_client, "GET", "/health/llm")
    assert_performance(elapsed, "GET /health/llm")


@pytest.mark.asyncio
@patch("app.core.cache.get_cache_stats")
async def test_perf_health_cache(mock_stats, perf_client):
    """Test /health/cache endpoint performance."""
    mock_stats.return_value = {"status": "connected", "total_keys": 100}
    elapsed = await measure_endpoint(perf_client, "GET", "/health/cache")
    assert_performance(elapsed, "GET /health/cache")


# =============================================================================
# Shows Endpoint Performance Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.show_service.get_shows_page")
async def test_perf_list_shows(mock_get_shows, mock_shows, perf_client):
    """Test GET /shows/ endpoint performance."""
    mock_get_shows.return_value = (mock_shows[:50], 100)
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/")
    assert_performance(elapsed, "GET /shows/")


@pytest.mark.asyncio
@patch("app.services.show_service.search_shows_fast")
async def test_perf_search_shows(mock_search, mock_shows, perf_client):
    """Test GET /shows/search endpoint performance."""
    mock_search.return_value = mock_shows[:10]
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/search?query=test")
    assert_performance(elapsed, "GET /shows/search")


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
async def test_perf_get_show(mock_get_show, mock_show, perf_client):
    """Test GET /shows/{key} endpoint performance."""
    mock_get_show.return_value = mock_show
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow")
    assert_performance(elapsed, "GET /shows/{key}")


@pytest.mark.asyncio
@patch("app.services.show_service.get_episodes")
@patch("app.services.show_service.get_show")
async def test_perf_get_show_with_episodes(mock_get_show, mock_get_eps, mock_show, mock_episodes, perf_client):
    """Test GET /shows/{key}?include=episodes endpoint performance."""
    mock_get_show.return_value = mock_show
    mock_get_eps.return_value = mock_episodes
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow?include=episodes")
    assert_performance(elapsed, "GET /shows/{key}?include=episodes")


# =============================================================================
# Seasons Endpoint Performance Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.show_service.get_seasons")
async def test_perf_get_seasons(mock_get_seasons, mock_seasons, perf_client):
    """Test GET /shows/{key}/seasons endpoint performance."""
    mock_get_seasons.return_value = mock_seasons
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow/seasons")
    assert_performance(elapsed, "GET /shows/{key}/seasons")


@pytest.mark.asyncio
@patch("app.services.show_service.get_episodes")
async def test_perf_get_season_episodes(mock_get_eps, mock_episodes, perf_client):
    """Test GET /shows/{key}/seasons/{num}/episodes endpoint performance."""
    mock_get_eps.return_value = mock_episodes
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow/seasons/1/episodes")
    assert_performance(elapsed, "GET /shows/{key}/seasons/{num}/episodes")


# =============================================================================
# Episodes Endpoint Performance Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.show_service.get_episodes")
async def test_perf_get_episodes(mock_get_eps, mock_episodes, perf_client):
    """Test GET /shows/{key}/episodes endpoint performance."""
    mock_get_eps.return_value = mock_episodes
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow/episodes")
    assert_performance(elapsed, "GET /shows/{key}/episodes")


@pytest.mark.asyncio
@patch("app.services.show_service.get_episodes")
async def test_perf_get_episodes_filtered(mock_get_eps, mock_episodes, perf_client):
    """Test GET /shows/{key}/episodes with filters endpoint performance."""
    mock_get_eps.return_value = mock_episodes
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow/episodes?season=1&year=2020")
    assert_performance(elapsed, "GET /shows/{key}/episodes (filtered)")


@pytest.mark.asyncio
@patch("app.services.show_service.get_show")
@patch("app.services.show_service.get_episodes")
async def test_perf_get_next_episode(mock_get_eps, mock_get_show, mock_show, perf_client):
    """Test GET /shows/{key}/episodes/next endpoint performance."""
    from datetime import date

    mock_get_show.return_value = mock_show
    mock_get_eps.return_value = [
        EpisodeSchema(season=1, number=1, title="Future Ep", release_date=date(2030, 1, 1), is_released=False)
    ]
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow/episodes/next")
    assert_performance(elapsed, "GET /shows/{key}/episodes/next")


@pytest.mark.asyncio
@patch("app.services.show_service.get_episodes")
async def test_perf_get_latest_episode(mock_get_eps, mock_episodes, perf_client):
    """Test GET /shows/{key}/episodes/latest endpoint performance."""
    mock_get_eps.return_value = mock_episodes
    elapsed = await measure_endpoint(perf_client, "GET", "/shows/testshow/episodes/latest")
    assert_performance(elapsed, "GET /shows/{key}/episodes/latest")


# =============================================================================
# MCP Endpoint Performance Tests
# =============================================================================


@pytest.mark.asyncio
async def test_perf_mcp_health(perf_client):
    """Test GET /mcp/health endpoint performance."""
    elapsed = await measure_endpoint(perf_client, "GET", "/mcp/health")
    assert_performance(elapsed, "GET /mcp/health")


@pytest.mark.asyncio
async def test_perf_mcp_initialize(perf_client):
    """Test POST /mcp initialize method performance."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    elapsed = await measure_endpoint(perf_client, "POST", "/mcp", json=request)
    assert_performance(elapsed, "POST /mcp (initialize)")


@pytest.mark.asyncio
async def test_perf_mcp_tools_list(perf_client):
    """Test POST /mcp tools/list method performance."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    elapsed = await measure_endpoint(perf_client, "POST", "/mcp", json=request)
    assert_performance(elapsed, "POST /mcp (tools/list)")


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.search_shows")
async def test_perf_mcp_search_shows(mock_search, mock_shows, perf_client):
    """Test POST /mcp search_shows tool performance."""
    mock_search.return_value = mock_shows[:10]
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_shows", "arguments": {"query": "test"}},
    }
    elapsed = await measure_endpoint(perf_client, "POST", "/mcp", json=request)
    assert_performance(elapsed, "POST /mcp (search_shows)")


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_show")
async def test_perf_mcp_get_show(mock_get_show, mock_show, perf_client):
    """Test POST /mcp get_show tool performance."""
    mock_get_show.return_value = mock_show
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_show", "arguments": {"epguides_key": "testshow"}},
    }
    elapsed = await measure_endpoint(perf_client, "POST", "/mcp", json=request)
    assert_performance(elapsed, "POST /mcp (get_show)")


@pytest.mark.asyncio
@patch("app.mcp.server.show_service.get_episodes")
async def test_perf_mcp_get_episodes(mock_get_eps, mock_episodes, perf_client):
    """Test POST /mcp get_episodes tool performance."""
    mock_get_eps.return_value = mock_episodes
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_episodes", "arguments": {"epguides_key": "testshow"}},
    }
    elapsed = await measure_endpoint(perf_client, "POST", "/mcp", json=request)
    assert_performance(elapsed, "POST /mcp (get_episodes)")


# =============================================================================
# Live Redis Integration Performance Tests
# =============================================================================
# These tests require Redis to be running (via `make up`).
# They test real cache performance, not just endpoint overhead.
# Skipped automatically if Redis is unavailable.


async def redis_available() -> bool:
    """Check if Redis is available for integration tests."""
    try:
        from app.core.cache import get_redis

        redis = await get_redis()
        await redis.ping()
        return True
    except Exception:
        return False


@pytest.fixture
async def live_client():
    """HTTP client for live integration tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# Live performance limits are more relaxed (include network + Redis latency)
LIVE_PERF_TARGET_MS = 50  # Target for cached responses
LIVE_PERF_LIMIT_MS = 200  # Hard limit (includes cold cache)


def assert_live_performance(elapsed_ms: float, endpoint: str, cached: bool = True) -> None:
    """Assert live endpoint performance (more relaxed than mocked tests)."""
    limit = LIVE_PERF_LIMIT_MS
    target = LIVE_PERF_TARGET_MS if cached else LIVE_PERF_LIMIT_MS

    if elapsed_ms > limit:
        pytest.fail(f"[LIVE] {endpoint} exceeded {limit}ms limit: {elapsed_ms:.1f}ms")

    if elapsed_ms > target:
        warnings.warn(
            f"[LIVE] {endpoint} exceeded {target}ms target: {elapsed_ms:.1f}ms",
            UserWarning,
            stacklevel=2,
        )


@pytest.mark.asyncio
async def test_live_perf_health_cache(live_client):
    """[LIVE] Test /health/cache with real Redis."""
    if not await redis_available():
        pytest.skip("Redis not available")

    elapsed = await measure_endpoint(live_client, "GET", "/health/cache")
    assert_live_performance(elapsed, "GET /health/cache (live)")


@pytest.mark.asyncio
async def test_live_perf_cache_operations():
    """[LIVE] Test raw Redis cache operation performance."""
    if not await redis_available():
        pytest.skip("Redis not available")

    from app.core.cache import cache_delete, cache_get, cache_set

    test_key = "perf_test:temp"
    test_value = '{"test": "data", "items": [1, 2, 3, 4, 5]}'

    # Measure cache SET
    start = time.perf_counter()
    await cache_set(test_key, test_value, 60)
    set_time = (time.perf_counter() - start) * 1000

    # Measure cache GET (warm)
    start = time.perf_counter()
    await cache_get(test_key)
    get_time = (time.perf_counter() - start) * 1000

    # Cleanup
    await cache_delete(test_key)

    # Assert performance
    assert set_time < 10, f"cache_set exceeded 10ms: {set_time:.1f}ms"
    assert get_time < 5, f"cache_get exceeded 5ms: {get_time:.1f}ms"


@pytest.mark.asyncio
async def test_live_perf_cached_vs_uncached():
    """[LIVE] Compare cached vs uncached response times."""
    if not await redis_available():
        pytest.skip("Redis not available")

    from app.core.cache import cache_delete, cache_get, cache_set

    # Simulate a cached response scenario
    cache_key = "perf_test:show"
    show_json = '{"epguides_key": "test", "title": "Test Show"}'

    # Cold cache (miss)
    await cache_delete(cache_key)
    start = time.perf_counter()
    result = await cache_get(cache_key)
    cold_time = (time.perf_counter() - start) * 1000
    assert result is None

    # Warm cache (hit)
    await cache_set(cache_key, show_json, 60)
    start = time.perf_counter()
    result = await cache_get(cache_key)
    warm_time = (time.perf_counter() - start) * 1000
    assert result == show_json

    # Cleanup
    await cache_delete(cache_key)

    # Both should be fast (Redis is in-memory)
    assert cold_time < 10, f"Cold cache exceeded 10ms: {cold_time:.1f}ms"
    assert warm_time < 5, f"Warm cache exceeded 5ms: {warm_time:.1f}ms"


@pytest.mark.asyncio
async def test_live_perf_hash_operations():
    """[LIVE] Test Redis hash operations (used for O(1) show lookups)."""
    if not await redis_available():
        pytest.skip("Redis not available")

    from app.core.cache import cache_hget, get_redis

    redis = await get_redis()
    test_hash = "perf_test:hash"

    # Setup test data
    await redis.hset(test_hash, "key1", "value1")
    await redis.hset(test_hash, "key2", "value2")

    # Measure HGET
    start = time.perf_counter()
    result = await cache_hget(test_hash, "key1")
    hget_time = (time.perf_counter() - start) * 1000

    # Cleanup
    await redis.delete(test_hash)

    assert result == "value1"
    assert hget_time < 5, f"cache_hget exceeded 5ms: {hget_time:.1f}ms"
