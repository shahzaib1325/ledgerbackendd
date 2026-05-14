"""
Production endpoints.

Order routes:
  POST   /production                          — create order (planned)
  GET    /production                          — list orders with filters
  GET    /production/{id}                     — order detail with all children
  PATCH  /production/{id}                     — update dates/notes (planned/in_progress)
  POST   /production/{id}/start               — planned → in_progress
  POST   /production/{id}/complete            — in_progress → completed (triggers stock)
  POST   /production/{id}/cancel              — planned/in_progress → cancelled

Line-item routes (add while planned or in_progress):
  POST   /production/{id}/labor               — add a labor entry
  POST   /production/{id}/costs               — add an overhead cost entry

RBAC:
  read   → staff, manager, admin
  write  → manager, admin
  delete → admin only  (cancel is treated as delete)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.models.enums import ProductionStatus
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.production import (
    LaborCreate,
    LaborOut,
    ProductionCostCreate,
    ProductionCostOut,
    ProductionOrderCreate,
    ProductionOrderListOut,
    ProductionOrderOut,
    ProductionOrderUpdate,
    ProductionOutputCreate,
    ProductionSortField,
    SortOrder,
)
from app.services import production_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _serialize_order(order) -> ProductionOrderOut:
    return ProductionOrderOut.model_validate({
        "id": order.id,
        "order_no": order.order_no,
        "product_item_id": order.product_item_id,
        "product_item_name": order.product_item.name if order.product_item else "",
        "quantity_to_produce": order.quantity_to_produce,
        "start_date": order.start_date,
        "end_date": order.end_date,
        "status": order.status,
        "total_material_cost": order.total_material_cost,
        "total_labor_cost": order.total_labor_cost,
        "total_other_cost": order.total_other_cost,
        "total_cost": order.total_cost,
        "selling_price": order.selling_price,
        "notes": order.notes,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "raw_materials": [
            {"id": m.id, "order_id": m.order_id, "item_id": m.item_id, "unit_id": m.unit_id,
             "required_quantity": m.required_quantity, "used_quantity": m.used_quantity,
             "unit_cost": m.unit_cost, "total_cost": m.total_cost}
            for m in order.raw_materials
        ],
        "labor": [
            {"id": lb.id, "order_id": lb.order_id, "staff_id": lb.staff_id,
             "category_id": lb.item_id, "quantity_produced": lb.quantity_produced,
             "rate_per_unit": lb.rate_per_unit, "total_cost": lb.total_cost}
            for lb in order.labor
        ],
        "costs": [
            {"id": c.id, "order_id": c.order_id, "cost_type": c.cost_type,
             "amount": c.amount, "note": c.note}
            for c in order.costs
        ],
        "outputs": [
            {"id": out.id, "order_id": out.order_id, "item_id": out.item_id,
             "quantity_produced": out.quantity_produced, "produced_at": out.produced_at}
            for out in order.outputs
        ],
    })


ReadDep = Annotated[User, Depends(require_permission("production", "read"))]
WriteDep = Annotated[User, Depends(require_permission("production", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("production", "delete"))]


# ── Create ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a production order (planned)",
)
async def create_order(
    body: ProductionOrderCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[ProductionOrderOut]:
    order = await production_service.create_order(
        db, body, created_by=current_user.id
    )
    await db.commit()

    # Re-fetch after commit via raw SQL to avoid MissingGreenlet on total_cost (Computed)
    from sqlalchemy import text
    o_res = await db.execute(
        text("SELECT * FROM production_orders WHERE id = :id"), {"id": order.id}
    )
    o_row = dict(o_res.mappings().one())

    mat_res = await db.execute(
        text("SELECT * FROM production_raw_materials WHERE order_id = :id"), {"id": order.id}
    )
    lab_res = await db.execute(
        text("SELECT * FROM production_labor WHERE order_id = :id"), {"id": order.id}
    )
    cost_res = await db.execute(
        text("SELECT * FROM production_costs WHERE order_id = :id"), {"id": order.id}
    )
    out_res = await db.execute(
        text("SELECT * FROM production_output WHERE order_id = :id"), {"id": order.id}
    )

    item_res = await db.execute(
        text("SELECT name FROM items WHERE id = :id"), {"id": o_row["product_item_id"]}
    )
    o_row["product_item_name"] = item_res.scalar_one_or_none() or ""
    o_row["raw_materials"] = [dict(r) for r in mat_res.mappings().all()]
    o_row["labor"] = [dict(r) for r in lab_res.mappings().all()]
    o_row["costs"] = [dict(r) for r in cost_res.mappings().all()]
    o_row["outputs"] = [dict(r) for r in out_res.mappings().all()]

    return SuccessResponse(data=ProductionOrderOut.model_validate(o_row))


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", summary="List production orders")
async def list_orders(
    db: DbDep,
    _: ReadDep,
    status: Annotated[ProductionStatus | None, Query()] = None,
    product_item_id: Annotated[int | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: Annotated[ProductionSortField, Query()] = "created_at",
    sort_order: Annotated[SortOrder, Query()] = "desc",
) -> PaginatedResponse[ProductionOrderListOut]:
    orders, total = await production_service.list_orders(
        db,
        status=status,
        product_item_id=product_item_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    rows = [
        ProductionOrderListOut.model_validate({
            "id": o.id,
            "order_no": o.order_no,
            "product_item_id": o.product_item_id,
            "product_item_name": o.product_item.name if o.product_item else "",
            "quantity_to_produce": o.quantity_to_produce,
            "start_date": o.start_date,
            "end_date": o.end_date,
            "status": o.status,
            "total_cost": o.total_cost,
            "selling_price": o.selling_price,
            "created_at": o.created_at,
        })
        for o in orders
    ]
    return PaginatedResponse.build(rows, total=total, page=page, limit=limit)


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{order_id}", summary="Get production order detail")
async def get_order(
    order_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[ProductionOrderOut]:
    order = await production_service.get_order(db, order_id)
    return SuccessResponse(data=_serialize_order(order))


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/{order_id}", summary="Update order dates / notes")
async def update_order(
    order_id: int,
    body: ProductionOrderUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[ProductionOrderOut]:
    order = await production_service.update_order(db, order_id, body, updated_by=current_user.id)
    await db.commit()
    order = await production_service.get_order(db, order_id)
    return SuccessResponse(data=_serialize_order(order))


# ── Status transitions ────────────────────────────────────────────────────────

@router.post("/{order_id}/start", summary="Start a planned production order")
async def start_order(
    order_id: int, db: DbDep, current_user: WriteDep
) -> SuccessResponse[ProductionOrderOut]:
    order = await production_service.start_order(db, order_id, started_by=current_user.id)
    await db.commit()
    order = await production_service.get_order(db, order_id)
    return SuccessResponse(data=_serialize_order(order))


@router.post(
    "/{order_id}/complete",
    summary="Complete a production order (triggers stock movements)",
)
async def complete_order(
    order_id: int,
    body: ProductionOutputCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[ProductionOrderOut]:
    await production_service.complete_order(
        db, order_id, body, completed_by=current_user.id
    )
    await db.commit()

    from sqlalchemy import text
    o_res = await db.execute(
        text("SELECT * FROM production_orders WHERE id = :id"), {"id": order_id}
    )
    o_row = dict(o_res.mappings().one())
    mat_res = await db.execute(
        text("SELECT * FROM production_raw_materials WHERE order_id = :id"), {"id": order_id}
    )
    lab_res = await db.execute(
        text("SELECT * FROM production_labor WHERE order_id = :id"), {"id": order_id}
    )
    cost_res = await db.execute(
        text("SELECT * FROM production_costs WHERE order_id = :id"), {"id": order_id}
    )
    out_res = await db.execute(
        text("SELECT * FROM production_output WHERE order_id = :id"), {"id": order_id}
    )
    item_name_res = await db.execute(
        text("SELECT name FROM items WHERE id = :id"), {"id": o_row["product_item_id"]}
    )
    o_row["product_item_name"] = item_name_res.scalar_one_or_none() or ""
    o_row["raw_materials"] = [dict(r) for r in mat_res.mappings().all()]
    o_row["labor"] = [dict(r) for r in lab_res.mappings().all()]
    o_row["costs"] = [dict(r) for r in cost_res.mappings().all()]
    o_row["outputs"] = [dict(r) for r in out_res.mappings().all()]
    return SuccessResponse(data=ProductionOrderOut.model_validate(o_row))


@router.post("/{order_id}/cancel", summary="Cancel a production order")
async def cancel_order(
    order_id: int, db: DbDep, current_user: DeleteDep
) -> SuccessResponse[ProductionOrderOut]:
    order = await production_service.cancel_order(db, order_id, cancelled_by=current_user.id)
    await db.commit()
    order = await production_service.get_order(db, order_id)
    return SuccessResponse(data=_serialize_order(order))


# ── Add line items ─────────────────────────────────────────────────────────────

@router.post(
    "/{order_id}/labor",
    status_code=status.HTTP_201_CREATED,
    summary="Add a labor entry to a production order",
)
async def add_labor(
    order_id: int,
    body: LaborCreate,
    db: DbDep,
    _: WriteDep,
) -> SuccessResponse[LaborOut]:
    labor = await production_service.add_labor(db, order_id, body)
    await db.commit()
    await db.refresh(labor)
    return SuccessResponse(data=LaborOut.model_validate(labor))


@router.post(
    "/{order_id}/costs",
    status_code=status.HTTP_201_CREATED,
    summary="Add an overhead cost entry to a production order",
)
async def add_cost(
    order_id: int,
    body: ProductionCostCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[ProductionCostOut]:
    cost = await production_service.add_cost(db, order_id, body, created_by=current_user.id)
    await db.commit()
    await db.refresh(cost)
    return SuccessResponse(data=ProductionCostOut.model_validate(cost))
