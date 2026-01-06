"""
Redis caching utilities with connection pooling.

Provides a simple async caching decorator that handles cache hits/misses
and falls back gracefully on errors.
"""

import logging
import re
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

import orjson
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# Cache TTL Constants (Single Source of Truth)
# =============================================================================

TTL_7_DAYS = 86400 * 7  # Ongoing shows, seasons, episodes
TTL_30_DAYS = 86400 * 30  # Show list, indexes
TTL_1_YEAR = 86400 * 365  # Finished shows (data won't change)

# =============================================================================
# Type Variables
# =============================================================================

P = ParamSpec("P")
R = TypeVar("R")

# =============================================================================
# Global Connection Pool
# =============================================================================

_redis_pool: ConnectionPool | None = None
_redis_client: Redis | None = None


async def get_redis() -> Redis:
    """
    Get or create Redis client with connection pooling.

    Pool is sized for production workloads:
    - 12 uvicorn workers × 10 connections each = 120 max connections
    - Socket timeouts prevent hanging on network issues
    - Health check interval ensures dead connections are recycled
    """
    global _redis_client, _redis_pool

    if _redis_client is None:
        _redis_pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        _redis_client = Redis(connection_pool=_redis_pool)

    return _redis_client


async def close_redis_pool() -> None:
    """
    Close the global Redis connection pool.

    Should be called during application shutdown.
    """
    global _redis_pool, _redis_client

    if _redis_client:
        await _redis_client.close()
        _redis_client = None

    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


async def invalidate_cache(key_prefix: str, key_suffix: str) -> bool:
    """
    Invalidate a specific cache entry.

    Args:
        key_prefix: Cache key prefix (e.g., "episodes")
        key_suffix: Cache key suffix (e.g., "breakingbad")

    Returns:
        True if key was deleted, False otherwise.
    """
    try:
        redis = await get_redis()
        cache_key = f"{key_prefix}:{key_suffix}"
        deleted = cast(int, await redis.delete(cache_key))
        if deleted:
            logger.info("Invalidated cache: %s", cache_key)
        return bool(deleted > 0)
    except Exception as e:
        logger.error("Failed to invalidate cache %s:%s: %s", key_prefix, key_suffix, e)
        return False


async def extend_cache_ttl(key_prefix: str, key_suffix: str, new_ttl: int) -> bool:
    """
    Extend the TTL of a cache key (e.g., for finished shows).

    Args:
        key_prefix: Cache key prefix (e.g., "episodes")
        key_suffix: Cache key suffix (e.g., "breakingbad")
        new_ttl: New TTL in seconds

    Returns:
        True if TTL was extended, False otherwise.
    """
    try:
        redis = await get_redis()
        cache_key = f"{key_prefix}:{key_suffix}"
        result = cast(bool, await redis.expire(cache_key, new_ttl))
        if result:
            logger.info("Extended cache TTL for %s to %d seconds", cache_key, new_ttl)
        return result
    except Exception as e:
        logger.error("Failed to extend cache TTL for %s:%s: %s", key_prefix, key_suffix, e)
        return False


# =============================================================================
# Simple Cache Helpers
# =============================================================================


async def cache_get(key: str) -> str | None:
    """Get raw value from cache, or None on miss/error."""
    try:
        redis = await get_redis()
        result = cast(str | None, await redis.get(key))
        return result
    except Exception as e:
        logger.warning("Cache read error for %s: %s", key, e)
        return None


async def cache_set(key: str, value: str, ttl: int) -> None:
    """Set value in cache with TTL. Fails silently."""
    try:
        redis = await get_redis()
        await redis.setex(key, ttl, value)
    except Exception as e:
        logger.warning("Cache write error for %s: %s", key, e)


async def cache_delete(*keys: str) -> None:
    """Delete one or more cache keys. Fails silently."""
    try:
        redis = await get_redis()
        await redis.delete(*keys)
    except Exception as e:
        logger.warning("Cache delete error: %s", e)


async def cache_hget(hash_key: str, field: str) -> str | None:
    """Get field from hash, or None on miss/error."""
    try:
        redis = await get_redis()
        # redis.hget returns Awaitable[str | None] but type stubs are wrong
        result: str | None = await redis.hget(hash_key, field)  # type: ignore[misc]
        return result
    except Exception as e:
        logger.warning("Cache hash read error for %s[%s]: %s", hash_key, field, e)
        return None


async def cache_exists(key: str) -> bool:
    """Check if key exists in cache."""
    try:
        redis = await get_redis()
        count = cast(int, await redis.exists(key))
        return bool(count > 0)
    except Exception:
        return False


# =============================================================================
# Caching Decorators
# =============================================================================


def cache(
    ttl_seconds: int = settings.CACHE_TTL_SECONDS,
    key_prefix: str = "",
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Awaitable[R]]]:
    """
    Async caching decorator for raw JSON data.

    Uses the first function argument as the cache key suffix.
    Falls back to calling the function on cache errors.

    Args:
        ttl_seconds: Cache time-to-live in seconds.
        key_prefix: Prefix for cache keys (e.g., "episodes", "shows").

    Example:
        @cache(ttl_seconds=3600, key_prefix="raw_data")
        async def fetch_data(key: str) -> dict:
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            cache_key_suffix = args[0] if args else "global"
            cache_key = f"{key_prefix}:{cache_key_suffix}"

            try:
                cached = await cache_get(cache_key)
                if cached:
                    try:
                        return orjson.loads(cached)  # type: ignore
                    except orjson.JSONDecodeError as e:
                        # Corrupted JSON - log warning (cache cleared on deployment)
                        logger.warning("Corrupted JSON in cache %s: %s", cache_key, e)

                result = await func(*args, **kwargs)
                if result:
                    await cache_set(cache_key, orjson.dumps(result).decode(), ttl_seconds)
                return result
            except Exception as e:
                logger.error("Cache error for %s: %s", cache_key, e)
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def cached(
    key_template: str,
    ttl: int,
    model: type | None = None,
    is_list: bool = False,
    key_transform: Callable[[str], str] | None = None,
    ttl_if: Callable[[Any], int | None] | None = None,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Awaitable[R]]]:
    """
    Clean caching decorator for Pydantic models.

    Args:
        key_template: Cache key template using named parameter, e.g. "show:{show_id}".
                      The parameter name must match the first function argument.
        ttl: Default TTL in seconds.
        model: Pydantic model class for deserialization (optional).
        is_list: If True, deserialize as list of models.
        key_transform: Transform function for the cache key arg (e.g., normalize_show_id).
        ttl_if: Function to override TTL based on result. Return new TTL or None to use default.

    Example:
        @cached("show:{show_id}", ttl=TTL_7_DAYS, model=ShowSchema, key_transform=normalize_id)
        async def get_show(show_id: str) -> ShowSchema | None:
            # Just business logic, no cache boilerplate
            ...

        @cached("episodes:{show_id}", ttl=TTL_7_DAYS, model=EpisodeSchema, is_list=True)
        async def get_episodes(show_id: str) -> list[EpisodeSchema]:
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Build cache key using first argument (or "global" for no-arg functions)
            key_arg = str(args[0]) if args else "global"
            if key_transform:
                key_arg = key_transform(key_arg)

            # Replace any {placeholder} with the key_arg value
            cache_key = re.sub(r"\{[^}]+\}", key_arg, key_template)

            # Check cache (use orjson for faster parsing)
            cached_data = await cache_get(cache_key)
            if cached_data:
                try:
                    data = orjson.loads(cached_data)
                    if model:
                        if is_list:
                            return [model(**item) for item in data]  # type: ignore
                        return model(**data) if data else None  # type: ignore
                    return data  # type: ignore
                except orjson.JSONDecodeError as e:
                    # Corrupted JSON - log warning (cache cleared on deployment)
                    logger.warning("Corrupted JSON in cache %s: %s", cache_key, e)
                except Exception as e:
                    # Pydantic validation error - log and continue to fetch fresh
                    logger.warning("Cache validation error for %s: %s", cache_key, e)

            # Cache miss or error - execute function
            result = await func(*args, **kwargs)

            # Cache the result
            if result is not None:
                # Determine TTL (allow override based on result)
                final_ttl = ttl
                if ttl_if:
                    override = ttl_if(result)
                    if override is not None:
                        final_ttl = override

                # Serialize (use orjson for speed, type: ignore needed as R is generic)
                if model:
                    if is_list:
                        items = list(result)  # type: ignore
                        serialized = orjson.dumps([i.model_dump(mode="json") for i in items]).decode()
                    else:
                        serialized = result.model_dump_json()  # type: ignore
                else:
                    serialized = orjson.dumps(result).decode()

                await cache_set(cache_key, serialized, final_ttl)

            return result

        return wrapper

    return decorator


# =============================================================================
# Cache Statistics
# =============================================================================


async def get_cache_stats() -> dict[str, Any]:
    """
    Get cache statistics for monitoring.

    Returns counts of cached items by type and Redis memory usage.
    """
    try:
        redis = await get_redis()

        # Get all keys and categorize them
        keys: list[bytes] = await redis.keys("*")
        key_strings = [k.decode() if isinstance(k, bytes) else k for k in keys]

        # Categorize keys
        shows_cached = sum(1 for k in key_strings if k.startswith("show:") and not k.endswith(":raw"))
        episodes_cached = sum(1 for k in key_strings if k.startswith("episodes:"))
        seasons_cached = sum(1 for k in key_strings if k.startswith("seasons:"))
        search_cached = sum(1 for k in key_strings if k.startswith("search:"))

        # Check for master caches
        has_show_list = "shows:all:raw" in key_strings
        has_show_index = "show_index" in key_strings

        # Get TTL for key caches
        ttls = {}
        for key_name, prefix in [
            ("shows_list", "shows:all:raw"),
            ("show_index", "show_index"),
        ]:
            if prefix in key_strings:
                ttl = await redis.ttl(prefix)
                ttls[key_name] = ttl if ttl > 0 else "no expiry"

        # Get Redis memory info
        info: dict[str, Any] = await redis.info("memory")
        used_memory = info.get("used_memory_human", "unknown")
        peak_memory = info.get("used_memory_peak_human", "unknown")

        return {
            "status": "connected",
            "total_keys": len(key_strings),
            "cached_items": {
                "shows": shows_cached,
                "episodes": episodes_cached,
                "seasons": seasons_cached,
                "searches": search_cached,
            },
            "master_caches": {
                "show_list": has_show_list,
                "show_index": has_show_index,
            },
            "ttl_seconds": ttls,
            "ttl_config": {
                "ongoing_shows": f"{TTL_7_DAYS} (7 days)",
                "finished_shows": f"{TTL_1_YEAR} (1 year)",
                "show_list": f"{TTL_30_DAYS} (30 days)",
            },
            "memory": {
                "used": used_memory,
                "peak": peak_memory,
            },
        }
    except Exception as e:
        logger.error("Failed to get cache stats: %s", e)
        return {
            "status": "error",
            "error": str(e),
        }
