"""
Repository for the Transactions / Accounts module. Data access only.

Entities:
  AccountRepository      — account CRUD + balance mutations
  TransactionRepository  — immutable ledger entry insert + list
  TransferRepository     — transfer insert + list
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AccountType, ReferenceType, TransactionType
from app.models.transaction import Account, Transaction, Transfer
from app.repositories.base_repo import BaseRepository


class AccountRepository(BaseRepository[Account]):
    model = Account

    async def get_with_lock(self, db: AsyncSession, account_id: int) -> Account | None:
        result = await db.execute(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_accounts(
        self,
        db: AsyncSession,
        *,
        account_type: AccountType | None = None,
        is_active: bool | None = True,
        skip: int = 0,
        limit: int = 20,
        sort_by: Literal["name", "current_balance", "created_at"] = "name",
        sort_order: Literal["asc", "desc"] = "asc",
    ) -> tuple[list[Account], int]:
        conditions = []
        if account_type is not None:
            conditions.append(Account.account_type == account_type)
        if is_active is not None:
            conditions.append(Account.is_active == is_active)

        stmt = select(Account)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "name": Account.name,
            "current_balance": Account.current_balance,
            "created_at": Account.created_at,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def apply_balance_delta(
        self,
        db: AsyncSession,
        account: Account,
        *,
        delta: Decimal,
    ) -> None:
        """Add delta (positive = credit in, negative = debit out) to current_balance."""
        account.current_balance += delta
        db.add(account)

    async def get_by_name(self, db: AsyncSession, name: str) -> Account | None:
        result = await db.execute(
            select(Account).where(Account.name == name)
        )
        return result.scalar_one_or_none()


class TransactionRepository:

    async def record(
        self,
        db: AsyncSession,
        *,
        account_id: int | None,
        transaction_type: TransactionType,
        reference_type: ReferenceType,
        reference_id: int | None,
        amount: Decimal,
        balance_after: Decimal | None,
        description: str,
        transaction_date: date,
        created_by: int,
        payment_method: str | None = None,
    ) -> Transaction:
        txn = Transaction(
            account_id=account_id,
            payment_method=payment_method,
            transaction_type=transaction_type,
            reference_type=reference_type,
            reference_id=reference_id,
            amount=amount,
            balance_after=balance_after,
            description=description,
            transaction_date=transaction_date,
            created_by=created_by,
        )
        db.add(txn)
        await db.flush()
        await db.refresh(txn)
        return txn

    async def list_for_account(
        self,
        db: AsyncSession,
        account_id: int,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        transaction_type: TransactionType | None = None,
        skip: int = 0,
        limit: int = 50,
        sort_by: Literal["transaction_date", "amount", "created_at"] = "transaction_date",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> tuple[list[Transaction], int]:
        conditions = [Transaction.account_id == account_id]
        if from_date is not None:
            conditions.append(Transaction.transaction_date >= from_date)
        if to_date is not None:
            conditions.append(Transaction.transaction_date <= to_date)
        if transaction_type is not None:
            conditions.append(Transaction.transaction_type == transaction_type)

        stmt = select(Transaction).where(and_(*conditions))

        sort_col = {
            "transaction_date": Transaction.transaction_date,
            "amount": Transaction.amount,
            "created_at": Transaction.created_at,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total


    async def list_all(
        self,
        db: AsyncSession,
        *,
        reference_type: ReferenceType | None = None,
        transaction_type: TransactionType | None = None,
        payment_method: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        skip: int = 0,
        limit: int = 50,
        sort_by: Literal["transaction_date", "amount", "created_at"] = "transaction_date",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> tuple[list[Transaction], int]:
        conditions: list[Any] = []
        if reference_type is not None:
            conditions.append(Transaction.reference_type == reference_type)
        if transaction_type is not None:
            conditions.append(Transaction.transaction_type == transaction_type)
        if payment_method is not None:
            conditions.append(Transaction.payment_method == payment_method)
        if from_date is not None:
            conditions.append(Transaction.transaction_date >= from_date)
        if to_date is not None:
            conditions.append(Transaction.transaction_date <= to_date)

        stmt = select(Transaction)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "transaction_date": Transaction.transaction_date,
            "amount": Transaction.amount,
            "created_at": Transaction.created_at,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total


class TransferRepository:

    async def create(
        self,
        db: AsyncSession,
        *,
        from_account_id: int,
        to_account_id: int,
        amount: Decimal,
        reference_no: str | None,
        note: str | None,
        transferred_at: datetime,
        created_by: int | None,
    ) -> Transfer:
        transfer = Transfer(
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            amount=amount,
            reference_no=reference_no,
            note=note,
            transferred_at=transferred_at,
            created_by=created_by,
        )
        db.add(transfer)
        await db.flush()
        await db.refresh(transfer)
        return transfer

    async def list_for_account(
        self,
        db: AsyncSession,
        account_id: int,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Transfer], int]:
        conditions = [
            (Transfer.from_account_id == account_id) | (Transfer.to_account_id == account_id)
        ]
        stmt = (
            select(Transfer)
            .where(*conditions)
            .order_by(desc(Transfer.transferred_at))
        )

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def list_all(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Transfer], int]:
        stmt = select(Transfer).order_by(desc(Transfer.transferred_at))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total
