"""
Repository for the Supplier module.

Responsibility: data access ONLY.
- No balance arithmetic or business rules here.
- Balance mutations are performed by the Service, which passes the
  already-computed new_balance and new_balance_type to apply_balance_update().
- SELECT FOR UPDATE is provided via get_with_lock(); callers (the Service)
  must call it inside an active transaction.

Specialised queries:
  get_with_lock        — SELECT FOR UPDATE (balance mutations)
  apply_balance_update — write pre-computed balance back to the locked row
  save_payment         — insert SupplierPayment row only (no balance math)
  list_suppliers       — filtered, sorted, paginated
  get_payments         — payment history (paginated)
  get_ledger           — purchases + payments UNION with running balance
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import Date, and_, asc, desc, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BalanceType
from app.models.supplier import Supplier, SupplierPayment
from app.repositories.base_repo import BaseRepository


class SupplierRepository(BaseRepository[Supplier]):
    model = Supplier

    # ── Locking ───────────────────────────────────────────────────────────────

    async def get_with_lock(self, db: AsyncSession, supplier_id: int) -> Supplier | None:
        """
        SELECT FOR UPDATE — must be called inside an open transaction.
        Returns None if the supplier does not exist.
        """
        result = await db.execute(
            select(Supplier)
            .where(Supplier.id == supplier_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    # ── Balance write-back (pure DB, no math) ─────────────────────────────────

    async def apply_balance_update(
        self,
        db: AsyncSession,
        supplier: Supplier,
        *,
        new_balance: Decimal,
        new_balance_type: BalanceType,
    ) -> None:
        """
        Persist the pre-computed balance fields onto an already-locked Supplier.
        The Service is responsible for all arithmetic before calling this.
        """
        supplier.balance = new_balance
        supplier.balance_type = new_balance_type
        db.add(supplier)
        # Caller (service) issues db.flush() after inserting the payment row.

    # ── Payment row insertion (no balance side-effects) ───────────────────────

    async def save_payment(
        self,
        db: AsyncSession,
        *,
        supplier_id: int,
        amount: Decimal,
        payment_mode,
        account_id: int | None,
        reference_no: str | None,
        note: str | None,
        paid_at: datetime,
        created_by: int | None,
    ) -> SupplierPayment:
        """Insert the SupplierPayment row. Balance update is handled separately."""
        payment = SupplierPayment(
            supplier_id=supplier_id,
            amount=amount,
            payment_mode=payment_mode,
            account_id=account_id,
            reference_no=reference_no,
            note=note,
            paid_at=paid_at,
            created_by=created_by,
        )
        db.add(payment)
        await db.flush()
        await db.refresh(payment)
        return payment

    # ── Filtered list ─────────────────────────────────────────────────────────

    async def list_suppliers(
        self,
        db: AsyncSession,
        *,
        search: str | None = None,
        balance_type: BalanceType | None = None,
        is_active: bool | None = True,
        skip: int = 0,
        limit: int = 20,
        sort_by: Literal["name", "balance", "created_at"] = "name",
        sort_order: Literal["asc", "desc"] = "asc",
    ) -> tuple[list[Supplier], int]:
        conditions = []
        if search:
            conditions.append(Supplier.name.ilike(f"%{search}%"))
        if balance_type is not None:
            conditions.append(Supplier.balance_type == balance_type)
        if is_active is not None:
            conditions.append(Supplier.is_active == is_active)

        stmt = select(Supplier)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "name": Supplier.name,
            "balance": Supplier.balance,
            "created_at": Supplier.created_at,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    # ── Payment history ───────────────────────────────────────────────────────

    async def get_payments(
        self,
        db: AsyncSession,
        supplier_id: int,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[SupplierPayment], int]:
        stmt = (
            select(SupplierPayment)
            .where(SupplierPayment.supplier_id == supplier_id)
            .order_by(desc(SupplierPayment.paid_at))
        )

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    # ── Ledger ────────────────────────────────────────────────────────────────

    async def get_ledger(
        self,
        db: AsyncSession,
        supplier_id: int,
        *,
        opening_balance_signed: Decimal,
        from_date: date | None = None,
        to_date: date | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[tuple], int]:
        """
        Chronological ledger: purchases (credit) + payments (debit).

        Returns raw rows as named tuples; the Service converts them to
        SupplierLedgerEntry objects (including opening balance row and
        balance_type derivation).

        opening_balance_signed is the SIGNED opening value computed by the
        Service using the same convention as _compute_new_balance:
          payable   opening → +opening_balance
          receivable opening → -opening_balance

        Running balance formula:
          row_balance_signed = opening_balance_signed
                               + SUM(credit - debit) OVER (ORDER BY date, id)

        A positive result means payable; negative means receivable.
        The Service converts to (abs, BalanceType) for the API response.

        COUNT is taken on the UNION subquery before the window function to
        avoid materialising the full window result just for counting.

        Lazy import of Purchase avoids circular imports at module load.
        """
        from app.models.purchase import Purchase  # noqa: PLC0415

        # ── Purchase leg — credit (increases payable, so +delta in signed space) ──
        purchase_leg = select(
            Purchase.purchase_date.label("entry_date"),
            Purchase.invoice_no.label("description_raw"),
            literal(Decimal("0")).cast(Purchase.total_amount.type).label("debit"),
            Purchase.total_amount.label("credit"),
            literal("purchase").label("reference_type"),
            Purchase.id.label("reference_id"),
        ).where(Purchase.supplier_id == supplier_id)

        # ── Payment leg — debit (decreases payable, so -delta in signed space) ───
        payment_leg = select(
            func.cast(SupplierPayment.paid_at, Date).label("entry_date"),
            SupplierPayment.reference_no.label("description_raw"),
            SupplierPayment.amount.label("debit"),
            literal(Decimal("0")).cast(SupplierPayment.amount.type).label("credit"),
            literal("payment").label("reference_type"),
            SupplierPayment.id.label("reference_id"),
        ).where(SupplierPayment.supplier_id == supplier_id)

        # ── Optional date filters ─────────────────────────────────────────────
        if from_date is not None:
            purchase_leg = purchase_leg.where(Purchase.purchase_date >= from_date)
            payment_leg = payment_leg.where(
                func.cast(SupplierPayment.paid_at, Date) >= from_date
            )
        if to_date is not None:
            purchase_leg = purchase_leg.where(Purchase.purchase_date <= to_date)
            payment_leg = payment_leg.where(
                func.cast(SupplierPayment.paid_at, Date) <= to_date
            )

        # ── UNION ALL → count BEFORE the window function ──────────────────────
        combined = union_all(purchase_leg, payment_leg).subquery()

        count_result = await db.execute(
            select(func.count()).select_from(combined)
        )
        total: int = count_result.scalar_one()

        # ── Running balance in signed space ───────────────────────────────────
        # credit = purchase amount  → +delta (increases payable)
        # debit  = payment amount   → -delta (decreases payable)
        # SUM(credit - debit) accumulates the signed change from transactions.
        # Adding opening_balance_signed gives the signed running total that
        # perfectly mirrors _compute_new_balance() arithmetic.
        running_balance_signed = (
            func.sum(combined.c.credit - combined.c.debit)
            .over(order_by=[combined.c.entry_date, combined.c.reference_id])
            + opening_balance_signed
        ).label("balance_signed")

        ledger_q = (
            select(
                combined.c.entry_date,
                combined.c.description_raw,
                combined.c.debit,
                combined.c.credit,
                combined.c.reference_type,
                combined.c.reference_id,
                running_balance_signed,
            )
            .order_by(combined.c.entry_date, combined.c.reference_id)
        )

        result = await db.execute(ledger_q.offset(skip).limit(limit))
        return result.all(), total
