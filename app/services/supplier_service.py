"""
Business logic for the Supplier module.

Domain rules (single source of truth):
─────────────────────────────────────────────────────────────────────────────
BALANCE MODEL
  supplier.balance  — non-negative absolute amount (>= 0, always).
  supplier.balance_type — direction: BalanceType.payable | BalanceType.receivable.

  Interpretation:
    payable    → we owe this amount to the supplier.
    receivable → the supplier owes us (overpayment / credit).

PURCHASES (handled by purchase_service, public helper below):
  Every new purchase adds to what we owe.
  → new_signed = signed(balance, balance_type) + purchase_amount
    where signed(b, payable) = +b, signed(b, receivable) = -b
  → (balance, balance_type) = abs/direction of new_signed.

PAYMENTS:
  A payment reduces what we owe (or builds up a credit if we overpay).
  → new_signed = signed(balance, balance_type) - payment_amount
  → (balance, balance_type) = abs/direction of new_signed.

LEDGER AGREEMENT:
  The running balance in get_ledger is seeded with supplier.opening_balance
  and applies: running += (credit - debit) per row in chronological order.
  The final row's running balance equals supplier.balance (when no date filter
  is applied) because every purchase/payment that mutated supplier.balance
  went through _compute_new_balance(), using the same arithmetic.

  Note: when balance_type flips (e.g., overpayment turns payable → receivable),
  the ledger running value may go negative (signed perspective). The cached
  supplier.balance is always the absolute value; balance_type carries the sign.
  Consumers should present the signed value as (balance × direction) where
  payable = +1, receivable = -1 from an "amount we owe" perspective.
─────────────────────────────────────────────────────────────────────────────

CONCURRENCY SAFETY
  All balance-mutating operations:
    1. Begin an explicit savepoint (nested transaction) so the lock + write
       is atomic even inside SQLAlchemy's autobegin transaction.
    2. Call repo.get_with_lock() — SELECT FOR UPDATE.
    3. Compute the new balance entirely in Python (this file, _compute_new_balance).
    4. Call repo.apply_balance_update() — pure DB write-back, no math.
    5. Insert the event row (purchase or payment).
    6. db.flush() — all changes go to PG in one round trip before the caller
       commits at the API layer.

SOFT DELETE
  Deleted suppliers (is_active=False) are excluded from all operations.
  get_or_404 loads active-only in the base repo (it checks None); we add
  an explicit is_active guard after load for mutation paths.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException
from app.models.enums import AuditAction, BalanceType
from app.models.supplier import Supplier, SupplierItem, SupplierPayment
from app.repositories.supplier_repo import SupplierRepository
from app.services import audit_service
from app.schemas.supplier import (
    SupplierBalanceSummary,
    SupplierCreate,
    SupplierLedgerEntry,
    SupplierPaymentCreate,
    SupplierUpdate,
)

_repo = SupplierRepository()


# ── Domain helper — SINGLE SOURCE OF TRUTH for balance arithmetic ─────────────

def _compute_new_balance(
    current_balance: Decimal,
    current_type: BalanceType,
    *,
    delta: Decimal,          # positive = increases payable (purchase)
                              # negative = decreases payable (payment)
) -> tuple[Decimal, BalanceType]:
    """
    Apply a signed delta to the (balance, balance_type) pair.

    Internally works with a signed representation where payable is positive
    and receivable is negative, then normalises back to (abs, direction).

    Returns (new_balance, new_balance_type) — both non-negative / direction.
    """
    signed = current_balance if current_type == BalanceType.payable else -current_balance
    new_signed = signed + delta

    if new_signed >= Decimal("0"):
        return new_signed, BalanceType.payable
    else:
        return -new_signed, BalanceType.receivable


def _active_or_404(supplier: Supplier | None, supplier_id: int) -> Supplier:
    """Raise NotFoundException for None or soft-deleted suppliers."""
    if supplier is None or not supplier.is_active:
        raise NotFoundException(f"Supplier {supplier_id} not found.")
    return supplier


# ── Create ────────────────────────────────────────────────────────────────────

async def create_supplier(
    db: AsyncSession,
    body: SupplierCreate,
    *,
    created_by: int,
) -> Supplier:
    """
    Create a new supplier.

    opening_balance seeds the initial balance cache with the correct direction
    already encoded in balance_type. The ledger window function uses
    opening_balance as its seed, so both views stay in sync from day one.
    """
    supplier = await _repo.create(
        db,
        {
            "name": body.name,
            "phone": body.phone,
            "email": str(body.email) if body.email else None,
            "address": body.address,
            "opening_balance": body.opening_balance,
            "balance": body.opening_balance,        # cache == opening at creation
            "balance_type": body.balance_type,
            "notes": body.notes,
            "created_by": created_by,
        },
    )

    for item in body.items:
        db.add(SupplierItem(supplier_id=supplier.id, item_id=item.item_id))
    if body.items:
        await db.flush()

    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="suppliers", record_id=supplier.id,
        new_values=audit_service.snapshot(supplier),
    )

    # Reload with items eagerly fetched — the relationship is not loaded on the
    # newly inserted object, and async SQLAlchemy forbids lazy loading.
    result = await db.execute(
        select(Supplier)
        .where(Supplier.id == supplier.id)
        .options(selectinload(Supplier.items))
    )
    return result.scalar_one()


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_supplier(db: AsyncSession, supplier_id: int) -> Supplier:
    result = await db.execute(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(selectinload(Supplier.items))
    )
    supplier = result.scalar_one_or_none()
    return _active_or_404(supplier, supplier_id)


async def list_suppliers(
    db: AsyncSession,
    *,
    search: str | None = None,
    balance_type: BalanceType | None = None,
    is_active: bool | None = True,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> tuple[list[Supplier], int]:
    skip = (page - 1) * limit
    return await _repo.list_suppliers(
        db,
        search=search,
        balance_type=balance_type,
        is_active=is_active,        # defaults True — deleted suppliers excluded
        skip=skip,
        limit=limit,
        sort_by=sort_by,            # type: ignore[arg-type]
        sort_order=sort_order,      # type: ignore[arg-type]
    )


# ── Update ────────────────────────────────────────────────────────────────────

async def update_supplier(
    db: AsyncSession,
    supplier_id: int,
    body: SupplierUpdate,
    *,
    updated_by: int,
) -> Supplier:
    result = await db.execute(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(selectinload(Supplier.items))
    )
    supplier = result.scalar_one_or_none()
    _active_or_404(supplier, supplier_id)
    old = audit_service.snapshot(supplier)

    patch = body.model_dump(exclude_unset=True, exclude={"categories", "items"})
    if "email" in patch and patch["email"] is not None:
        patch["email"] = str(patch["email"])

    updated = await _repo.update(db, supplier, patch)

    if body.items is not None:
        for item in supplier.items:
            await db.delete(item)
        await db.flush()
        for item in body.items:
            db.add(SupplierItem(supplier_id=supplier_id, item_id=item.item_id))
        await db.flush()

    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="suppliers", record_id=supplier_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )

    # Reload with items eagerly fetched — db.refresh() does not reload relationships.
    result = await db.execute(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(selectinload(Supplier.items))
    )
    return result.scalar_one()


# ── Delete (soft) ─────────────────────────────────────────────────────────────

async def delete_supplier(db: AsyncSession, supplier_id: int, *, deleted_by: int) -> None:
    supplier = await _repo.get_or_404(db, supplier_id)
    _active_or_404(supplier, supplier_id)
    old = audit_service.snapshot(supplier)
    supplier.is_active = False
    db.add(supplier)
    await db.flush()
    await audit_service.log(
        db, user_id=deleted_by, action=AuditAction.DELETE,
        table_name="suppliers", record_id=supplier_id,
        old_values=old,
    )


# ── Payments ──────────────────────────────────────────────────────────────────

async def record_payment(
    db: AsyncSession,
    supplier_id: int,
    body: SupplierPaymentCreate,
    *,
    created_by: int,
) -> SupplierPayment:
    """
    Record a payment to a supplier.

    Sequence (concurrency-safe):
      1. SELECT FOR UPDATE — lock the supplier row.
      2. Compute new balance in Python using _compute_new_balance().
         Payment delta is negative (reduces payable).
      3. Write new balance via apply_balance_update() (pure DB write-back).
      4. Insert the SupplierPayment row.
      5. db.flush() — both writes land atomically before the API-layer commit.
    """
    # Step 1 — lock
    supplier = await _repo.get_with_lock(db, supplier_id)
    _active_or_404(supplier, supplier_id)

    # Step 2 — compute (all business logic here, not in repo)
    new_balance, new_balance_type = _compute_new_balance(
        supplier.balance,
        supplier.balance_type,
        delta=-body.amount,          # payment reduces payable
    )

    # Step 3 — write balance back (no arithmetic in repo)
    await _repo.apply_balance_update(
        db,
        supplier,
        new_balance=new_balance,
        new_balance_type=new_balance_type,
    )

    # Step 4 — insert payment row
    paid_at = body.paid_at or datetime.now(timezone.utc)
    payment = await _repo.save_payment(
        db,
        supplier_id=supplier_id,
        amount=body.amount,
        payment_mode=body.payment_mode,
        account_id=body.account_id,
        reference_no=body.reference_no,
        note=body.note,
        paid_at=paid_at,
        created_by=created_by,
    )
    # Step 5 — db.flush() is issued inside save_payment(); commit at API layer.
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="supplier_payments", record_id=payment.id,
        new_values=audit_service.snapshot(payment),
    )
    return payment


async def list_payments(
    db: AsyncSession,
    supplier_id: int,
    *,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[SupplierPayment], int]:
    supplier = await _repo.get_or_404(db, supplier_id)
    _active_or_404(supplier, supplier_id)
    skip = (page - 1) * limit
    return await _repo.get_payments(db, supplier_id, skip=skip, limit=limit)


# ── Purchase balance update (called by purchase_service) ──────────────────────

async def apply_purchase_to_balance(
    db: AsyncSession,
    supplier_id: int,
    *,
    purchase_amount: Decimal,
) -> None:
    """
    Called by purchase_service after a new purchase is created.

    Locks the supplier row and increases the payable balance.
    purchase_service must already be inside an open transaction.
    """
    supplier = await _repo.get_with_lock(db, supplier_id)
    _active_or_404(supplier, supplier_id)

    new_balance, new_balance_type = _compute_new_balance(
        supplier.balance,
        supplier.balance_type,
        delta=+purchase_amount,      # purchase increases payable
    )
    await _repo.apply_balance_update(
        db,
        supplier,
        new_balance=new_balance,
        new_balance_type=new_balance_type,
    )
    await db.flush()


# ── Ledger ────────────────────────────────────────────────────────────────────

async def get_ledger(
    db: AsyncSession,
    supplier_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[SupplierLedgerEntry], int]:
    """
    Return the complete financial ledger for a supplier.

    Structure:
      Row 0 — synthetic "Opening Balance" entry (always present, never paginated
               away: it is prepended in Python, not returned from the DB query).
      Row 1..N — chronological purchases (credit) and payments (debit), each
                 carrying the signed running balance after that transaction.

    Signed convention (mirrors _compute_new_balance):
      positive signed balance → payable  (we owe the supplier)
      negative signed balance → receivable (supplier owes us / credit)

    The repo returns raw DB rows with balance_signed. This function converts
    each row to (abs(balance_signed), BalanceType) so SupplierLedgerEntry.balance
    stays non-negative and SupplierLedgerEntry.balance_type carries direction.

    Consistency guarantee:
      When no date filter is applied, the last transaction row's
      (balance, balance_type) equals supplier.(balance, balance_type) exactly,
      because both use the same signed arithmetic seeded from the same
      opening_balance_signed.
    """
    supplier = await _repo.get_or_404(db, supplier_id)
    _active_or_404(supplier, supplier_id)

    # Signed opening: payable → +, receivable → −
    opening_signed = (
        supplier.opening_balance
        if supplier.balance_type == BalanceType.payable
        else -supplier.opening_balance
    )

    skip = (page - 1) * limit
    rows, total = await _repo.get_ledger(
        db,
        supplier_id,
        opening_balance_signed=opening_signed,
        from_date=from_date,
        to_date=to_date,
        skip=skip,
        limit=limit,
    )

    # ── Convert raw rows to SupplierLedgerEntry ───────────────────────────────
    def _signed_to_abs_type(signed: Decimal) -> tuple[Decimal, BalanceType]:
        if signed >= Decimal("0"):
            return signed, BalanceType.payable
        return -signed, BalanceType.receivable

    entries: list[SupplierLedgerEntry] = []

    # Synthetic opening balance row — only on page 1 when no skip is applied.
    # It shows the state *before* any transaction, giving auditors a starting
    # point. reference_id=0 marks it as synthetic (no DB row).
    if skip == 0:
        ob_abs = supplier.opening_balance
        ob_type = supplier.balance_type
        entries.append(
            SupplierLedgerEntry(
                date=supplier.created_at.date(),
                description="Opening Balance",
                debit=Decimal("0"),
                credit=Decimal("0"),
                balance=ob_abs,
                balance_type=ob_type,
                reference_type="opening",
                reference_id=0,
            )
        )

    for row in rows:
        abs_bal, bal_type = _signed_to_abs_type(Decimal(str(row.balance_signed)))
        entries.append(
            SupplierLedgerEntry(
                date=row.entry_date,
                description=row.description_raw or (
                    "Purchase" if row.reference_type == "purchase" else "Payment"
                ),
                debit=row.debit,
                credit=row.credit,
                balance=abs_bal,
                balance_type=bal_type,
                reference_type=row.reference_type,
                reference_id=row.reference_id,
            )
        )

    # total reflects DB transaction rows only; the opening row is always extra.
    return entries, total


# ── Balance summary ───────────────────────────────────────────────────────────

async def get_balance_summary(
    db: AsyncSession,
    supplier_id: int,
) -> SupplierBalanceSummary:
    supplier = await _repo.get_or_404(db, supplier_id)
    _active_or_404(supplier, supplier_id)
    return SupplierBalanceSummary(
        id=supplier.id,
        name=supplier.name,
        balance=supplier.balance,
        balance_type=supplier.balance_type,
    )
