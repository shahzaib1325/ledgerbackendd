"""
Business logic for the Customer module.

Domain rules (single source of truth):
─────────────────────────────────────────────────────────────────────────────
BALANCE MODEL
  customer.balance      — non-negative absolute amount (>= 0, always).
  customer.balance_type — direction: BalanceType.receivable | BalanceType.payable.

  Interpretation:
    receivable → customer owes us this amount (default after a sale).
    payable    → we owe the customer (overpayment / credit note).

SALES (called by sale_service via apply_sale_to_balance):
  A new sale increases what the customer owes us.
  → delta = +sale_amount  (increases receivable in signed space)

PAYMENTS (customer pays us):
  A payment reduces what the customer owes us.
  → delta = −payment_amount  (decreases receivable in signed space)

CREDIT LIMIT:
  Before recording a sale, the service checks that the resulting receivable
  balance does not exceed credit_limit (when credit_limit > 0).
  CreditLimitExceededError is raised if the check fails.
  credit_limit = 0 means no limit enforced.

SIGNED CONVENTION (mirrors _compute_new_balance):
  receivable → +balance in signed space
  payable    → −balance in signed space

LEDGER AGREEMENT:
  Ledger is seeded with opening_balance_signed = ±opening_balance.
  The final transaction row's (balance, balance_type) equals
  customer.(balance, balance_type) exactly (no date filter applied).

CONCURRENCY SAFETY:
  1. SELECT FOR UPDATE via repo.get_with_lock().
  2. All arithmetic in _compute_new_balance() — Python, this file only.
  3. repo.apply_balance_update() — pure DB write-back.
  4. repo.save_payment() — inserts payment row + db.flush().

SOFT DELETE:
  is_active=False excludes the customer from all operations.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CreditLimitExceededError, NotFoundException
from app.models.customer import Customer, CustomerPayment
from app.models.enums import AuditAction, BalanceType
from app.repositories.customer_repo import CustomerRepository
from app.services import audit_service
from app.schemas.customer import (
    CustomerBalanceSummary,
    CustomerCreate,
    CustomerLedgerEntry,
    CustomerPaymentCreate,
    CustomerUpdate,
)

_repo = CustomerRepository()


# ── Domain helpers ────────────────────────────────────────────────────────────

def _compute_new_balance(
    current_balance: Decimal,
    current_type: BalanceType,
    *,
    delta: Decimal,
) -> tuple[Decimal, BalanceType]:
    """
    Apply a signed delta to (balance, balance_type).

    Signed space: receivable = +balance, payable = −balance.
    Positive result → receivable; negative → payable.
    Returns (abs_value, BalanceType).
    """
    signed = current_balance if current_type == BalanceType.receivable else -current_balance
    new_signed = signed + delta
    if new_signed >= Decimal("0"):
        return new_signed, BalanceType.receivable
    return -new_signed, BalanceType.payable


def _active_or_404(customer: Customer | None, customer_id: int) -> Customer:
    if customer is None or not customer.is_active:
        raise NotFoundException(f"Customer {customer_id} not found.")
    return customer


def _signed_to_abs_type(signed: Decimal) -> tuple[Decimal, BalanceType]:
    if signed >= Decimal("0"):
        return signed, BalanceType.receivable
    return -signed, BalanceType.payable


# ── Create ────────────────────────────────────────────────────────────────────

async def create_customer(
    db: AsyncSession,
    body: CustomerCreate,
    *,
    created_by: int,
) -> Customer:
    """
    Create a new customer.

    opening_balance seeds both opening_balance and balance cache.
    balance_type defaults to receivable (customer owes us).
    """
    customer = await _repo.create(
        db,
        {
            "name": body.name,
            "phone": body.phone,
            "email": str(body.email) if body.email else None,
            "address": body.address,
            "credit_limit": body.credit_limit,
            "opening_balance": body.opening_balance,
            "balance": body.opening_balance,
            "balance_type": body.balance_type,
            "is_active": body.is_active,
            "notes": body.notes,
            "created_by": created_by,
        },
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="customers", record_id=customer.id,
        new_values=audit_service.snapshot(customer),
    )
    return customer


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_customer(db: AsyncSession, customer_id: int) -> Customer:
    customer = await _repo.get_or_404(db, customer_id)
    return _active_or_404(customer, customer_id)


async def list_customers(
    db: AsyncSession,
    *,
    search: str | None = None,
    balance_type: BalanceType | None = None,
    is_active: bool | None = True,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> tuple[list[Customer], int]:
    skip = (page - 1) * limit
    return await _repo.list_customers(
        db,
        search=search,
        balance_type=balance_type,
        is_active=is_active,
        skip=skip,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


# ── Update ────────────────────────────────────────────────────────────────────

async def update_customer(
    db: AsyncSession,
    customer_id: int,
    body: CustomerUpdate,
    *,
    updated_by: int,
) -> Customer:
    customer = await _repo.get_or_404(db, customer_id)
    _active_or_404(customer, customer_id)
    old = audit_service.snapshot(customer)

    patch = body.model_dump(exclude_unset=True)
    if "email" in patch and patch["email"] is not None:
        patch["email"] = str(patch["email"])

    updated = await _repo.update(db, customer, patch)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="customers", record_id=customer_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return updated


# ── Delete (soft) ─────────────────────────────────────────────────────────────

async def delete_customer(db: AsyncSession, customer_id: int, *, deleted_by: int) -> None:
    customer = await _repo.get_or_404(db, customer_id)
    _active_or_404(customer, customer_id)
    old = audit_service.snapshot(customer)
    customer.is_active = False
    db.add(customer)
    await db.flush()
    await audit_service.log(
        db, user_id=deleted_by, action=AuditAction.DELETE,
        table_name="customers", record_id=customer_id,
        old_values=old,
    )


# ── Payments ──────────────────────────────────────────────────────────────────

async def record_payment(
    db: AsyncSession,
    customer_id: int,
    body: CustomerPaymentCreate,
    *,
    created_by: int,
) -> CustomerPayment:
    """
    Record a payment from a customer (reduces receivable balance).

    Sequence (concurrency-safe):
      1. SELECT FOR UPDATE — lock customer row.
      2. Compute new balance via _compute_new_balance (delta = −amount).
      3. Write balance back via apply_balance_update.
      4. Insert CustomerPayment row via save_payment (+ db.flush inside).
    """
    customer = await _repo.get_with_lock(db, customer_id)
    _active_or_404(customer, customer_id)

    new_balance, new_balance_type = _compute_new_balance(
        customer.balance,
        customer.balance_type,
        delta=-body.amount,     # payment reduces receivable
    )

    await _repo.apply_balance_update(
        db, customer,
        new_balance=new_balance,
        new_balance_type=new_balance_type,
    )

    received_at = body.received_at or datetime.now(timezone.utc)
    payment = await _repo.save_payment(
        db,
        customer_id=customer_id,
        amount=body.amount,
        payment_mode=body.payment_mode,
        account_id=body.account_id,
        reference_no=body.reference_no,
        note=body.note,
        received_at=received_at,
        created_by=created_by,
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="customer_payments", record_id=payment.id,
        new_values=audit_service.snapshot(payment),
    )
    return payment


async def list_payments(
    db: AsyncSession,
    customer_id: int,
    *,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[CustomerPayment], int]:
    customer = await _repo.get_or_404(db, customer_id)
    _active_or_404(customer, customer_id)
    skip = (page - 1) * limit
    return await _repo.get_payments(db, customer_id, skip=skip, limit=limit)


# ── Sale balance update (called by sale_service) ──────────────────────────────

async def apply_sale_to_balance(
    db: AsyncSession,
    customer_id: int,
    *,
    sale_amount: Decimal,
) -> None:
    """
    Called by sale_service after a new sale invoice is created.

    Increases the receivable balance. Enforces credit_limit when set.
    sale_service must already be inside an open transaction.
    """
    customer = await _repo.get_with_lock(db, customer_id)
    _active_or_404(customer, customer_id)

    new_balance, new_balance_type = _compute_new_balance(
        customer.balance,
        customer.balance_type,
        delta=+sale_amount,     # sale increases receivable
    )

    # Enforce credit limit (0 means unlimited)
    if (
        customer.credit_limit > Decimal("0")
        and new_balance_type == BalanceType.receivable
        and new_balance > customer.credit_limit
    ):
        raise CreditLimitExceededError(
            f"Sale would bring balance to {new_balance}, exceeding "
            f"credit limit of {customer.credit_limit}."
        )

    await _repo.apply_balance_update(
        db, customer,
        new_balance=new_balance,
        new_balance_type=new_balance_type,
    )
    await db.flush()


# ── Ledger ────────────────────────────────────────────────────────────────────

async def get_ledger(
    db: AsyncSession,
    customer_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[CustomerLedgerEntry], int]:
    """
    Return the complete financial ledger for a customer.

    Row 0 — synthetic "Opening Balance" entry (page 1 only).
    Row 1..N — chronological sales (debit) and payments (credit).

    AR ledger convention: Sales are Debits (increase receivable asset),
    Payments are Credits (decrease receivable asset).
    Signed convention: receivable = +, payable = −.
    Each row's balance_signed is converted to (abs, BalanceType) here.
    """
    customer = await _repo.get_or_404(db, customer_id)
    _active_or_404(customer, customer_id)

    # Signed opening: receivable → +, payable → −
    opening_signed = (
        customer.opening_balance
        if customer.balance_type == BalanceType.receivable
        else -customer.opening_balance
    )

    skip = (page - 1) * limit
    rows, total = await _repo.get_ledger(
        db,
        customer_id,
        opening_balance_signed=opening_signed,
        from_date=from_date,
        to_date=to_date,
        skip=skip,
        limit=limit,
    )

    entries: list[CustomerLedgerEntry] = []

    if skip == 0:
        entries.append(
            CustomerLedgerEntry(
                date=customer.created_at.date(),
                description="Opening Balance",
                debit=Decimal("0"),
                credit=Decimal("0"),
                balance=customer.opening_balance,
                balance_type=customer.balance_type,
                reference_type="opening",
                reference_id=0,
            )
        )

    for row in rows:
        abs_bal, bal_type = _signed_to_abs_type(Decimal(str(row.balance_signed)))
        entries.append(
            CustomerLedgerEntry(
                date=row.entry_date,
                description=row.description_raw or (
                    "Sale Invoice" if row.reference_type == "sale" else "Payment"
                ),
                debit=row.debit,
                credit=row.credit,
                balance=abs_bal,
                balance_type=bal_type,
                reference_type=row.reference_type,
                reference_id=row.reference_id,
            )
        )

    return entries, total


# ── Balance summary ───────────────────────────────────────────────────────────

async def get_balance_summary(
    db: AsyncSession,
    customer_id: int,
) -> CustomerBalanceSummary:
    customer = await _repo.get_or_404(db, customer_id)
    _active_or_404(customer, customer_id)
    return CustomerBalanceSummary(
        id=customer.id,
        name=customer.name,
        balance=customer.balance,
        balance_type=customer.balance_type,
        credit_limit=customer.credit_limit,
    )
