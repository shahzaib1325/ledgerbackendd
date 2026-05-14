"""
Supplier endpoints.

All sub-resource routes (/{id}/balance, /{id}/payments, /{id}/ledger)
are declared before /{id} in the file, but FastAPI resolves path segments
correctly regardless — "balance", "payments", "ledger" are never parsed
as integer supplier IDs.

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
from app.schemas.supplier import (
    SortField,
    SortOrder,
    SupplierBalanceSummary,
    SupplierCreate,
    SupplierLedgerEntry,
    SupplierListOut,
    SupplierOut,
    SupplierPaymentCreate,
    SupplierPaymentOut,
    SupplierUpdate,
)
from app.services import supplier_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("suppliers", "read"))]
WriteDep = Annotated[User, Depends(require_permission("suppliers", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("suppliers", "delete"))]


# ── POST /suppliers ───────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new supplier",
)
async def create_supplier(
    body: SupplierCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SupplierOut]:
    supplier = await supplier_service.create_supplier(
        db, body, created_by=current_user.id
    )
    await db.commit()
    return SuccessResponse(data=SupplierOut.model_validate(supplier))


# ── GET /suppliers/{id}/balance ───────────────────────────────────────────────
# Declared before /{supplier_id} generic routes; FastAPI resolves static path
# segments before integer captures, so "balance" is never parsed as an int.

@router.get(
    "/{supplier_id}/balance",
    summary="Get balance summary for a supplier",
)
async def get_balance_summary(
    supplier_id: int,
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[SupplierBalanceSummary]:
    summary = await supplier_service.get_balance_summary(db, supplier_id)
    return SuccessResponse(data=summary)


# ── GET /suppliers ────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List suppliers with filtering, sorting, and pagination",
)
async def list_suppliers(
    db: DbDep,
    _: ReadDep,
    search: str | None = Query(None, description="Search by name (case-insensitive)"),
    balance_type: BalanceType | None = Query(None),
    is_active: bool | None = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: SortField = Query("name"),
    sort_order: SortOrder = Query("asc"),
) -> PaginatedResponse[SupplierListOut]:
    suppliers, total = await supplier_service.list_suppliers(
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
        [SupplierListOut.model_validate(s) for s in suppliers],
        total=total,
        page=page,
        limit=limit,
    )


# ── GET /suppliers/{id} ───────────────────────────────────────────────────────

@router.get(
    "/{supplier_id}",
    summary="Get a supplier by ID",
)
async def get_supplier(
    supplier_id: int,
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[SupplierOut]:
    supplier = await supplier_service.get_supplier(db, supplier_id)
    return SuccessResponse(data=SupplierOut.model_validate(supplier))


# ── PATCH /suppliers/{id} ─────────────────────────────────────────────────────

@router.patch(
    "/{supplier_id}",
    summary="Partially update a supplier (PATCH semantics)",
)
async def update_supplier(
    supplier_id: int,
    body: SupplierUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SupplierOut]:
    supplier = await supplier_service.update_supplier(db, supplier_id, body, updated_by=current_user.id)
    await db.commit()
    return SuccessResponse(data=SupplierOut.model_validate(supplier))


# ── DELETE /suppliers/{id} ────────────────────────────────────────────────────

@router.delete(
    "/{supplier_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a supplier (sets is_active=False)",
)
async def delete_supplier(
    supplier_id: int,
    db: DbDep,
    current_user: DeleteDep,
) -> SuccessResponse[None]:
    await supplier_service.delete_supplier(db, supplier_id, deleted_by=current_user.id)
    await db.commit()
    return SuccessResponse(data=None)


# ── POST /suppliers/{id}/payments ─────────────────────────────────────────────

@router.post(
    "/{supplier_id}/payments",
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment to a supplier",
)
async def record_payment(
    supplier_id: int,
    body: SupplierPaymentCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SupplierPaymentOut]:
    payment = await supplier_service.record_payment(
        db, supplier_id, body, created_by=current_user.id
    )
    await db.commit()
    return SuccessResponse(data=SupplierPaymentOut.model_validate(payment))


# ── GET /suppliers/{id}/payments ──────────────────────────────────────────────

@router.get(
    "/{supplier_id}/payments",
    summary="List payments made to a supplier",
)
async def list_payments(
    supplier_id: int,
    db: DbDep,
    _: ReadDep,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[SupplierPaymentOut]:
    payments, total = await supplier_service.list_payments(
        db, supplier_id, page=page, limit=limit
    )
    return PaginatedResponse.build(
        [SupplierPaymentOut.model_validate(p) for p in payments],
        total=total,
        page=page,
        limit=limit,
    )


# ── GET /suppliers/{id}/ledger ────────────────────────────────────────────────

@router.get(
    "/{supplier_id}/ledger",
    summary="Get the full ledger (purchases + payments) for a supplier",
)
async def get_ledger(
    supplier_id: int,
    db: DbDep,
    _: ReadDep,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[SupplierLedgerEntry]:
    entries, total = await supplier_service.get_ledger(
        db,
        supplier_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
    )
    return PaginatedResponse.build(entries, total=total, page=page, limit=limit)
