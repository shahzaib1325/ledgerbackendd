"""
Repository for the Sales module. Data access only — no business logic.

Entities:
  SaleRepository        — header CRUD + filtered list
  SaleItemRepository    — line item bulk insert
  SalePaymentRepository — payment row insert + list
  SaleReturnRepository  — return header + items
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, asc, delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import ReturnStatus, SaleStatus
from app.models.sale import SaleInvoice, SaleItem, SalePayment, SaleReturn, SaleReturnItem
from app.repositories.base_repo import BaseRepository


class SaleRepository(BaseRepository[SaleInvoice]):
    model = SaleInvoice

    async def get_with_items(self, db: AsyncSession, invoice_id: int) -> SaleInvoice | None:
        result = await db.execute(
            select(SaleInvoice)
            .options(selectinload(SaleInvoice.items), selectinload(SaleInvoice.customer))
            .where(SaleInvoice.id == invoice_id)
        )
        return result.scalar_one_or_none()

    async def get_with_lock(self, db: AsyncSession, invoice_id: int) -> SaleInvoice | None:
        result = await db.execute(
            select(SaleInvoice).where(SaleInvoice.id == invoice_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_sales(
        self,
        db: AsyncSession,
        *,
        customer_id: int | None = None,
        status: SaleStatus | None = None,
        from_date=None,
        to_date=None,
        overdue_only: bool = False,
        skip: int = 0,
        limit: int = 20,
        sort_by: Literal["invoice_date", "total_amount", "created_at", "due_date"] = "invoice_date",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> tuple[list[SaleInvoice], int]:
        from datetime import date

        conditions = []
        if customer_id is not None:
            conditions.append(SaleInvoice.customer_id == customer_id)
        if status is not None:
            conditions.append(SaleInvoice.status == status)
        if from_date is not None:
            conditions.append(SaleInvoice.invoice_date >= from_date)
        if to_date is not None:
            conditions.append(SaleInvoice.invoice_date <= to_date)
        if overdue_only:
            conditions.append(SaleInvoice.due_date < date.today())
            conditions.append(SaleInvoice.due_amount > 0)

        stmt = select(SaleInvoice).options(selectinload(SaleInvoice.customer))
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "invoice_date": SaleInvoice.invoice_date,
            "total_amount": SaleInvoice.total_amount,
            "created_at": SaleInvoice.created_at,
            "due_date": SaleInvoice.due_date,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def add_paid_amount(
        self,
        db: AsyncSession,
        invoice: SaleInvoice,
        *,
        amount: Decimal,
    ) -> None:
        invoice.paid_amount += amount
        # Recompute status based on new paid_amount
        new_paid = invoice.paid_amount
        if new_paid >= invoice.total_amount:
            invoice.status = SaleStatus.paid
        elif new_paid > Decimal("0"):
            invoice.status = SaleStatus.partially_paid
        db.add(invoice)

    async def set_status(
        self,
        db: AsyncSession,
        invoice: SaleInvoice,
        *,
        status: SaleStatus,
        confirmed_by: int | None = None,
        confirmed_at: datetime | None = None,
    ) -> None:
        invoice.status = status
        if confirmed_by is not None:
            invoice.confirmed_by = confirmed_by
        if confirmed_at is not None:
            invoice.confirmed_at = confirmed_at
        db.add(invoice)


class SaleItemRepository:

    async def bulk_create(
        self,
        db: AsyncSession,
        items: list[dict[str, Any]],
    ) -> list[SaleItem]:
        objs = [SaleItem(**item) for item in items]
        db.add_all(objs)
        await db.flush()
        return objs

    async def delete_for_invoice(self, db: AsyncSession, invoice_id: int) -> None:
        await db.execute(delete(SaleItem).where(SaleItem.invoice_id == invoice_id))


class SalePaymentRepository:

    async def save(
        self,
        db: AsyncSession,
        *,
        invoice_id: int,
        amount: Decimal,
        payment_mode,
        account_id: int | None,
        reference_no: str | None,
        received_at: datetime,
        created_by: int | None,
    ) -> SalePayment:
        payment = SalePayment(
            invoice_id=invoice_id,
            amount=amount,
            payment_mode=payment_mode,
            account_id=account_id,
            reference_no=reference_no,
            received_at=received_at,
            created_by=created_by,
        )
        db.add(payment)
        await db.flush()
        await db.refresh(payment)
        return payment

    async def list_for_invoice(
        self, db: AsyncSession, invoice_id: int
    ) -> list[SalePayment]:
        result = await db.execute(
            select(SalePayment)
            .where(SalePayment.invoice_id == invoice_id)
            .order_by(SalePayment.received_at)
        )
        return list(result.scalars().all())


class SaleReturnRepository:

    async def create_return(
        self,
        db: AsyncSession,
        *,
        invoice_id: int,
        return_type: str,
        reason: str | None,
        total_amount: Decimal,
        penalty: Decimal,
        refund_amount: Decimal,
        created_by: int | None,
    ) -> SaleReturn:
        ret = SaleReturn(
            invoice_id=invoice_id,
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
    ) -> list[SaleReturnItem]:
        objs = [SaleReturnItem(**item) for item in items]
        db.add_all(objs)
        await db.flush()
        return objs

    async def get_with_items(
        self, db: AsyncSession, return_id: int
    ) -> SaleReturn | None:
        result = await db.execute(
            select(SaleReturn)
            .options(selectinload(SaleReturn.return_items))
            .where(SaleReturn.id == return_id)
        )
        return result.scalar_one_or_none()

    async def list_for_invoice(
        self, db: AsyncSession, invoice_id: int
    ) -> list[SaleReturn]:
        result = await db.execute(
            select(SaleReturn)
            .options(selectinload(SaleReturn.return_items))
            .where(SaleReturn.invoice_id == invoice_id)
            .order_by(desc(SaleReturn.created_at))
        )
        return list(result.scalars().all())

    async def approve(
        self,
        db: AsyncSession,
        sale_return: SaleReturn,
        *,
        approved_by: int,
        approved_at: datetime,
    ) -> None:
        sale_return.status = ReturnStatus.approved
        sale_return.approved_by = approved_by
        sale_return.approved_at = approved_at
        db.add(sale_return)
        await db.flush()

    async def reject(
        self,
        db: AsyncSession,
        sale_return: SaleReturn,
        *,
        rejected_by: int,
        rejected_at: datetime,
        rejection_reason: str | None,
    ) -> None:
        sale_return.status = ReturnStatus.rejected
        sale_return.rejected_by = rejected_by
        sale_return.rejected_at = rejected_at
        sale_return.rejection_reason = rejection_reason
        db.add(sale_return)
        await db.flush()

    async def get_approved_qty_by_item(
        self,
        db: AsyncSession,
        invoice_id: int,
        item_id: int,
    ) -> "Decimal":
        from decimal import Decimal
        result = await db.execute(
            select(func.coalesce(func.sum(SaleReturnItem.quantity), 0))
            .join(SaleReturn, SaleReturnItem.return_id == SaleReturn.id)
            .where(
                SaleReturn.invoice_id == invoice_id,
                SaleReturn.status == ReturnStatus.approved,
                SaleReturnItem.item_id == item_id,
            )
        )
        return Decimal(str(result.scalar_one()))
