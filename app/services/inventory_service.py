"""
Business logic for the Inventory module.

Domain rules:
─────────────────────────────────────────────────────────────────────────────
STOCK MODEL
  item.current_stock — absolute quantity on hand (can be 0, never negative
                        in normal flow; negative only via explicit adjustment
                        with a note, left to operator discretion).

STOCK MUTATIONS
  All mutations go through _apply_stock_change():
    1. SELECT FOR UPDATE on the item row.
    2. Compute new_stock = current_stock + delta (Python only).
    3. Write new_stock via repo.apply_stock_update() (pure DB write-back).
    4. Append a StockMovement record via movement_repo.record().
    5. db.flush() inside record() — both writes land before caller commits.

  Callers from other services (purchase_service, sale_service, etc.) use the
  public helpers:
    record_purchase_in()   — purchase_in movement, +quantity
    record_sale_out()      — sale_out movement, -quantity
    record_return_in()     — return_in movement, +quantity
    record_return_out()    — return_out movement, -quantity
    record_production_in() — production_in movement, +quantity
    record_production_out()— production_out movement, -quantity

  Manual operator adjustments use adjust_stock() (movement_type=adjustment).

UNIQUENESS
  Unit names and abbreviations are unique (case-insensitive).
  Item SKUs are unique when provided.
  Category names are unique per parent (enforced by DB unique constraint).

SOFT DELETE
  Items: is_active=False. Units and Categories: same.
  Deleted items still appear in StockMovement history (RESTRICT FK).
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.models.enums import AuditAction, ItemType, MovementType
from app.models.inventory import Category, Item, StockMovement, Unit
from app.services import audit_service
from app.repositories.inventory_repo import (
    CategoryRepository,
    ItemRepository,
    StockMovementRepository,
    UnitRepository,
)
from app.schemas.inventory import (
    CategoryCreate,
    CategoryUpdate,
    ItemCreate,
    ItemUpdate,
    StockAdjustmentCreate,
    StockMovementOut,
)

_unit_repo = UnitRepository()
_cat_repo = CategoryRepository()
_item_repo = ItemRepository()
_move_repo = StockMovementRepository()


# ── Internal stock mutation helper ────────────────────────────────────────────

async def _apply_stock_change(
    db: AsyncSession,
    item_id: int,
    *,
    delta: Decimal,
    movement_type: MovementType,
    reference_type: str | None = None,
    reference_id: int | None = None,
    note: str | None = None,
    created_by: int | None = None,
) -> StockMovement:
    """
    Lock item row, apply delta, write movement record.
    Returns the created StockMovement.
    Caller must commit.
    """
    item = await _item_repo.get_with_lock(db, item_id)
    if item is None or not item.is_active:
        raise NotFoundException(f"Item {item_id} not found.")

    stock_before = item.current_stock
    new_stock = stock_before + delta
    await _item_repo.apply_stock_update(db, item, new_stock=new_stock)

    return await _move_repo.record(
        db,
        item_id=item_id,
        movement_type=movement_type,
        quantity=delta,
        stock_before=stock_before,
        stock_after=new_stock,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        moved_at=datetime.now(timezone.utc),
        created_by=created_by,
    )


# ── Units ─────────────────────────────────────────────────────────────────────

async def create_unit(db: AsyncSession, body: "UnitCreate", *, created_by: int | None = None) -> Unit:  # noqa: F821
    if await _unit_repo.get_by_name(db, body.name):
        raise ConflictException("A unit with this name already exists.", field="name")
    if await _unit_repo.get_by_abbreviation(db, body.abbreviation):
        raise ConflictException(
            "A unit with this abbreviation already exists.", field="abbreviation"
        )
    unit = await _unit_repo.create(db, {"name": body.name, "abbreviation": body.abbreviation})
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="units", record_id=unit.id,
        new_values=audit_service.snapshot(unit),
    )
    return unit


async def list_units(
    db: AsyncSession, *, is_active: bool | None = True, page: int = 1, limit: int = 100
) -> tuple[list[Unit], int]:
    return await _unit_repo.list_units(
        db, is_active=is_active, skip=(page - 1) * limit, limit=limit
    )


async def get_unit(db: AsyncSession, unit_id: int) -> Unit:
    unit = await _unit_repo.get_or_404(db, unit_id)
    if not unit.is_active:
        raise NotFoundException(f"Unit {unit_id} not found.")
    return unit


async def update_unit(db: AsyncSession, unit_id: int, body: "UnitUpdate", *, updated_by: int | None = None) -> Unit:  # noqa: F821
    unit = await _unit_repo.get_or_404(db, unit_id)
    if not unit.is_active:
        raise NotFoundException(f"Unit {unit_id} not found.")
    old = audit_service.snapshot(unit)
    patch = body.model_dump(exclude_unset=True)
    if "name" in patch:
        existing = await _unit_repo.get_by_name(db, patch["name"])
        if existing and existing.id != unit_id:
            raise ConflictException("A unit with this name already exists.", field="name")
    if "abbreviation" in patch:
        existing = await _unit_repo.get_by_abbreviation(db, patch["abbreviation"])
        if existing and existing.id != unit_id:
            raise ConflictException(
                "A unit with this abbreviation already exists.", field="abbreviation"
            )
    updated = await _unit_repo.update(db, unit, patch)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="units", record_id=unit_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return updated


async def delete_unit(db: AsyncSession, unit_id: int, *, deleted_by: int | None = None) -> None:
    unit = await _unit_repo.get_or_404(db, unit_id)
    if not unit.is_active:
        raise NotFoundException(f"Unit {unit_id} not found.")
    old = audit_service.snapshot(unit)
    unit.is_active = False
    db.add(unit)
    await db.flush()
    await audit_service.log(
        db, user_id=deleted_by, action=AuditAction.DELETE,
        table_name="units", record_id=unit_id,
        old_values=old,
    )


# ── Categories ────────────────────────────────────────────────────────────────

async def create_category(db: AsyncSession, body: CategoryCreate, *, created_by: int | None = None) -> Category:
    if body.parent_id is not None:
        parent = await _cat_repo.get_or_404(db, body.parent_id)
        if not parent.is_active:
            raise NotFoundException(f"Parent category {body.parent_id} not found.")
    cat = await _cat_repo.create(
        db, {"name": body.name, "parent_id": body.parent_id}
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="categories", record_id=cat.id,
        new_values=audit_service.snapshot(cat),
    )
    return cat


async def list_categories(
    db: AsyncSession,
    *,
    parent_id: int | None = None,
    is_active: bool | None = True,
    page: int = 1,
    limit: int = 100,
) -> tuple[list[Category], int]:
    return await _cat_repo.list_categories(
        db,
        parent_id=parent_id,
        is_active=is_active,
        skip=(page - 1) * limit,
        limit=limit,
    )


async def get_category(db: AsyncSession, category_id: int) -> Category:
    cat = await _cat_repo.get_or_404(db, category_id)
    if not cat.is_active:
        raise NotFoundException(f"Category {category_id} not found.")
    return cat


async def update_category(
    db: AsyncSession, category_id: int, body: CategoryUpdate, *, updated_by: int | None = None
) -> Category:
    cat = await _cat_repo.get_or_404(db, category_id)
    if not cat.is_active:
        raise NotFoundException(f"Category {category_id} not found.")
    old = audit_service.snapshot(cat)
    patch = body.model_dump(exclude_unset=True)
    if "parent_id" in patch and patch["parent_id"] is not None:
        if patch["parent_id"] == category_id:
            raise ConflictException("A category cannot be its own parent.")
        parent = await _cat_repo.get_or_404(db, patch["parent_id"])
        if not parent.is_active:
            raise NotFoundException(f"Parent category {patch['parent_id']} not found.")
    updated = await _cat_repo.update(db, cat, patch)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="categories", record_id=category_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return updated


async def delete_category(db: AsyncSession, category_id: int, *, deleted_by: int | None = None) -> None:
    cat = await _cat_repo.get_or_404(db, category_id)
    if not cat.is_active:
        raise NotFoundException(f"Category {category_id} not found.")
    old = audit_service.snapshot(cat)
    cat.is_active = False
    db.add(cat)
    await db.flush()
    await audit_service.log(
        db, user_id=deleted_by, action=AuditAction.DELETE,
        table_name="categories", record_id=category_id,
        old_values=old,
    )


# ── Items ─────────────────────────────────────────────────────────────────────

async def create_item(
    db: AsyncSession, body: ItemCreate, *, created_by: int
) -> Item:
    await _unit_repo.get_or_404(db, body.unit_id)
    if body.category_id is not None:
        await _cat_repo.get_or_404(db, body.category_id)

    item = await _item_repo.create(
        db,
        {
            "name": body.name,
            "sku": None,
            "category_id": body.category_id,
            "unit_id": body.unit_id,
            "item_type": body.item_type,
            "reorder_level": body.reorder_level,
            "sale_price": body.sale_price,
            "purchase_price": body.purchase_price,
            "current_stock": Decimal("0"),
            "created_by": created_by,
        },
    )
    prefix = "PUR" if body.item_type == ItemType.purchased else "PRD"
    item.sku = f"{prefix}-{item.id:05d}"
    await db.flush()

    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="items", record_id=item.id,
        new_values=audit_service.snapshot(item),
    )
    return item


async def get_item(db: AsyncSession, item_id: int) -> Item:
    item = await _item_repo.get_or_404(db, item_id)
    if not item.is_active:
        raise NotFoundException(f"Item {item_id} not found.")
    return item


async def list_items(
    db: AsyncSession,
    *,
    search: str | None = None,
    category_id: int | None = None,
    item_type: ItemType | None = None,
    is_active: bool | None = True,
    low_stock_only: bool = False,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> tuple[list[Item], int]:
    return await _item_repo.list_items(
        db,
        search=search,
        category_id=category_id,
        item_type=item_type,
        is_active=is_active,
        low_stock_only=low_stock_only,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


async def update_item(
    db: AsyncSession, item_id: int, body: ItemUpdate, *, updated_by: int
) -> Item:
    item = await _item_repo.get_or_404(db, item_id)
    if not item.is_active:
        raise NotFoundException(f"Item {item_id} not found.")
    old = audit_service.snapshot(item)
    patch = body.model_dump(exclude_unset=True)
    if "sku" in patch and patch["sku"]:
        existing = await _item_repo.get_by_sku(db, patch["sku"])
        if existing and existing.id != item_id:
            raise ConflictException("An item with this SKU already exists.", field="sku")
    if "unit_id" in patch:
        await _unit_repo.get_or_404(db, patch["unit_id"])
    if "category_id" in patch and patch["category_id"] is not None:
        await _cat_repo.get_or_404(db, patch["category_id"])
    updated = await _item_repo.update(db, item, patch)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="items", record_id=item_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return updated


async def delete_item(db: AsyncSession, item_id: int, *, deleted_by: int) -> None:
    item = await _item_repo.get_or_404(db, item_id)
    if not item.is_active:
        raise NotFoundException(f"Item {item_id} not found.")
    old = audit_service.snapshot(item)
    item.is_active = False
    db.add(item)
    await db.flush()
    await audit_service.log(
        db, user_id=deleted_by, action=AuditAction.DELETE,
        table_name="items", record_id=item_id,
        old_values=old,
    )


# ── Stock movements ───────────────────────────────────────────────────────────

async def adjust_stock(
    db: AsyncSession,
    body: StockAdjustmentCreate,
    *,
    created_by: int,
) -> StockMovement:
    """Manual stock adjustment by an operator."""
    movement = await _apply_stock_change(
        db,
        body.item_id,
        delta=body.quantity,
        movement_type=MovementType.adjustment,
        note=body.note,
        created_by=created_by,
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.UPDATE,
        table_name="items", record_id=body.item_id,
        new_values={
            "adjustment_quantity": str(body.quantity),
            "note": body.note,
            "movement_id": movement.id,
        },
    )
    return movement


async def list_movements(
    db: AsyncSession,
    item_id: int,
    *,
    movement_type: MovementType | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[StockMovement], int]:
    # Verify item exists (active or not — history is always accessible)
    await _item_repo.get_or_404(db, item_id)
    return await _move_repo.list_for_item(
        db,
        item_id,
        movement_type=movement_type,
        skip=(page - 1) * limit,
        limit=limit,
    )


# ── Public hooks for other services ──────────────────────────────────────────

async def update_purchase_price(
    db: AsyncSession,
    item_id: int,
    new_price: Decimal,
) -> None:
    """Update the cached purchase_price on an inventory item after a confirmed purchase."""
    from app.repositories.inventory_repo import ItemRepository
    item = await ItemRepository().get_or_404(db, item_id)
    item.purchase_price = new_price
    db.add(item)


async def record_purchase_in(
    db: AsyncSession,
    item_id: int,
    quantity: Decimal,
    *,
    reference_id: int,
    created_by: int | None = None,
) -> StockMovement:
    return await _apply_stock_change(
        db, item_id,
        delta=+quantity,
        movement_type=MovementType.purchase_in,
        reference_type="purchase",
        reference_id=reference_id,
        created_by=created_by,
    )


async def record_sale_out(
    db: AsyncSession,
    item_id: int,
    quantity: Decimal,
    *,
    reference_id: int,
    created_by: int | None = None,
) -> StockMovement:
    return await _apply_stock_change(
        db, item_id,
        delta=-quantity,
        movement_type=MovementType.sale_out,
        reference_type="sale",
        reference_id=reference_id,
        created_by=created_by,
    )


async def record_return_in(
    db: AsyncSession,
    item_id: int,
    quantity: Decimal,
    *,
    reference_id: int,
    created_by: int | None = None,
) -> StockMovement:
    return await _apply_stock_change(
        db, item_id,
        delta=+quantity,
        movement_type=MovementType.return_in,
        reference_type="return",
        reference_id=reference_id,
        created_by=created_by,
    )


async def record_return_out(
    db: AsyncSession,
    item_id: int,
    quantity: Decimal,
    *,
    reference_id: int,
    created_by: int | None = None,
) -> StockMovement:
    return await _apply_stock_change(
        db, item_id,
        delta=-quantity,
        movement_type=MovementType.return_out,
        reference_type="return",
        reference_id=reference_id,
        created_by=created_by,
    )


async def record_production_in(
    db: AsyncSession,
    item_id: int,
    quantity: Decimal,
    *,
    reference_id: int,
    created_by: int | None = None,
) -> StockMovement:
    return await _apply_stock_change(
        db, item_id,
        delta=+quantity,
        movement_type=MovementType.production_in,
        reference_type="production",
        reference_id=reference_id,
        created_by=created_by,
    )


async def record_production_out(
    db: AsyncSession,
    item_id: int,
    quantity: Decimal,
    *,
    reference_id: int,
    created_by: int | None = None,
) -> StockMovement:
    return await _apply_stock_change(
        db, item_id,
        delta=-quantity,
        movement_type=MovementType.production_out,
        reference_type="production",
        reference_id=reference_id,
        created_by=created_by,
    )
