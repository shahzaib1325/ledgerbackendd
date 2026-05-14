"""
Inventory endpoints.

Groups:
  /inventory/units      — units of measure
  /inventory/categories — item categories
  /inventory/items      — inventory items
  /inventory/items/{id}/stock     — stock movements history
  /inventory/items/{id}/adjust    — manual stock adjustment

RBAC:
  read   → staff, manager, admin
  write  → manager, admin
  delete → admin only
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.models.enums import ItemType, MovementType
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.inventory import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ItemCreate,
    ItemListOut,
    ItemOut,
    ItemSortField,
    ItemUpdate,
    SortOrder,
    StockAdjustmentCreate,
    StockMovementOut,
    UnitCreate,
    UnitOut,
    UnitUpdate,
)
from app.services import inventory_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("inventory", "read"))]
WriteDep = Annotated[User, Depends(require_permission("inventory", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("inventory", "delete"))]


# ══════════════════════════════════════════════════════════════════════════════
# Units
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/units",
    status_code=status.HTTP_201_CREATED,
    summary="Create a unit of measure",
)
async def create_unit(
    body: UnitCreate,
    db: DbDep,
    _: WriteDep,
) -> SuccessResponse[UnitOut]:
    unit = await inventory_service.create_unit(db, body)
    await db.commit()
    await db.refresh(unit)
    return SuccessResponse(data=UnitOut.model_validate(unit))


@router.get("/units", summary="List units of measure")
async def list_units(
    db: DbDep,
    _: ReadDep,
    is_active: bool | None = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
) -> PaginatedResponse[UnitOut]:
    units, total = await inventory_service.list_units(
        db, is_active=is_active, page=page, limit=limit
    )
    return PaginatedResponse.build(
        [UnitOut.model_validate(u) for u in units],
        total=total, page=page, limit=limit,
    )


@router.get("/units/{unit_id}", summary="Get a unit by ID")
async def get_unit(
    unit_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[UnitOut]:
    unit = await inventory_service.get_unit(db, unit_id)
    return SuccessResponse(data=UnitOut.model_validate(unit))


@router.patch("/units/{unit_id}", summary="Update a unit")
async def update_unit(
    unit_id: int, body: UnitUpdate, db: DbDep, _: WriteDep
) -> SuccessResponse[UnitOut]:
    unit = await inventory_service.update_unit(db, unit_id, body)
    await db.commit()
    await db.refresh(unit)
    return SuccessResponse(data=UnitOut.model_validate(unit))


@router.delete(
    "/units/{unit_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a unit",
)
async def delete_unit(
    unit_id: int, db: DbDep, _: DeleteDep
) -> SuccessResponse[None]:
    await inventory_service.delete_unit(db, unit_id)
    await db.commit()
    return SuccessResponse(data=None)


# ══════════════════════════════════════════════════════════════════════════════
# Categories
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/categories",
    status_code=status.HTTP_201_CREATED,
    summary="Create an item category",
)
async def create_category(
    body: CategoryCreate, db: DbDep, _: WriteDep
) -> SuccessResponse[CategoryOut]:
    cat = await inventory_service.create_category(db, body)
    await db.commit()
    await db.refresh(cat)
    return SuccessResponse(data=CategoryOut.model_validate(cat))


@router.get("/categories", summary="List categories")
async def list_categories(
    db: DbDep,
    _: ReadDep,
    parent_id: int | None = Query(None),
    is_active: bool | None = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
) -> PaginatedResponse[CategoryOut]:
    cats, total = await inventory_service.list_categories(
        db, parent_id=parent_id, is_active=is_active, page=page, limit=limit
    )
    return PaginatedResponse.build(
        [CategoryOut.model_validate(c) for c in cats],
        total=total, page=page, limit=limit,
    )


@router.get("/categories/{category_id}", summary="Get a category by ID")
async def get_category(
    category_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[CategoryOut]:
    cat = await inventory_service.get_category(db, category_id)
    return SuccessResponse(data=CategoryOut.model_validate(cat))


@router.patch("/categories/{category_id}", summary="Update a category")
async def update_category(
    category_id: int, body: CategoryUpdate, db: DbDep, _: WriteDep
) -> SuccessResponse[CategoryOut]:
    cat = await inventory_service.update_category(db, category_id, body)
    await db.commit()
    await db.refresh(cat)
    return SuccessResponse(data=CategoryOut.model_validate(cat))


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a category",
)
async def delete_category(
    category_id: int, db: DbDep, _: DeleteDep
) -> SuccessResponse[None]:
    await inventory_service.delete_category(db, category_id)
    await db.commit()
    return SuccessResponse(data=None)


# ══════════════════════════════════════════════════════════════════════════════
# Items
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/items",
    status_code=status.HTTP_201_CREATED,
    summary="Create an inventory item",
)
async def create_item(
    body: ItemCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[ItemOut]:
    item = await inventory_service.create_item(db, body, created_by=current_user.id)
    await db.commit()
    await db.refresh(item)
    return SuccessResponse(data=ItemOut.model_validate(item))


@router.get("/items", summary="List items with filtering and pagination")
async def list_items(
    db: DbDep,
    _: ReadDep,
    search: str | None = Query(None),
    category_id: int | None = Query(None),
    item_type: ItemType | None = Query(None),
    is_active: bool | None = Query(True),
    low_stock_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=1000),
    sort_by: ItemSortField = Query("name"),
    sort_order: SortOrder = Query("asc"),
) -> PaginatedResponse[ItemListOut]:
    items, total = await inventory_service.list_items(
        db,
        search=search,
        category_id=category_id,
        item_type=item_type,
        is_active=is_active,
        low_stock_only=low_stock_only,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.build(
        [ItemListOut.model_validate(i) for i in items],
        total=total, page=page, limit=limit,
    )


@router.get("/items/{item_id}", summary="Get an item by ID")
async def get_item(
    item_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[ItemOut]:
    item = await inventory_service.get_item(db, item_id)
    return SuccessResponse(data=ItemOut.model_validate(item))


@router.patch("/items/{item_id}", summary="Partially update an item")
async def update_item(
    item_id: int, body: ItemUpdate, db: DbDep, current_user: WriteDep
) -> SuccessResponse[ItemOut]:
    item = await inventory_service.update_item(db, item_id, body, updated_by=current_user.id)
    await db.commit()
    await db.refresh(item)
    return SuccessResponse(data=ItemOut.model_validate(item))


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete an item",
)
async def delete_item(
    item_id: int, db: DbDep, current_user: DeleteDep
) -> SuccessResponse[None]:
    await inventory_service.delete_item(db, item_id, deleted_by=current_user.id)
    await db.commit()
    return SuccessResponse(data=None)


# ── Stock adjustment ──────────────────────────────────────────────────────────

@router.post(
    "/items/{item_id}/adjust",
    status_code=status.HTTP_201_CREATED,
    summary="Manual stock adjustment (positive=add, negative=remove)",
)
async def adjust_stock(
    item_id: int,
    body: StockAdjustmentCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[StockMovementOut]:
    # Ensure path param and body agree
    body.item_id = item_id
    movement = await inventory_service.adjust_stock(
        db, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(movement)
    return SuccessResponse(data=StockMovementOut.model_validate(movement))


# ── Stock movement history ────────────────────────────────────────────────────

@router.get(
    "/items/{item_id}/stock",
    summary="Stock movement history for an item",
)
async def list_movements(
    item_id: int,
    db: DbDep,
    _: ReadDep,
    movement_type: MovementType | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[StockMovementOut]:
    movements, total = await inventory_service.list_movements(
        db, item_id, movement_type=movement_type, page=page, limit=limit
    )
    return PaginatedResponse.build(
        [StockMovementOut.model_validate(m) for m in movements],
        total=total, page=page, limit=limit,
    )
