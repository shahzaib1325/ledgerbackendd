"""
Repository for the Customer module.

Responsibility: data access ONLY.
- No balance arithmetic or business rules here.
- Balance mutations: Service computes new values, passes them to
  apply_balance_update(). Repository only writes to DB.
- SELECT FOR UPDATE provided via get_with_lock(); callers must be inside
  an active transaction.

Specialised queries:
  get_with_lock        — SELECT FOR UPDATE (balance mutations)
  apply_balance_update — write pre-computed balance back to the locked row
  save_payment         — insert CustomerPayment row only (no balance math)
  list_customers       — filtered, sorted, paginated
  get_payments         — payment history (paginated)
  get_ledger           — sales + payments UNION with signed running balance
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import Date, and_, asc, desc, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer, CustomerPayment
from app.models.enums import BalanceType
from app.repositories.base_repo import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    # ── Locking ───────────────────────────────────────────────────────────────

    async def get_with_lock(self, db: AsyncSession, customer_id: int) -> Customer | None:
        """SELECT FOR UPDATE — must be called inside an open transaction."""
        result = await db.execute(
            select(Customer)
            .where(Customer.id == customer_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    # ── Balance write-back (pure DB, no math) ─────────────────────────────────

    async def apply_balance_update(
        self,
        db: AsyncSession,
        customer: Customer,
        *,
        new_balance: Decimal,
        new_balance_type: BalanceType,
    ) -> None:
        """Persist pre-computed balance fields. Service owns all arithmetic."""
        customer.balance = new_balance
        customer.balance_type = new_balance_type
        db.add(customer)

    # ── Payment row insertion (no balance side-effects) ───────────────────────

    async def save_payment(
        self,
        db: AsyncSession,
        *,
        customer_id: int,
        amount: Decimal,
        payment_mode,
        account_id: int | None,
        reference_no: str | None,
        note: str | None,
        received_at: datetime,
        created_by: int | None,
    ) -> CustomerPayment:
        """Insert the CustomerPayment row. Balance update is handled separately."""
        payment = CustomerPayment(
            customer_id=customer_id,
            amount=amount,
            payment_mode=payment_mode,
            account_id=account_id,
            reference_no=reference_no,
            note=note,
            received_at=received_at,
            created_by=created_by,
        )
        db.add(payment)
        await db.flush()
        await db.refresh(payment)
        return payment

    # ── Filtered list ─────────────────────────────────────────────────────────

    async def list_customers(
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
    ) -> tuple[list[Customer], int]:
        conditions = []
        if search:
            conditions.append(Customer.name.ilike(f"%{search}%"))
        if balance_type is not None:
            conditions.append(Customer.balance_type == balance_type)
        if is_active is not None:
            conditions.append(Customer.is_active == is_active)

        stmt = select(Customer)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "name": Customer.name,
            "balance": Customer.balance,
            "created_at": Customer.created_at,
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
        customer_id: int,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[CustomerPayment], int]:
        stmt = (
            select(CustomerPayment)
            .where(CustomerPayment.customer_id == customer_id)
            .order_by(desc(CustomerPayment.received_at))
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
        customer_id: int,
        *,
        opening_balance_signed: Decimal,
        from_date: date | None = None,
        to_date: date | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[tuple], int]:
        """
        Chronological ledger: sale invoices + payments.

        Accounting convention (AR ledger — asset perspective):
          Sale    → Debit  (debits increase the Accounts Receivable asset)
          Payment → Credit (credits decrease the Accounts Receivable asset)

        Running balance formula:
          balance_signed = opening_balance_signed + SUM(debit − credit) OVER (...)

        Signed convention (matches _compute_new_balance in the service):
          positive → receivable (customer owes us)
          negative → payable   (we owe the customer — overpayment / credit)

        Returns raw named-tuple rows with balance_signed. The Service converts
        them to CustomerLedgerEntry objects (adds opening row, abs/direction).

        COUNT is on the raw UNION subquery (before window function).
        Lazy import of SaleInvoice avoids circular imports at module load.
        """
        from app.models.sale import SaleInvoice  # noqa: PLC0415

        # ── Sale leg — Debit (increases AR asset, +delta in signed space) ────
        sale_leg = select(
            SaleInvoice.invoice_date.label("entry_date"),
            SaleInvoice.invoice_no.label("description_raw"),
            SaleInvoice.total_amount.label("debit"),
            literal(Decimal("0")).cast(SaleInvoice.total_amount.type).label("credit"),
            literal("sale").label("reference_type"),
            SaleInvoice.id.label("reference_id"),
        ).where(SaleInvoice.customer_id == customer_id)

        # ── Payment leg — Credit (decreases AR asset, −delta in signed space) ─
        payment_leg = select(
            func.cast(CustomerPayment.received_at, Date).label("entry_date"),
            CustomerPayment.reference_no.label("description_raw"),
            literal(Decimal("0")).cast(CustomerPayment.amount.type).label("debit"),
            CustomerPayment.amount.label("credit"),
            literal("payment").label("reference_type"),
            CustomerPayment.id.label("reference_id"),
        ).where(CustomerPayment.customer_id == customer_id)

        # ── Optional date filters ─────────────────────────────────────────────
        if from_date is not None:
            sale_leg = sale_leg.where(SaleInvoice.invoice_date >= from_date)
            payment_leg = payment_leg.where(
                func.cast(CustomerPayment.received_at, Date) >= from_date
            )
        if to_date is not None:
            sale_leg = sale_leg.where(SaleInvoice.invoice_date <= to_date)
            payment_leg = payment_leg.where(
                func.cast(CustomerPayment.received_at, Date) <= to_date
            )

        # ── UNION ALL → count BEFORE window function ──────────────────────────
        combined = union_all(sale_leg, payment_leg).subquery()

        count_result = await db.execute(
            select(func.count()).select_from(combined)
        )
        total: int = count_result.scalar_one()

        # ── Signed running balance ────────────────────────────────────────────
        # debit - credit: sales (+) increase receivable, payments (-) decrease it.
        running_balance_signed = (
            func.sum(combined.c.debit - combined.c.credit)
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
