"""
ARQ background task: refresh_materialized_views

Runs nightly at 02:00 (scheduled in worker.py).

Refreshes PostgreSQL materialized views used by the Reports module.
Views are refreshed CONCURRENTLY so reads can continue during the refresh
(no exclusive table lock).

Refresh order matters — views that depend on others come last:
  1. mv_stock_valuation        — stock quantities × last purchase price
  2. mv_supplier_balances      — aggregated supplier balance snapshot
  3. mv_customer_balances      — aggregated customer balance snapshot
  4. mv_profit_loss            — monthly P&L summary (depends on sales + purchases)

Error handling:
  - Each view refresh is wrapped individually. If one fails, the others continue.
  - Final result reports which views succeeded and which failed.
  - Job-level errors are caught and logged without crashing the worker.

Returns: {"refreshed": [...], "failed": [...]}
"""

from __future__ import annotations

import structlog
from sqlalchemy import text

from app.core.database import async_engine

logger = structlog.get_logger(__name__)

# Views refreshed in dependency order
_VIEWS = [
    "mv_stock_valuation",
    "mv_supplier_balances",
    "mv_customer_balances",
    "mv_profit_loss",
]


async def refresh_materialized_views(ctx: dict) -> dict:
    """
    Refresh all report materialized views nightly.
    Each view is attempted independently — partial success is acceptable.
    """
    refreshed: list[str] = []
    failed: list[str] = []

    for view in _VIEWS:
        try:
            # Use a raw connection — REFRESH MATERIALIZED VIEW is DDL,
            # not compatible with SQLAlchemy ORM transaction management.
            async with async_engine.connect() as conn:
                await conn.execute(
                    text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
                )
                await conn.commit()
            refreshed.append(view)
            logger.info("refresh_materialized_views.view_refreshed", view=view)
        except Exception:
            failed.append(view)
            logger.exception(
                "refresh_materialized_views.view_failed", view=view
            )

    logger.info(
        "refresh_materialized_views.completed",
        refreshed=refreshed,
        failed=failed,
    )
    return {"refreshed": refreshed, "failed": failed}
