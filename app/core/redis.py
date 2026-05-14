"""
Async Redis connection for SmartLedger.

Provides a module-level connection pool and a FastAPI dependency (get_redis)
that yields a live Redis client for the duration of a request.

Usage in a route or dependency:
    from app.core.redis import get_redis
    from redis.asyncio import Redis

    async def some_dep(redis: Redis = Depends(get_redis)) -> ...:
        await redis.set("key", "value", ex=60)
"""

from collections.abc import AsyncGenerator

import structlog
from redis.asyncio import Redis, ConnectionPool

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Module-level pool — created once, shared across all requests.
# decode_responses=True so all values come back as str, not bytes.
_pool: ConnectionPool = ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
)


def get_redis_pool() -> ConnectionPool:
    """Return the shared connection pool (used by ARQ worker config)."""
    return _pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    FastAPI dependency — yields an async Redis client backed by the shared pool.

    The client is released back to the pool after the request completes.
    No explicit close is needed; the pool manages the lifecycle.
    """
    async with Redis(connection_pool=_pool) as client:
        yield client
