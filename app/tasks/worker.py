"""
ARQ worker configuration for SmartLedger.

Run the worker with:
    arq app.tasks.worker.WorkerSettings

In production (via supervisor / systemd):
    arq app.tasks.worker.WorkerSettings --watch app/

Cron schedule (all times UTC):
  07:00  check_low_stock
  08:00  send_due_invoice_notifications
  02:00  refresh_materialized_views
  03:00  cleanup_old_exports

On-demand (enqueued by API):
  generate_report_export — POST /reports/{report_name}/export
"""

from __future__ import annotations

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.database import AsyncSessionLocal, async_engine
from app.tasks.notifications import send_due_invoice_notifications
from app.tasks.report_export import cleanup_old_exports, generate_report_export
from app.tasks.report_refresh import refresh_materialized_views
from app.tasks.stock_alerts import check_low_stock

logger = structlog.get_logger(__name__)


def startup(ctx: dict) -> None:
    """Store the DB session factory in the ARQ context on worker start."""
    ctx["db_factory"] = AsyncSessionLocal
    logger.info("arq_worker.started")


async def shutdown(_ctx: dict) -> None:
    """Dispose the DB engine connection pool on worker stop."""
    await async_engine.dispose()
    logger.info("arq_worker.stopped")


class WorkerSettings:
    functions = [
        check_low_stock,
        send_due_invoice_notifications,
        refresh_materialized_views,
        generate_report_export,
        cleanup_old_exports,
    ]

    cron_jobs = [
        cron(check_low_stock, hour=7, minute=0),
        cron(send_due_invoice_notifications, hour=8, minute=0),
        cron(refresh_materialized_views, hour=2, minute=0),
        cron(cleanup_old_exports, hour=3, minute=0),
    ]

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    max_jobs = 20
    job_timeout = 300
    keep_result = 3600
    retry_jobs = True
    max_tries = 3

    on_startup = startup
    on_shutdown = shutdown
