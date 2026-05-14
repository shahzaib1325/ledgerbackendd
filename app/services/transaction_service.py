"""
Business logic for the Transactions / Accounts module.

Domain rules:
─────────────────────────────────────────────────────────────────────────────
ACCOUNTS:
  - Each account (cash / bank / digital) has a current_balance that is always
    kept in sync with recorded transactions.
  - opening_balance seeds current_balance at creation.
  - Soft-delete (is_active=False) prevents further transactions.

TRANSACTIONS:
  - Immutable once written. No update / delete endpoints.
  - Every mutation to an account balance creates a Transaction row.
  - balance_after is computed here (not in DB) to avoid a round-trip.
  - transaction_date defaults to today when not supplied.

TRANSFERS:
  - Atomic debit from source account + credit to destination account.
  - Writes two Transaction rows (one per account) and one Transfer row.
  - Source and destination must be different active accounts.
  - Source balance must be sufficient (no overdraft).

INTERNAL HOOK (used by other services):
  - record_account_transaction() — called by purchase/sale/salary services
    when a payment is tied to a specific account.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.enums import AuditAction, AccountType, ReferenceType, TransactionType
from app.models.transaction import Account, Transaction, Transfer
from app.services import audit_service
from app.repositories.transaction_repo import (
    AccountRepository,
    TransactionRepository,
    TransferRepository,
)
from app.schemas.transaction import (
    AccountCreate,
    AccountUpdate,
    TransferCreate,
)

_account_repo = AccountRepository()
_txn_repo = TransactionRepository()
_transfer_repo = TransferRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _active_account_or_404(account: Account | None, account_id: int) -> Account:
    if account is None or not account.is_active:
        raise NotFoundException(f"Account {account_id} not found.")
    return account


async def _debit_account(
    db: AsyncSession,
    account: Account,
    *,
    amount: Decimal,
    reference_type: ReferenceType,
    reference_id: int | None,
    description: str,
    transaction_date: date,
    created_by: int,
) -> Transaction:
    """Reduce account balance and record a debit transaction."""
    if account.current_balance < amount:
        raise ValidationException(
            f"Insufficient balance. Available: {account.current_balance}, required: {amount}.",
            field="amount",
        )
    await _account_repo.apply_balance_delta(db, account, delta=-amount)
    return await _txn_repo.record(
        db,
        account_id=account.id,
        transaction_type=TransactionType.debit,
        reference_type=reference_type,
        reference_id=reference_id,
        amount=amount,
        balance_after=account.current_balance,
        description=description,
        transaction_date=transaction_date,
        created_by=created_by,
    )


async def _credit_account(
    db: AsyncSession,
    account: Account,
    *,
    amount: Decimal,
    reference_type: ReferenceType,
    reference_id: int | None,
    description: str,
    transaction_date: date,
    created_by: int,
) -> Transaction:
    """Increase account balance and record a credit transaction."""
    await _account_repo.apply_balance_delta(db, account, delta=+amount)
    return await _txn_repo.record(
        db,
        account_id=account.id,
        transaction_type=TransactionType.credit,
        reference_type=reference_type,
        reference_id=reference_id,
        amount=amount,
        balance_after=account.current_balance,
        description=description,
        transaction_date=transaction_date,
        created_by=created_by,
    )


# ── Accounts — CRUD ───────────────────────────────────────────────────────────

async def create_account(
    db: AsyncSession,
    body: AccountCreate,
    *,
    created_by: int,
) -> Account:
    existing = await _account_repo.get_by_name(db, body.name)
    if existing and existing.is_active:
        raise ValidationException(
            f"An active account named '{body.name}' already exists.",
            field="name",
        )

    account = await _account_repo.create(
        db,
        {
            "name": body.name,
            "account_type": body.account_type,
            "account_no": body.account_no,
            "bank_name": body.bank_name,
            "opening_balance": body.opening_balance,
            "current_balance": body.opening_balance,
            "created_by": created_by,
        },
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="accounts", record_id=account.id,
        new_values=audit_service.snapshot(account),
    )
    return account


async def get_account(db: AsyncSession, account_id: int) -> Account:
    account = await _account_repo.get_or_404(db, account_id)
    return _active_account_or_404(account, account_id)


async def list_accounts(
    db: AsyncSession,
    *,
    account_type: AccountType | None = None,
    is_active: bool | None = True,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> tuple[list[Account], int]:
    return await _account_repo.list_accounts(
        db,
        account_type=account_type,
        is_active=is_active,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


async def update_account(
    db: AsyncSession, account_id: int, body: AccountUpdate, *, updated_by: int
) -> Account:
    account = await _account_repo.get_or_404(db, account_id)
    _active_account_or_404(account, account_id)
    old = audit_service.snapshot(account)
    patch = body.model_dump(exclude_unset=True)
    updated = await _account_repo.update(db, account, patch)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="accounts", record_id=account_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return updated


async def deactivate_account(db: AsyncSession, account_id: int, *, deactivated_by: int) -> None:
    account = await _account_repo.get_or_404(db, account_id)
    _active_account_or_404(account, account_id)
    if account.current_balance != Decimal("0"):
        raise ValidationException(
            "Cannot deactivate an account with a non-zero balance. "
            "Transfer remaining funds first.",
        )
    old = audit_service.snapshot(account)
    updated = await _account_repo.update(db, account, {"is_active": False})
    await audit_service.log(
        db, user_id=deactivated_by, action=AuditAction.UPDATE,
        table_name="accounts", record_id=account_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )


# ── Transactions — read only ───────────────────────────────────────────────────

async def list_transactions(
    db: AsyncSession,
    account_id: int,
    *,
    from_date=None,
    to_date=None,
    transaction_type=None,
    page: int = 1,
    limit: int = 50,
    sort_by: str = "transaction_date",
    sort_order: str = "desc",
) -> tuple[list[Transaction], int]:
    account = await _account_repo.get_or_404(db, account_id)
    _active_account_or_404(account, account_id)
    return await _txn_repo.list_for_account(
        db,
        account_id,
        from_date=from_date,
        to_date=to_date,
        transaction_type=transaction_type,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


# ── Transfers ─────────────────────────────────────────────────────────────────

async def create_transfer(
    db: AsyncSession,
    body: TransferCreate,
    *,
    created_by: int,
) -> Transfer:
    """
    Move funds from one account to another atomically.
    Writes two Transaction rows (debit + credit) and one Transfer row.
    """
    from_account = await _account_repo.get_with_lock(db, body.from_account_id)
    _active_account_or_404(from_account, body.from_account_id)

    to_account = await _account_repo.get_with_lock(db, body.to_account_id)
    _active_account_or_404(to_account, body.to_account_id)

    today = date.today()
    now = datetime.now(timezone.utc)

    transfer = await _transfer_repo.create(
        db,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount=body.amount,
        reference_no=body.reference_no,
        note=body.note,
        transferred_at=now,
        created_by=created_by,
    )

    await _debit_account(
        db, from_account,
        amount=body.amount,
        reference_type=ReferenceType.transfer,
        reference_id=transfer.id,
        description=f"Transfer to {to_account.name}",
        transaction_date=today,
        created_by=created_by,
    )

    await _credit_account(
        db, to_account,
        amount=body.amount,
        reference_type=ReferenceType.transfer,
        reference_id=transfer.id,
        description=f"Transfer from {from_account.name}",
        transaction_date=today,
        created_by=created_by,
    )

    await db.flush()
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="transfers", record_id=transfer.id,
        new_values=audit_service.snapshot(transfer),
    )
    return transfer


async def list_transfers(
    db: AsyncSession,
    *,
    account_id: int | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[Transfer], int]:
    skip = (page - 1) * limit
    if account_id is not None:
        account = await _account_repo.get_or_404(db, account_id)
        _active_account_or_404(account, account_id)
        return await _transfer_repo.list_for_account(db, account_id, skip=skip, limit=limit)
    return await _transfer_repo.list_all(db, skip=skip, limit=limit)


# ── Internal hooks (called by purchase / sale / payroll / production services) ─

async def record_account_transaction(
    db: AsyncSession,
    *,
    account_id: int,
    transaction_type: TransactionType,
    reference_type: ReferenceType,
    reference_id: int | None,
    amount: Decimal,
    description: str,
    transaction_date: date | None = None,
    created_by: int,
) -> Transaction:
    """
    Post a transaction against a real Account (maintains running balance).
    Uses SELECT FOR UPDATE to prevent concurrent balance races.
    """
    account = await _account_repo.get_with_lock(db, account_id)
    if account is None or not account.is_active:
        raise NotFoundException(f"Account {account_id} not found.")

    txn_date = transaction_date or date.today()

    if transaction_type == TransactionType.debit:
        return await _debit_account(
            db, account,
            amount=amount,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            transaction_date=txn_date,
            created_by=created_by,
        )
    return await _credit_account(
        db, account,
        amount=amount,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        transaction_date=txn_date,
        created_by=created_by,
    )


async def record_reference_transaction(
    db: AsyncSession,
    *,
    payment_method: str,
    transaction_type: TransactionType,
    reference_type: ReferenceType,
    reference_id: int | None,
    amount: Decimal,
    description: str,
    transaction_date: date | None = None,
    created_by: int,
) -> Transaction:
    """
    Post a reference-only transaction (no real Account FK, no balance update).
    Used for sale/purchase/production events where payment method is a label
    (cash | bank | digital) rather than a tracked account record.
    """
    return await _txn_repo.record(
        db,
        account_id=None,
        payment_method=payment_method,
        transaction_type=transaction_type,
        reference_type=reference_type,
        reference_id=reference_id,
        amount=amount,
        balance_after=None,
        description=description,
        transaction_date=transaction_date or date.today(),
        created_by=created_by,
    )


async def list_all_transactions(
    db: AsyncSession,
    *,
    reference_type: ReferenceType | None = None,
    transaction_type: TransactionType | None = None,
    payment_method: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    limit: int = 50,
    sort_by: str = "transaction_date",
    sort_order: str = "desc",
) -> tuple[list[Transaction], int]:
    return await _txn_repo.list_all(
        db,
        reference_type=reference_type,
        transaction_type=transaction_type,
        payment_method=payment_method,
        from_date=from_date,
        to_date=to_date,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )
