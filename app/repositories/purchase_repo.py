"""
Repository for the Purchases module. Data access only — no business logic.

Entities:
  PurchaseRepository        — header CRUD + filtered list
  PurchaseItemRepository    — line item bulk insert
  PurchasePaymentRepository — payment row insert
  PurchaseReturnRepository  — return header + items
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import PaymentType, PurchaseStatus, ReturnStatus
from app.models.purchase import Purchase, PurchaseItem, PurchasePayment, PurchaseReturn, PurchaseReturnItem
from app.repositories.base_repo import BaseRepository


class PurchaseRepository(BaseRepository[Purchase]):
    model = Purchase

    async def get_with_items(self, db: AsyncSession, purchase_id: int) -> Purchase | None:
        """Load purchase with line items (and their item/unit) eagerly (for detail view)."""
        result = await db.execute(
            select(Purchase)
            .options(
                selectinload(Purchase.items).selectinload(PurchaseItem.item),
                selectinload(Purchase.items).selectinload(PurchaseItem.unit),
                selectinload(Purchase.supplier),
            )
            .where(Purchase.id == purchase_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_with_lock(self, db: AsyncSession, purchase_id: int) -> Purchase | None:
        """SELECT FOR UPDATE — for paid_amount mutations."""
        result = await db.execute(
            select(Purchase).where(Purchase.id == purchase_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_purchases(
        self,
        db: AsyncSession,
        *,
        supplier_id: int | None = None,
        status: PurchaseStatus | None = None,
        payment_type: PaymentType | None = None,
        search: str | None = None,
        from_date=None,
        to_date=None,
        skip: int = 0,
        limit: int = 20,
        sort_by: Literal["purchase_date", "total_amount", "created_at"] = "purchase_date",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> tuple[list[Purchase], int]:
        conditions = []
        if supplier_id is not None:
            conditions.append(Purchase.supplier_id == supplier_id)
        if status is not None:
            conditions.append(Purchase.status == status)
        if payment_type is not None:
            conditions.append(Purchase.payment_type == payment_type)
        if search is not None:
            conditions.append(Purchase.invoice_no.ilike(f"%{search}%"))
        if from_date is not None:
            conditions.append(Purchase.purchase_date >= from_date)
        if to_date is not None:
            conditions.append(Purchase.purchase_date <= to_date)

        stmt = select(Purchase).options(selectinload(Purchase.supplier))
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "purchase_date": Purchase.purchase_date,
            "total_amount": Purchase.total_amount,
            "created_at": Purchase.created_at,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def update_totals(
        self,
        db: AsyncSession,
        purchase: Purchase,
        *,
        subtotal: Decimal,
        discount: Decimal,
        total_amount: Decimal,
    ) -> None:
        """Write computed totals back to the purchase header."""
        purchase.subtotal = subtotal
        purchase.discount = discount
        purchase.total_amount = total_amount
        db.add(purchase)

    async def add_paid_amount(
        self,
        db: AsyncSession,
        purchase: Purchase,
        *,
        amount: Decimal,
    ) -> None:
        """Increment paid_amount on a locked purchase row."""
        purchase.paid_amount += amount
        db.add(purchase)

    async def set_status(
        self,
        db: AsyncSession,
        purchase: Purchase,
        *,
        status: PurchaseStatus,
        confirmed_by: int | None = None,
        confirmed_at: datetime | None = None,
    ) -> None:
        purchase.status = status
        if confirmed_by is not None:
            purchase.confirmed_by = confirmed_by
        if confirmed_at is not None:
            purchase.confirmed_at = confirmed_at
        db.add(purchase)


class PurchaseItemRepository:

    async def bulk_create(
        self,
        db: AsyncSession,
        items: list[dict[str, Any]],
    ) -> list[PurchaseItem]:
        objs = [PurchaseItem(**item) for item in items]
        db.add_all(objs)
        await db.flush()
        return objs

    async def get_for_purchase(
        self, db: AsyncSession, purchase_id: int
    ) -> list[PurchaseItem]:
        result = await db.execute(
            select(PurchaseItem).where(PurchaseItem.purchase_id == purchase_id)
        )
        return list(result.scalars().all())


class PurchasePaymentRepository:

    async def save(
        self,
        db: AsyncSession,
        *,
        purchase_id: int,
        amount: Decimal,
        payment_mode,
        account_id: int | None,
        reference_no: str | None,
        paid_at: datetime,
        created_by: int | None,
    ) -> PurchasePayment:
        payment = PurchasePayment(
            purchase_id=purchase_id,
            amount=amount,
            payment_mode=payment_mode,
            account_id=account_id,
            reference_no=reference_no,
            paid_at=paid_at,
            created_by=created_by,
        )
        db.add(payment)
        await db.flush()
        await db.refresh(payment)
        return payment

    async def list_for_purchase(
        self, db: AsyncSession, purchase_id: int
    ) -> list[PurchasePayment]:
        result = await db.execute(
            select(PurchasePayment)
            .where(PurchasePayment.purchase_id == purchase_id)
            .order_by(PurchasePayment.paid_at)
        )
        return list(result.scalars().all())


class PurchaseReturnRepository:

    async def create_return(
        self,
        db: AsyncSession,
        *,
        purchase_id: int,
        return_type: str,
        reason: str | None,
        total_amount: Decimal,
        penalty: Decimal,
        refund_amount: Decimal,
        created_by: int | None,
    ) -> PurchaseReturn:
        ret = PurchaseReturn(
            purchase_id=purchase_id,
            return_type=return_type,
            reason=reason,
            total_amount=total_amount,
            penalty=penalty,
            refund_amount=refund_amount,
            status=ReturnStatus.pending,
            created_by=created_by,
        )
        db.add(ret)
        await db.flush()
        await db.refresh(ret)
        return ret

    async def bulk_create_items(
        self,
        db: AsyncSession,
        items: list[dict[str, Any]],
    ) -> list[PurchaseReturnItem]:
        objs = [PurchaseReturnItem(**item) for item in items]
        db.add_all(objs)
        await db.flush()
        return objs

    async def get_with_items(
        self, db: AsyncSession, return_id: int
    ) -> PurchaseReturn | None:
        result = await db.execute(
            select(PurchaseReturn)
            .options(selectinload(PurchaseReturn.return_items))
            .where(PurchaseReturn.id == return_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_for_purchase(
        self, db: AsyncSession, purchase_id: int
    ) -> list[PurchaseReturn]:
        result = await db.execute(
            select(PurchaseReturn)
            .where(PurchaseReturn.purchase_id == purchase_id)
            .order_by(desc(PurchaseReturn.created_at))
        )
        return list(result.scalars().all())

    async def approve(
        self,
        db: AsyncSession,
        purchase_return: PurchaseReturn,
        *,
        approved_by: int,
        approved_at: datetime,
    ) -> None:
        purchase_return.status = ReturnStatus.approved
        purchase_return.approved_by = approved_by
        purchase_return.approved_at = approved_at
        db.add(purchase_return)
        await db.flush()

    async def reject(
        self,
        db: AsyncSession,
        purchase_return: PurchaseReturn,
        *,
        rejected_by: int,
        rejected_at: datetime,
    ) -> None:
        purchase_return.status = ReturnStatus.rejected
        purchase_return.approved_by = rejected_by   # reuse column to record who acted
        purchase_return.approved_at = rejected_at
        db.add(purchase_return)
        await db.flush()
