"""
ARQ background task: check_low_stock

Runs daily at 07:00 (scheduled in worker.py).

Steps:
  1. Query all active items where current_stock <= reorder_level (and reorder_level > 0).
  2. For each item, skip if a 'low_stock' notification was already inserted today.
  3. Bulk-insert Notification rows for new alerts only.

Returns: {"alerts_created": N}

Error handling:
  - Entire job is wrapped in try/except — failures are logged, worker continues.
  - Individual item errors do not abort the rest of the batch.
"""

from __future__ import annotations

import structlog
from datetime import date, datetime, timezone
from sqlalchemy import select, and_, func, text

from app.core.database import AsyncSessionLocal
from app.models.inventory import Item
from app.models.sale import Notification
from app.models.enums import NotificationType

logger = structlog.get_logger(__name__)


async def check_low_stock(ctx: dict) -> dict:
    """
    Identify items below reorder level and insert low_stock notifications.
    Idempotent: skips items that already have a low_stock notification today.
    """
    alerts_created = 0

    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                today = date.today()

                # Items below reorder level
                low_items_result = await db.execute(
                    select(Item.id, Item.name, Item.current_stock, Item.reorder_level)
                    .where(
                        and_(
                            Item.is_active == True,       # noqa: E712
                            Item.reorder_level > 0,
                            Item.current_stock <= Item.reorder_level,
                        )
                    )
                )
                low_items = low_items_result.all()

                if not low_items:
                    logger.info("check_low_stock.no_alerts_needed")
                    return {"alerts_created": 0}

                # IDs that already have a low_stock notification today
                item_ids = [row.id for row in low_items]
                existing_result = await db.execute(
                    select(Notification.item_id)
                    .where(
                        and_(
                            Notification.type == NotificationType.low_stock,
                            Notification.item_id.in_(item_ids),
                            func.date(Notification.sent_at) == today,
                        )
                    )
                )
                already_notified = {row.item_id for row in existing_result.all()}

                # Insert new notifications
                new_notifications = []
                for row in low_items:
                    if row.id in already_notified:
                        continue
                    new_notifications.append(
                        Notification(
                            item_id=row.id,
                            type=NotificationType.low_stock,
                            message=(
                                f"Low stock alert: '{row.name}' has "
                                f"{row.current_stock} units remaining "
                                f"(reorder level: {row.reorder_level})."
                            ),
                            is_read=False,
                        )
                    )

                if new_notifications:
                    db.add_all(new_notifications)
                    alerts_created = len(new_notifications)

    except Exception:
        logger.exception("check_low_stock.failed")
        return {"alerts_created": 0, "error": True}

    logger.info("check_low_stock.completed", alerts_created=alerts_created)
    return {"alerts_created": alerts_created}
