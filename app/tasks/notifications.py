"""
ARQ background task: send_due_invoice_notifications

Runs daily at 08:00 (scheduled in worker.py).

Steps:
  1. Query sale_invoices WHERE status IN ('confirmed','partially_paid')
     AND due_date IS NOT NULL
     AND due_date <= CURRENT_DATE + 3  (due within 3 days OR already overdue).
  2. For each invoice:
     - due_date < today  → type = 'overdue'
     - due_date <= today + 3 → type = 'due'
     - Skip if a notification of the same type already exists for this invoice today.
  3. Bulk-insert Notification rows in batches of 100.

Returns: {"notifications_created": N}

Error handling:
  - Batch-level errors are logged; remaining batches continue processing.
  - Job-level errors are caught and logged without crashing the worker.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import islice

import structlog
from sqlalchemy import and_, func, select, text

from app.core.database import AsyncSessionLocal
from app.models.enums import NotificationType, SaleStatus
from app.models.sale import Notification, SaleInvoice

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 100
_DUE_WARN_DAYS = 3


def _batched(iterable, size: int):
    """Yield successive slices of `size` from an iterable."""
    it = iter(iterable)
    while batch := list(islice(it, size)):
        yield batch


async def send_due_invoice_notifications(ctx: dict) -> dict:
    """
    Create due / overdue notifications for sale invoices approaching their due date.
    Idempotent: skips invoices already notified with the same type today.
    """
    notifications_created = 0

    try:
        async with AsyncSessionLocal() as db:
            today = date.today()
            warn_cutoff = today + timedelta(days=_DUE_WARN_DAYS)

            # Invoices that are due or overdue
            invoices_result = await db.execute(
                select(
                    SaleInvoice.id,
                    SaleInvoice.invoice_no,
                    SaleInvoice.customer_id,
                    SaleInvoice.due_date,
                    SaleInvoice.due_amount,
                )
                .where(
                    and_(
                        SaleInvoice.status.in_(
                            [SaleStatus.confirmed, SaleStatus.partially_paid]
                        ),
                        SaleInvoice.due_date.is_not(None),
                        SaleInvoice.due_date <= warn_cutoff,
                        SaleInvoice.due_amount > 0,
                    )
                )
            )
            invoices = invoices_result.all()

            if not invoices:
                logger.info("send_due_invoice_notifications.no_invoices")
                return {"notifications_created": 0}

            invoice_ids = [row.id for row in invoices]

            # Already-notified invoice+type pairs today
            existing_result = await db.execute(
                select(Notification.invoice_id, Notification.type)
                .where(
                    and_(
                        Notification.invoice_id.in_(invoice_ids),
                        Notification.type.in_(
                            [NotificationType.due, NotificationType.overdue]
                        ),
                        func.date(Notification.sent_at) == today,
                    )
                )
            )
            already_notified: set[tuple[int, str]] = {
                (row.invoice_id, row.type.value)
                for row in existing_result.all()
            }

            # Build notification objects
            pending: list[Notification] = []
            for row in invoices:
                notif_type = (
                    NotificationType.overdue
                    if row.due_date < today
                    else NotificationType.due
                )
                key = (row.id, notif_type.value)
                if key in already_notified:
                    continue

                if notif_type == NotificationType.overdue:
                    days_overdue = (today - row.due_date).days
                    message = (
                        f"Invoice {row.invoice_no} is {days_overdue} day(s) overdue. "
                        f"Outstanding amount: {row.due_amount}."
                    )
                else:
                    days_left = (row.due_date - today).days
                    message = (
                        f"Invoice {row.invoice_no} is due in {days_left} day(s) "
                        f"({row.due_date}). Outstanding amount: {row.due_amount}."
                    )

                pending.append(
                    Notification(
                        customer_id=row.customer_id,
                        invoice_id=row.id,
                        type=notif_type,
                        message=message,
                        is_read=False,
                    )
                )

            # Bulk-insert in batches
            for batch in _batched(pending, _BATCH_SIZE):
                try:
                    async with db.begin():
                        db.add_all(batch)
                    notifications_created += len(batch)
                except Exception:
                    logger.exception(
                        "send_due_invoice_notifications.batch_failed",
                        batch_size=len(batch),
                    )

    except Exception:
        logger.exception("send_due_invoice_notifications.failed")
        return {"notifications_created": notifications_created, "error": True}

    logger.info(
        "send_due_invoice_notifications.completed",
        notifications_created=notifications_created,
    )
    return {"notifications_created": notifications_created}
