"""
Unit tests for cache module.

Tests Redis cache operations, decorators, and helpers.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core import cache

# =============================================================================
# Redis Connection Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_redis_returns_client():
    """Test get_redis returns a Redis client."""
    # Just verify it returns something (actual connection tested in integration)
    result = await cache.get_redis()
    assert result is not None


@pytest.mark.asyncio
async def test_close_redis_pool():
    """Test close_redis_pool closes connections."""
    mock_client = AsyncMock()
    mock_pool = AsyncMock()

    with patch.object(cache, "_redis_client", mock_client), patch.object(cache, "_redis_pool", mock_pool):
        await cache.close_redis_pool()
        mock_client.close.assert_called_once()
        mock_pool.disconnect.assert_called_once()


# =============================================================================
# Cache Helper Tests
# =============================================================================


@pytest.mark.asyncio
async def test_cache_get_returns_value():
    """Test cache_get returns cached value."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "cached_value"

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_get("test_key")
        assert result == "cached_value"
        mock_redis.get.assert_called_once_with("test_key")


@pytest.mark.asyncio
async def test_cache_get_returns_none_on_miss():
    """Test cache_get returns None on cache miss."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_get("missing_key")
        assert result is None


@pytest.mark.asyncio
async def test_cache_get_handles_error():
    """Test cache_get returns None on Redis error."""
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = Exception("Redis error")

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_get("test_key")
        assert result is None


@pytest.mark.asyncio
async def test_cache_set_stores_value():
    """Test cache_set stores value with TTL."""
    mock_redis = AsyncMock()

    with patch.object(cache, "get_redis", return_value=mock_redis):
        await cache.cache_set("test_key", "test_value", 3600)
        mock_redis.setex.assert_called_once_with("test_key", 3600, "test_value")


@pytest.mark.asyncio
async def test_cache_set_handles_error():
    """Test cache_set handles Redis error silently."""
    mock_redis = AsyncMock()
    mock_redis.setex.side_effect = Exception("Redis error")

    with patch.object(cache, "get_redis", return_value=mock_redis):
        # Should not raise
        await cache.cache_set("test_key", "test_value", 3600)


@pytest.mark.asyncio
async def test_cache_delete_removes_keys():
    """Test cache_delete removes keys."""
    mock_redis = AsyncMock()

    with patch.object(cache, "get_redis", return_value=mock_redis):
        await cache.cache_delete("key1", "key2")
        mock_redis.delete.assert_called_once_with("key1", "key2")


@pytest.mark.asyncio
async def test_cache_delete_handles_error():
    """Test cache_delete handles Redis error silently."""
    mock_redis = AsyncMock()
    mock_redis.delete.side_effect = Exception("Redis error")

    with patch.object(cache, "get_redis", return_value=mock_redis):
        # Should not raise
        await cache.cache_delete("key1")


@pytest.mark.asyncio
async def test_cache_hget_returns_value():
    """Test cache_hget returns hash field value."""
    mock_redis = AsyncMock()
    mock_redis.hget.return_value = "hash_value"

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_hget("hash_key", "field")
        assert result == "hash_value"


@pytest.mark.asyncio
async def test_cache_hget_handles_error():
    """Test cache_hget returns None on error."""
    mock_redis = AsyncMock()
    mock_redis.hget.side_effect = Exception("Redis error")

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_hget("hash_key", "field")
        assert result is None


@pytest.mark.asyncio
async def test_cache_exists_returns_true():
    """Test cache_exists returns True when key exists."""
    mock_redis = AsyncMock()
    mock_redis.exists.return_value = 1

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_exists("test_key")
        assert result is True


@pytest.mark.asyncio
async def test_cache_exists_returns_false():
    """Test cache_exists returns False when key doesn't exist."""
    mock_redis = AsyncMock()
    mock_redis.exists.return_value = 0

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_exists("missing_key")
        assert result is False


@pytest.mark.asyncio
async def test_cache_exists_handles_error():
    """Test cache_exists returns False on error."""
    mock_redis = AsyncMock()
    mock_redis.exists.side_effect = Exception("Redis error")

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.cache_exists("test_key")
        assert result is False


# =============================================================================
# Invalidate and Extend TTL Tests
# =============================================================================


@pytest.mark.asyncio
async def test_invalidate_cache_deletes_key():
    """Test invalidate_cache deletes the specified key."""
    mock_redis = AsyncMock()
    mock_redis.delete.return_value = 1

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.invalidate_cache("episodes", "breakingbad")
        assert result is True
        mock_redis.delete.assert_called_once_with("episodes:breakingbad")


@pytest.mark.asyncio
async def test_invalidate_cache_returns_false_when_not_found():
    """Test invalidate_cache returns False when key doesn't exist."""
    mock_redis = AsyncMock()
    mock_redis.delete.return_value = 0

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.invalidate_cache("episodes", "nonexistent")
        assert result is False


@pytest.mark.asyncio
async def test_invalidate_cache_handles_error():
    """Test invalidate_cache returns False on error."""
    mock_redis = AsyncMock()
    mock_redis.delete.side_effect = Exception("Redis error")

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.invalidate_cache("episodes", "test")
        assert result is False


@pytest.mark.asyncio
async def test_extend_cache_ttl_extends():
    """Test extend_cache_ttl extends TTL."""
    mock_redis = AsyncMock()
    mock_redis.expire.return_value = True

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.extend_cache_ttl("episodes", "breakingbad", 31536000)
        assert result is True
        mock_redis.expire.assert_called_once_with("episodes:breakingbad", 31536000)


@pytest.mark.asyncio
async def test_extend_cache_ttl_handles_error():
    """Test extend_cache_ttl returns False on error."""
    mock_redis = AsyncMock()
    mock_redis.expire.side_effect = Exception("Redis error")

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.extend_cache_ttl("episodes", "test", 3600)
        assert result is False


# =============================================================================
# Cache Decorator Tests
# =============================================================================


@pytest.mark.asyncio
async def test_cache_decorator_returns_cached():
    """Test @cache decorator returns cached data."""

    @cache.cache(ttl_seconds=3600, key_prefix="test")
    async def get_data(key: str) -> dict:
        return {"result": "fresh"}

    with patch.object(cache, "cache_get", return_value='{"result": "cached"}'):
        with patch.object(cache, "cache_set") as mock_set:
            result = await get_data("mykey")
            assert result == {"result": "cached"}
            mock_set.assert_not_called()


@pytest.mark.asyncio
async def test_cache_decorator_fetches_on_miss():
    """Test @cache decorator fetches fresh data on cache miss."""

    @cache.cache(ttl_seconds=3600, key_prefix="test")
    async def get_data(key: str) -> dict:
        return {"result": "fresh"}

    with patch.object(cache, "cache_get", return_value=None), patch.object(cache, "cache_set") as mock_set:
        result = await get_data("mykey")
        assert result == {"result": "fresh"}
        mock_set.assert_called_once()


@pytest.mark.asyncio
async def test_cache_decorator_handles_corrupted_json():
    """Test @cache decorator handles corrupted cached JSON."""

    @cache.cache(ttl_seconds=3600, key_prefix="test")
    async def get_data(key: str) -> dict:
        return {"result": "fresh"}

    with patch.object(cache, "cache_get", return_value="not valid json"):
        with patch.object(cache, "cache_set") as mock_set:
            result = await get_data("mykey")
            assert result == {"result": "fresh"}
            mock_set.assert_called_once()


# =============================================================================
# Cached Decorator Tests (Pydantic models)
# =============================================================================


@pytest.mark.asyncio
async def test_cached_decorator_returns_cached_model():
    """Test @cached decorator returns cached Pydantic model."""
    from app.models.schemas import ShowSchema, create_show_schema

    @cache.cached("show:{show_id}", ttl=3600, model=ShowSchema)
    async def get_show(show_id: str) -> ShowSchema:
        return create_show_schema(epguides_key="test", title="Test Show")

    cached_json = '{"epguides_key": "cached", "title": "Cached Show"}'
    with patch.object(cache, "cache_get", return_value=cached_json):
        result = await get_show("test")
        assert result.epguides_key == "cached"
        assert result.title == "Cached Show"


@pytest.mark.asyncio
async def test_cached_decorator_fetches_on_miss():
    """Test @cached decorator fetches fresh data on cache miss."""
    from app.models.schemas import ShowSchema, create_show_schema

    @cache.cached("show:{show_id}", ttl=3600, model=ShowSchema)
    async def get_show(show_id: str) -> ShowSchema:
        return create_show_schema(epguides_key="fresh", title="Fresh Show")

    with patch.object(cache, "cache_get", return_value=None), patch.object(cache, "cache_set") as mock_set:
        result = await get_show("test")
        assert result.epguides_key == "fresh"
        mock_set.assert_called_once()


@pytest.mark.asyncio
async def test_cached_decorator_handles_list():
    """Test @cached decorator handles list of Pydantic models."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    @cache.cached("episodes:{show_id}", ttl=3600, model=EpisodeSchema, is_list=True)
    async def get_episodes(show_id: str) -> list[EpisodeSchema]:
        return [EpisodeSchema(season=1, number=1, title="Pilot", release_date=date(2020, 1, 1), is_released=True)]

    cached_json = '[{"season": 1, "number": 2, "title": "Cached", "release_date": "2020-01-02", "is_released": true}]'
    with patch.object(cache, "cache_get", return_value=cached_json):
        result = await get_episodes("test")
        assert len(result) == 1
        assert result[0].title == "Cached"


@pytest.mark.asyncio
async def test_cached_decorator_handles_corrupted_json():
    """Test @cached decorator handles corrupted JSON gracefully."""
    from app.models.schemas import ShowSchema, create_show_schema

    @cache.cached("show:{show_id}", ttl=3600, model=ShowSchema)
    async def get_show(show_id: str) -> ShowSchema:
        return create_show_schema(epguides_key="fresh", title="Fresh Show")

    with patch.object(cache, "cache_get", return_value="invalid json {{"), patch.object(cache, "cache_set"):
        result = await get_show("test")
        assert result.epguides_key == "fresh"


@pytest.mark.asyncio
async def test_cached_decorator_handles_validation_error():
    """Test @cached decorator handles Pydantic validation errors."""
    from app.models.schemas import ShowSchema, create_show_schema

    @cache.cached("show:{show_id}", ttl=3600, model=ShowSchema)
    async def get_show(show_id: str) -> ShowSchema:
        return create_show_schema(epguides_key="fresh", title="Fresh Show")

    # Missing required field
    with patch.object(cache, "cache_get", return_value='{"wrong_field": "value"}'):
        with patch.object(cache, "cache_set"):
            result = await get_show("test")
            assert result.epguides_key == "fresh"


@pytest.mark.asyncio
async def test_cached_decorator_with_ttl_override():
    """Test @cached decorator with dynamic TTL override."""
    from datetime import date

    from app.models.schemas import ShowSchema, create_show_schema

    def ttl_override(show: ShowSchema) -> int | None:
        if show.end_date:
            return 31536000  # 1 year for finished shows
        return None

    @cache.cached("show:{show_id}", ttl=3600, model=ShowSchema, ttl_if=ttl_override)
    async def get_show(show_id: str) -> ShowSchema:
        return create_show_schema(epguides_key="finished", title="Finished Show", end_date=date(2020, 1, 1))

    with patch.object(cache, "cache_get", return_value=None), patch.object(cache, "cache_set") as mock_set:
        await get_show("test")
        # Should use 1 year TTL for finished show
        call_args = mock_set.call_args
        assert call_args[0][2] == 31536000


@pytest.mark.asyncio
async def test_cached_decorator_without_model():
    """Test @cached decorator without Pydantic model (raw dict)."""

    @cache.cached("data:{key}", ttl=3600)
    async def get_data(key: str) -> dict:
        return {"raw": "data"}

    with patch.object(cache, "cache_get", return_value=None), patch.object(cache, "cache_set") as mock_set:
        result = await get_data("test")
        assert result == {"raw": "data"}
        mock_set.assert_called_once()


# =============================================================================
# Cache Stats Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_cache_stats_returns_stats():
    """Test get_cache_stats returns cache statistics."""
    mock_redis = AsyncMock()
    mock_redis.keys.return_value = [
        b"show:test1",
        b"show:test2",
        b"episodes:test1",
        b"seasons:test1",
        b"shows:all:raw",
        b"show_index",
    ]
    mock_redis.ttl.return_value = 86400
    mock_redis.info.return_value = {"used_memory_human": "10M", "used_memory_peak_human": "15M"}

    with patch.object(cache, "get_redis", return_value=mock_redis):
        result = await cache.get_cache_stats()

        assert result["status"] == "connected"
        assert result["total_keys"] == 6
        assert result["cached_items"]["shows"] == 2
        assert result["cached_items"]["episodes"] == 1
        assert result["cached_items"]["seasons"] == 1
        assert result["master_caches"]["show_list"] is True
        assert result["master_caches"]["show_index"] is True


@pytest.mark.asyncio
async def test_get_cache_stats_handles_error():
    """Test get_cache_stats returns error status on failure."""
    with patch.object(cache, "get_redis", side_effect=Exception("Connection failed")):
        result = await cache.get_cache_stats()
        assert result["status"] == "error"
        assert "error" in result


@pytest.mark.asyncio
async def test_cache_decorator_handles_redis_error():
    """Test @cache decorator handles Redis errors gracefully."""

    @cache.cache(ttl_seconds=3600, key_prefix="test")
    async def get_data(key: str) -> dict:
        return {"result": "fresh"}

    # Simulate cache_get raising an exception
    with patch.object(cache, "cache_get", side_effect=Exception("Redis connection error")):
        result = await get_data("mykey")
        # Should fall back to executing function
        assert result == {"result": "fresh"}
