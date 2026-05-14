"""
Transactions / Accounts endpoints.

Account routes:
  POST   /accounts                        — create account
  GET    /accounts                        — list accounts
  GET    /accounts/{id}                   — account detail
  PATCH  /accounts/{id}                   — update account metadata
  DELETE /accounts/{id}                   — deactivate (soft-delete, zero-balance only)
  GET    /accounts/{id}/transactions      — paginated transaction history

Transfer routes:
  POST   /transfers                       — create a transfer between accounts
  GET    /transfers                       — list all transfers

RBAC:
  read   → staff, manager, admin
  write  → manager, admin
  delete → admin only
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.models.enums import AccountType, ReferenceType, TransactionType
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.transaction import (
    AccountCreate,
    AccountListOut,
    AccountOut,
    AccountSortField,
    AccountUpdate,
    SortOrder,
    TransactionOut,
    TransactionSortField,
    TransferCreate,
    TransferOut,
)
from app.services import transaction_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("transactions", "read"))]
WriteDep = Annotated[User, Depends(require_permission("transactions", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("transactions", "delete"))]


# ── Accounts ──────────────────────────────────────────────────────────────────

@router.post(
    "/accounts",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def create_account(
    body: AccountCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[AccountOut]:
    account = await transaction_service.create_account(
        db, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(account)
    return SuccessResponse(data=AccountOut.model_validate(account))


@router.get("/accounts", summary="List accounts")
async def list_accounts(
    db: DbDep,
    _: ReadDep,
    account_type: Annotated[AccountType | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = True,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: Annotated[AccountSortField, Query()] = "name",
    sort_order: Annotated[SortOrder, Query()] = "asc",
) -> PaginatedResponse[AccountListOut]:
    accounts, total = await transaction_service.list_accounts(
        db,
        account_type=account_type,
        is_active=is_active,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.build(
        [AccountListOut.model_validate(a) for a in accounts],
        total=total, page=page, limit=limit,
    )


@router.get("/accounts/{account_id}", summary="Get account detail")
async def get_account(
    account_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[AccountOut]:
    account = await transaction_service.get_account(db, account_id)
    return SuccessResponse(data=AccountOut.model_validate(account))


@router.patch("/accounts/{account_id}", summary="Update account metadata")
async def update_account(
    account_id: int,
    body: AccountUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[AccountOut]:
    account = await transaction_service.update_account(db, account_id, body, updated_by=current_user.id)
    await db.commit()
    await db.refresh(account)
    return SuccessResponse(data=AccountOut.model_validate(account))


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Deactivate an account (zero-balance only)",
)
async def deactivate_account(
    account_id: int,
    db: DbDep,
    current_user: DeleteDep,
) -> None:
    await transaction_service.deactivate_account(db, account_id, deactivated_by=current_user.id)
    await db.commit()


@router.get("/accounts/{account_id}/transactions", summary="Transaction history for an account")
async def list_transactions(
    account_id: int,
    db: DbDep,
    _: ReadDep,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    transaction_type: Annotated[TransactionType | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    sort_by: Annotated[TransactionSortField, Query()] = "transaction_date",
    sort_order: Annotated[SortOrder, Query()] = "desc",
) -> PaginatedResponse[TransactionOut]:
    txns, total = await transaction_service.list_transactions(
        db,
        account_id,
        from_date=from_date,
        to_date=to_date,
        transaction_type=transaction_type,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.build(
        [TransactionOut.model_validate(t) for t in txns],
        total=total, page=page, limit=limit,
    )


# ── Global transaction ledger (reference-only + account-linked) ───────────────

@router.get("/transactions", summary="Global financial ledger")
async def list_all_transactions(
    db: DbDep,
    _: ReadDep,
    reference_type: Annotated[ReferenceType | None, Query()] = None,
    transaction_type: Annotated[TransactionType | None, Query()] = None,
    payment_method: Annotated[str | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    sort_by: Annotated[TransactionSortField, Query()] = "transaction_date",
    sort_order: Annotated[SortOrder, Query()] = "desc",
) -> PaginatedResponse[TransactionOut]:
    txns, total = await transaction_service.list_all_transactions(
        db,
        reference_type=reference_type,
        transaction_type=transaction_type,
        payment_method=payment_method,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.build(
        [TransactionOut.model_validate(t) for t in txns],
        total=total, page=page, limit=limit,
    )


# ── Transfers ─────────────────────────────────────────────────────────────────

@router.post(
    "/transfers",
    status_code=status.HTTP_201_CREATED,
    summary="Transfer funds between two accounts",
)
async def create_transfer(
    body: TransferCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[TransferOut]:
    transfer = await transaction_service.create_transfer(
        db, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(transfer)
    return SuccessResponse(data=TransferOut.model_validate(transfer))


@router.get("/transfers", summary="List all transfers")
async def list_transfers(
    db: DbDep,
    _: ReadDep,
    account_id: Annotated[int | None, Query(description="Filter by from or to account")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PaginatedResponse[TransferOut]:
    transfers, total = await transaction_service.list_transfers(
        db,
        account_id=account_id,
        page=page,
        limit=limit,
    )
    return PaginatedResponse.build(
        [TransferOut.model_validate(t) for t in transfers],
        total=total, page=page, limit=limit,
    )
