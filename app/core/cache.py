"""
Redis caching utilities with connection pooling.

Provides a simple async caching decorator that handles cache hits/misses
and falls back gracefully on errors.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# Cache TTL Constants
# =============================================================================

# Default TTL for ongoing shows (episodes air weekly at most)
CACHE_TTL_ONGOING = 604800  # 7 days

# Extended TTL for finished shows (data won't change)
CACHE_TTL_FINISHED = 31536000  # 1 year (365 days)

# Note: Master show list TTL is in app.core.constants.CACHE_TTL_SHOWS_METADATA_SECONDS

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

    Pool is sized for typical API workloads (20 concurrent connections).
    """
    global _redis_client, _redis_pool

    if _redis_client is None:
        _redis_pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
            max_connections=20,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
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
        deleted = await redis.delete(cache_key)
        if deleted:
            logger.info("Invalidated cache: %s", cache_key)
        return deleted > 0
    except Exception as e:
        logger.error("Failed to invalidate cache %s:%s: %s", key_prefix, key_suffix, e)
        return False


async def get_cache_ttl(key_prefix: str, key_suffix: str) -> int | None:
    """
    Get remaining TTL for a cache key.

    Returns:
        TTL in seconds, or None if key doesn't exist.
    """
    try:
        redis = await get_redis()
        cache_key = f"{key_prefix}:{key_suffix}"
        ttl = await redis.ttl(cache_key)
        return ttl if ttl > 0 else None
    except Exception:
        return None


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
        result = await redis.expire(cache_key, new_ttl)
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
        return await redis.get(key)
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
        return await redis.hget(hash_key, field)
    except Exception as e:
        logger.warning("Cache hash read error for %s[%s]: %s", hash_key, field, e)
        return None


async def cache_exists(key: str) -> bool:
    """Check if key exists in cache."""
    try:
        redis = await get_redis()
        return await redis.exists(key) > 0
    except Exception:
        return False


# =============================================================================
# Caching Decorator
# =============================================================================


def cache(
    ttl_seconds: int = settings.CACHE_TTL_SECONDS,
    key_prefix: str = "",
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Awaitable[R]]]:
    """
    Async caching decorator using Redis.

    Uses the first function argument as the cache key suffix.
    Falls back to calling the function on cache errors.

    Args:
        ttl_seconds: Cache time-to-live in seconds.
        key_prefix: Prefix for cache keys (e.g., "episodes", "shows").

    Returns:
        Decorator function.

    Example:
        @cache(ttl_seconds=3600, key_prefix="show")
        async def get_show(show_id: str) -> dict:
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Build cache key from first positional argument
            cache_key_suffix = args[0] if args else "global"
            cache_key = f"{key_prefix}:{cache_key_suffix}"

            redis = await get_redis()

            try:
                # Check cache
                cached = await redis.get(cache_key)
                if cached:
                    logger.debug("Cache hit: %s", cache_key)
                    return json.loads(cached)  # type: ignore[return-value]

                # Cache miss - call function
                logger.debug("Cache miss: %s", cache_key)
                result = await func(*args, **kwargs)

                # Store result if not empty
                if result:
                    await redis.setex(cache_key, ttl_seconds, json.dumps(result, default=str))

                return result

            except Exception as e:
                logger.error("Cache error for %s: %s", cache_key, e)
                # Fallback to direct function call
                return await func(*args, **kwargs)

        return wrapper

    return decorator
