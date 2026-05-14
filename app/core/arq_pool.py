"""
ARQ connection pool for SmartLedger.

Provides a singleton ARQ Redis pool used by FastAPI routes to enqueue
background jobs without creating a new connection on every request.

Usage in a route / service:
    from app.core.arq_pool import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("generate_report_export", ...)

The pool is initialised lazily on first call and reused thereafter.
Call close_arq_pool() in the application shutdown lifecycle hook.
"""

from __future__ import annotations

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = structlog.get_logger(__name__)

_arq_pool: ArqRedis | None = None


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.REDIS_URL)


async def get_arq_pool() -> ArqRedis:
    """
    Return the shared ARQ Redis pool, creating it on first call.

    Thread-safe in a single-process async context (no lock needed —
    asyncio is cooperative and this coroutine is never suspended between
    the None-check and the assignment).
    """
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(_redis_settings())
        logger.info("arq_pool.created")
    return _arq_pool


async def close_arq_pool() -> None:
    """Close the pool gracefully. Called from the FastAPI shutdown hook."""
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
        logger.info("arq_pool.closed")
