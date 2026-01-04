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

    Returns:
        Shared Redis client instance.
    """
    global _redis_client, _redis_pool

    if _redis_client is None:
        _redis_pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
            max_connections=10,
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
