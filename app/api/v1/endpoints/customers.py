"""
Customer endpoints.

Sub-resource routes (/{id}/balance, /{id}/payments, /{id}/ledger) are
registered on the same router; FastAPI correctly resolves static path
segments before integer captures.

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
from app.models.enums import BalanceType
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.customer import (
    CustomerBalanceSummary,
    CustomerCreate,
    CustomerLedgerEntry,
    CustomerListOut,
    CustomerOut,
    CustomerPaymentCreate,
    CustomerPaymentOut,
    CustomerUpdate,
    SortField,
    SortOrder,
)
from app.services import customer_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("customers", "read"))]
WriteDep = Annotated[User, Depends(require_permission("customers", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("customers", "delete"))]


# ── POST /customers ───────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new customer",
)
async def create_customer(
    body: CustomerCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[CustomerOut]:
    customer = await customer_service.create_customer(
        db, body, created_by=current_user.id
    )
    await db.commit()
    return SuccessResponse(data=CustomerOut.model_validate(customer))


# ── GET /customers ────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List customers with filtering, sorting, and pagination",
)
async def list_customers(
    db: DbDep,
    _: ReadDep,
    search: str | None = Query(None, description="Search by name (case-insensitive)"),
    balance_type: BalanceType | None = Query(None),
    is_active: bool | None = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: SortField = Query("name"),
    sort_order: SortOrder = Query("asc"),
) -> PaginatedResponse[CustomerListOut]:
    customers, total = await customer_service.list_customers(
        db,
        search=search,
        balance_type=balance_type,
        is_active=is_active,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.build(
        [CustomerListOut.model_validate(c) for c in customers],
        total=total,
        page=page,
        limit=limit,
    )


# ── GET /customers/{id} ───────────────────────────────────────────────────────

@router.get(
    "/{customer_id}",
    summary="Get a customer by ID",
)
async def get_customer(
    customer_id: int,
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[CustomerOut]:
    customer = await customer_service.get_customer(db, customer_id)
    return SuccessResponse(data=CustomerOut.model_validate(customer))


# ── PATCH /customers/{id} ─────────────────────────────────────────────────────

@router.patch(
    "/{customer_id}",
    summary="Partially update a customer (PATCH semantics)",
)
async def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[CustomerOut]:
    customer = await customer_service.update_customer(db, customer_id, body, updated_by=current_user.id)
    await db.commit()
    return SuccessResponse(data=CustomerOut.model_validate(customer))


# ── DELETE /customers/{id} ────────────────────────────────────────────────────

@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a customer (sets is_active=False)",
)
async def delete_customer(
    customer_id: int,
    db: DbDep,
    current_user: DeleteDep,
) -> SuccessResponse[None]:
    await customer_service.delete_customer(db, customer_id, deleted_by=current_user.id)
    await db.commit()
    return SuccessResponse(data=None)


# ── GET /customers/{id}/balance ───────────────────────────────────────────────

@router.get(
    "/{customer_id}/balance",
    summary="Get balance summary for a customer",
)
async def get_balance_summary(
    customer_id: int,
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[CustomerBalanceSummary]:
    summary = await customer_service.get_balance_summary(db, customer_id)
    return SuccessResponse(data=summary)


# ── POST /customers/{id}/payments ─────────────────────────────────────────────

@router.post(
    "/{customer_id}/payments",
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment received from a customer",
)
async def record_payment(
    customer_id: int,
    body: CustomerPaymentCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[CustomerPaymentOut]:
    payment = await customer_service.record_payment(
        db, customer_id, body, created_by=current_user.id
    )
    await db.commit()
    return SuccessResponse(data=CustomerPaymentOut.model_validate(payment))


# ── GET /customers/{id}/payments ──────────────────────────────────────────────

@router.get(
    "/{customer_id}/payments",
    summary="List payments received from a customer",
)
async def list_payments(
    customer_id: int,
    db: DbDep,
    _: ReadDep,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[CustomerPaymentOut]:
    payments, total = await customer_service.list_payments(
        db, customer_id, page=page, limit=limit
    )
    return PaginatedResponse.build(
        [CustomerPaymentOut.model_validate(p) for p in payments],
        total=total,
        page=page,
        limit=limit,
    )


# ── GET /customers/{id}/ledger ────────────────────────────────────────────────

@router.get(
    "/{customer_id}/ledger",
    summary="Get the full ledger (sales + payments) for a customer",
)
async def get_ledger(
    customer_id: int,
    db: DbDep,
    _: ReadDep,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[CustomerLedgerEntry]:
    entries, total = await customer_service.get_ledger(
        db,
        customer_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
    )
    return PaginatedResponse.build(entries, total=total, page=page, limit=limit)
