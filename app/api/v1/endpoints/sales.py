"""
Sale endpoints.

Lifecycle routes:
  POST   /sales                          — create draft
  GET    /sales                          — list with filters
  GET    /sales/{id}                     — detail with line items
  PATCH  /sales/{id}                     — update draft fields
  POST   /sales/{id}/confirm             — confirm → triggers stock-out + customer balance
  POST   /sales/{id}/void                — void a draft
  POST   /sales/{id}/payments            — record a payment
  GET    /sales/{id}/payments            — list payments
  POST   /sales/{id}/returns             — create a return (pending)
  GET    /sales/{id}/returns             — list returns
  POST   /sales/{id}/returns/{rid}/approve — approve a return

RBAC:
  read   → staff, manager, admin
  write  → manager, admin
  delete → admin only  (void is treated as delete)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.models.enums import SaleStatus
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.sale import (
    SaleCreate,
    SaleListOut,
    SaleOut,
    SalePaymentCreate,
    SalePaymentOut,
    SaleReturnCreate,
    SaleReturnOut,
    SaleReturnRejectRequest,
    SaleSortField,
    SaleUpdate,
    SortOrder,
)
from app.services import sale_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("sales", "read"))]
WriteDep = Annotated[User, Depends(require_permission("sales", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("sales", "delete"))]


# ── Create ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a sale invoice (draft)",
)
async def create_sale(
    body: SaleCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SaleOut]:
    invoice = await sale_service.create_sale(db, body, created_by=current_user.id)
    await db.commit()
    invoice = await sale_service.get_sale(db, invoice.id)
    await db.refresh(invoice, ["due_amount", "updated_at", "created_at", "items"])
    db.expunge(invoice)
    return SuccessResponse(data=SaleOut.model_validate(invoice))


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", summary="List sale invoices")
async def list_sales(
    db: DbDep,
    _: ReadDep,
    customer_id: int | None = Query(None),
    status: SaleStatus | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    overdue_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: SaleSortField = Query("invoice_date"),
    sort_order: SortOrder = Query("desc"),
) -> PaginatedResponse[SaleListOut]:
    invoices, total = await sale_service.list_sales(
        db,
        customer_id=customer_id,
        status=status,
        from_date=from_date,
        to_date=to_date,
        overdue_only=overdue_only,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    rows = [
        SaleListOut.model_validate({
            **{c.key: getattr(s, c.key) for c in s.__table__.columns},
            "customer_name": s.customer.name if s.customer else "Walk-in",
            "customer_type": s.customer_type,
        })
        for s in invoices
    ]
    return PaginatedResponse.build(rows, total=total, page=page, limit=limit)


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{invoice_id}", summary="Get sale invoice detail with line items")
async def get_sale(
    invoice_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[SaleOut]:
    invoice = await sale_service.get_sale(db, invoice_id)
    return SuccessResponse(data=SaleOut.model_validate(invoice))


# ── Update (draft only) ───────────────────────────────────────────────────────

@router.patch("/{invoice_id}", summary="Update a draft sale invoice")
async def update_sale(
    invoice_id: int,
    body: SaleUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SaleOut]:
    await sale_service.update_sale(db, invoice_id, body, updated_by=current_user.id)
    await db.commit()
    invoice = await sale_service.get_sale(db, invoice_id)
    return SuccessResponse(data=SaleOut.model_validate(invoice))


# ── Confirm ───────────────────────────────────────────────────────────────────

@router.post(
    "/{invoice_id}/confirm",
    summary="Confirm a draft sale (moves stock-out, updates customer balance)",
)
async def confirm_sale(
    invoice_id: int,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SaleOut]:
    await sale_service.confirm_sale(db, invoice_id, confirmed_by=current_user.id)
    await db.commit()
    invoice = await sale_service.get_sale(db, invoice_id)
    return SuccessResponse(data=SaleOut.model_validate(invoice))


# ── Void ──────────────────────────────────────────────────────────────────────

@router.post("/{invoice_id}/void", summary="Void a draft sale invoice")
async def void_sale(
    invoice_id: int,
    db: DbDep,
    current_user: DeleteDep,
) -> SuccessResponse[SaleOut]:
    await sale_service.void_sale(db, invoice_id, voided_by=current_user.id)
    await db.commit()
    invoice = await sale_service.get_sale(db, invoice_id)
    return SuccessResponse(data=SaleOut.model_validate(invoice))


# ── Payments ──────────────────────────────────────────────────────────────────

@router.post(
    "/{invoice_id}/payments",
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment against a confirmed sale invoice",
)
async def record_payment(
    invoice_id: int,
    body: SalePaymentCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SalePaymentOut]:
    payment = await sale_service.record_payment(
        db, invoice_id, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(payment)
    return SuccessResponse(data=SalePaymentOut.model_validate(payment))


@router.get("/{invoice_id}/payments", summary="List payments for a sale invoice")
async def list_payments(
    invoice_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[list[SalePaymentOut]]:
    payments = await sale_service.list_payments(db, invoice_id)
    return SuccessResponse(
        data=[SalePaymentOut.model_validate(p) for p in payments]
    )


# ── Returns ───────────────────────────────────────────────────────────────────

@router.post(
    "/{invoice_id}/returns",
    status_code=status.HTTP_201_CREATED,
    summary="Create a return request for a confirmed sale invoice",
)
async def create_return(
    invoice_id: int,
    body: SaleReturnCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SaleReturnOut]:
    sale_return = await sale_service.create_return(
        db, invoice_id, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(sale_return)
    return SuccessResponse(data=SaleReturnOut.model_validate(sale_return))


@router.get("/{invoice_id}/returns", summary="List returns for a sale invoice")
async def list_returns(
    invoice_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[list[SaleReturnOut]]:
    returns = await sale_service.list_returns(db, invoice_id)
    return SuccessResponse(
        data=[SaleReturnOut.model_validate(r) for r in returns]
    )


@router.get(
    "/{invoice_id}/returns/{return_id}",
    summary="Get a single return with its line items",
)
async def get_return(
    invoice_id: int,
    return_id: int,
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[SaleReturnOut]:
    sale_return = await sale_service.get_return(db, invoice_id, return_id)
    return SuccessResponse(data=SaleReturnOut.model_validate(sale_return))


@router.post(
    "/{invoice_id}/returns/{return_id}/approve",
    summary="Approve a pending return (restores stock, reduces customer balance)",
)
async def approve_return(
    invoice_id: int,
    return_id: int,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SaleReturnOut]:
    sale_return = await sale_service.approve_return(
        db, invoice_id, return_id, approved_by=current_user.id
    )
    await db.commit()
    return SuccessResponse(data=SaleReturnOut.model_validate(sale_return))


@router.post(
    "/{invoice_id}/returns/{return_id}/reject",
    summary="Reject a pending return",
)
async def reject_return(
    invoice_id: int,
    return_id: int,
    body: SaleReturnRejectRequest,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SaleReturnOut]:
    sale_return = await sale_service.reject_return(
        db, invoice_id, return_id,
        rejected_by=current_user.id,
        rejection_reason=body.rejection_reason,
    )
    await db.commit()
    return SuccessResponse(data=SaleReturnOut.model_validate(sale_return))
