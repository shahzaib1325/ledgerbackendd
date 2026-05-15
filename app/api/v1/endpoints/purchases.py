"""
Purchase endpoints.

Lifecycle routes:
  POST   /purchases                        — create draft
  GET    /purchases                        — list with filters
  GET    /purchases/{id}                   — detail with line items
  PATCH  /purchases/{id}                   — update draft fields
  POST   /purchases/{id}/confirm           — confirm → triggers stock + supplier balance
  POST   /purchases/{id}/void              — void a draft
  POST   /purchases/{id}/payments          — record a payment
  GET    /purchases/{id}/payments          — list payments
  POST   /purchases/{id}/returns           — create a return (pending)
  GET    /purchases/{id}/returns           — list returns
  POST   /purchases/{id}/returns/{rid}/approve — approve a return

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
from app.models.enums import PaymentType, PurchaseStatus
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.purchase import (
    PurchaseCreate,
    PurchaseListOut,
    PurchaseOut,
    PurchasePaymentCreate,
    PurchasePaymentOut,
    PurchaseReturnCreate,
    PurchaseReturnRejectRequest,
    PurchaseReturnOut,
    PurchaseSortField,
    PurchaseUpdate,
    SortOrder,
)
from app.services import purchase_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("purchases", "read"))]
WriteDep = Annotated[User, Depends(require_permission("purchases", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("purchases", "delete"))]


# ── Create ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a purchase order (draft)",
)
async def create_purchase(
    body: PurchaseCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[PurchaseOut]:
    purchase = await purchase_service.create_purchase(
        db, body, created_by=current_user.id
    )
    await db.commit()
    # Re-fetch with all needed relationships
    purchase = await purchase_service.get_purchase(db, purchase.id)
    # Force load server-side/computed columns in async context
    await db.refresh(purchase, ["due_amount", "updated_at", "created_at", "items"])
    db.expunge(purchase)
    return SuccessResponse(data=PurchaseOut.model_validate(purchase))


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", summary="List purchases")
async def list_purchases(
    db: DbDep,
    _: ReadDep,
    supplier_id: int | None = Query(None),
    status: PurchaseStatus | None = Query(None),
    payment_type: PaymentType | None = Query(None),
    search: str | None = Query(None, description="Search by invoice number"),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: PurchaseSortField = Query("purchase_date"),
    sort_order: SortOrder = Query("desc"),
) -> PaginatedResponse[PurchaseListOut]:
    purchases, total = await purchase_service.list_purchases(
        db,
        supplier_id=supplier_id,
        status=status,
        payment_type=payment_type,
        search=search,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    rows = [
        PurchaseListOut.model_validate({
            "id": p.id,
            "supplier_id": p.supplier_id,
            "supplier_name": p.supplier.name if p.supplier else "",
            "invoice_no": p.invoice_no,
            "purchase_date": p.purchase_date,
            "payment_type": p.payment_type,
            "total_amount": p.total_amount,
            "paid_amount": p.paid_amount,
            "due_amount": p.due_amount,
            "status": p.status,
            "created_at": p.created_at,
        })
        for p in purchases
    ]
    return PaginatedResponse.build(rows, total=total, page=page, limit=limit)


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{purchase_id}", summary="Get purchase detail with line items")
async def get_purchase(
    purchase_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[PurchaseOut]:
    purchase = await purchase_service.get_purchase(db, purchase_id)
    return SuccessResponse(data=PurchaseOut.model_validate(purchase))


# ── Update (draft only) ───────────────────────────────────────────────────────

@router.patch("/{purchase_id}", summary="Update a draft purchase")
async def update_purchase(
    purchase_id: int,
    body: PurchaseUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[PurchaseOut]:
    purchase = await purchase_service.update_purchase(db, purchase_id, body, updated_by=current_user.id)
    await db.commit()
    purchase = await purchase_service.get_purchase(db, purchase_id)
    return SuccessResponse(data=PurchaseOut.model_validate(purchase))


# ── Confirm ───────────────────────────────────────────────────────────────────

@router.post(
    "/{purchase_id}/confirm",
    summary="Confirm a draft purchase (moves stock, updates supplier balance)",
)
async def confirm_purchase(
    purchase_id: int,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[PurchaseOut]:
    purchase = await purchase_service.confirm_purchase(
        db, purchase_id, confirmed_by=current_user.id
    )
    purchase_id_val = purchase.id
    await db.commit()
    
    # Use raw SQL to fetch a clean dict and avoid MissingGreenlet
    from sqlalchemy import text
    p_res = await db.execute(text("SELECT * FROM purchases WHERE id = :id"), {"id": purchase_id_val})
    p_row = p_res.mappings().one()
    
    i_res = await db.execute(text("SELECT * FROM purchase_items WHERE purchase_id = :id"), {"id": purchase_id_val})
    i_rows = i_res.mappings().all()
    
    data = dict(p_row)
    data["items"] = [dict(r) for r in i_rows]
    
    return SuccessResponse(data=PurchaseOut.model_validate(data))


# ── Void ──────────────────────────────────────────────────────────────────────

@router.post(
    "/{purchase_id}/void",
    summary="Void a draft purchase",
)
async def void_purchase(
    purchase_id: int,
    db: DbDep,
    current_user: DeleteDep,
) -> SuccessResponse[PurchaseOut]:
    purchase = await purchase_service.void_purchase(db, purchase_id, voided_by=current_user.id)
    await db.commit()
    purchase = await purchase_service.get_purchase(db, purchase_id)
    return SuccessResponse(data=PurchaseOut.model_validate(purchase))


# ── Payments ──────────────────────────────────────────────────────────────────

@router.post(
    "/{purchase_id}/payments",
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment against a confirmed purchase",
)
async def record_payment(
    purchase_id: int,
    body: PurchasePaymentCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[PurchasePaymentOut]:
    payment = await purchase_service.record_payment(
        db, purchase_id, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(payment)
    return SuccessResponse(data=PurchasePaymentOut.model_validate(payment))


@router.get("/{purchase_id}/payments", summary="List payments for a purchase")
async def list_payments(
    purchase_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[list[PurchasePaymentOut]]:
    payments = await purchase_service.list_payments(db, purchase_id)
    return SuccessResponse(
        data=[PurchasePaymentOut.model_validate(p) for p in payments]
    )


# ── Returns ───────────────────────────────────────────────────────────────────

@router.post(
    "/{purchase_id}/returns",
    status_code=status.HTTP_201_CREATED,
    summary="Create a return request for a confirmed purchase",
)
async def create_return(
    purchase_id: int,
    body: PurchaseReturnCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[PurchaseReturnOut]:
    purchase_return = await purchase_service.create_return(
        db, purchase_id, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(purchase_return)
    return SuccessResponse(data=PurchaseReturnOut.model_validate(purchase_return))


@router.get("/{purchase_id}/returns", summary="List returns for a purchase")
async def list_returns(
    purchase_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[list[PurchaseReturnOut]]:
    returns = await purchase_service.list_returns(db, purchase_id)
    return SuccessResponse(
        data=[PurchaseReturnOut.model_validate(r) for r in returns]
    )


@router.post(
    "/{purchase_id}/returns/{return_id}/approve",
    summary="Approve a pending return (reverses stock and supplier balance)",
)
async def approve_return(
    purchase_id: int,
    return_id: int,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[PurchaseReturnOut]:
    purchase_return = await purchase_service.approve_return(
        db, purchase_id, return_id, approved_by=current_user.id
    )
    await db.commit()
    return SuccessResponse(data=PurchaseReturnOut.model_validate(purchase_return))


@router.post(
    "/{purchase_id}/returns/{return_id}/reject",
    summary="Reject a pending return",
)
async def reject_return(
    purchase_id: int,
    return_id: int,
    body: PurchaseReturnRejectRequest,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[PurchaseReturnOut]:
    purchase_return = await purchase_service.reject_return(
        db, purchase_id, return_id,
        rejected_by=current_user.id,
        rejection_reason=body.rejection_reason,
    )
    await db.commit()
    return SuccessResponse(data=PurchaseReturnOut.model_validate(purchase_return))
