import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis connection pool
_redis_pool: ConnectionPool | None = None
_redis_client: Redis | None = None

F = TypeVar("F", bound=Callable[..., Any])


async def get_redis() -> Redis:
    """Get or create Redis client with connection pooling."""
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


async def close_redis_pool():
    """Close the global Redis connection pool."""
    global _redis_pool, _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


def cache(ttl_seconds: int = settings.CACHE_TTL_SECONDS, key_prefix: str = ""):
    """
    Simple async caching decorator using Redis connection pool.
    Uses the first function argument as the cache key.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build cache key from first argument (after self if method)
            cache_key_arg = args[1] if len(args) > 1 else (args[0] if args else "global")
            cache_key = f"{key_prefix}:{cache_key_arg}"

            redis = await get_redis()

            try:
                cached = await redis.get(cache_key)
                if cached:
                    logger.debug(f"Cache hit: {cache_key}")
                    return json.loads(cached)

                logger.debug(f"Cache miss: {cache_key}")
                result = await func(*args, **kwargs)

                if result:
                    await redis.setex(cache_key, ttl_seconds, json.dumps(result, default=str))

                return result
            except Exception as e:
                logger.error(f"Cache error for {cache_key}: {e}")
                return await func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator
