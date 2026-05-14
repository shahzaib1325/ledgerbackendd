"""
Repository for the Inventory module.

Responsibility: data access only.

Entities managed:
  UnitRepository      — CRUD for units of measure
  CategoryRepository  — CRUD for item categories (self-referential tree)
  ItemRepository      — CRUD + filtered list + stock lock
  StockMovementRepository — append-only movement log + paginated history

Stock mutation rule:
  item.current_stock is updated by the Service, which passes the
  pre-computed new stock value to apply_stock_update(). The repository
  only writes; no arithmetic here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MovementType
from app.models.inventory import Category, Item, StockMovement, Unit
from app.repositories.base_repo import BaseRepository


class UnitRepository(BaseRepository[Unit]):
    model = Unit

    async def get_by_name(self, db: AsyncSession, name: str) -> Unit | None:
        result = await db.execute(
            select(Unit).where(func.lower(Unit.name) == name.lower().strip())
        )
        return result.scalar_one_or_none()

    async def get_by_abbreviation(self, db: AsyncSession, abbr: str) -> Unit | None:
        result = await db.execute(
            select(Unit).where(func.lower(Unit.abbreviation) == abbr.lower().strip())
        )
        return result.scalar_one_or_none()

    async def list_units(
        self,
        db: AsyncSession,
        *,
        is_active: bool | None = True,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Unit], int]:
        stmt = select(Unit)
        if is_active is not None:
            stmt = stmt.where(Unit.is_active == is_active)
        stmt = stmt.order_by(asc(Unit.name))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total


class CategoryRepository(BaseRepository[Category]):
    model = Category

    async def list_categories(
        self,
        db: AsyncSession,
        *,
        parent_id: int | None = None,
        is_active: bool | None = True,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Category], int]:
        conditions = []
        if is_active is not None:
            conditions.append(Category.is_active == is_active)
        if parent_id is not None:
            conditions.append(Category.parent_id == parent_id)

        stmt = select(Category)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(asc(Category.name))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total


class ItemRepository(BaseRepository[Item]):
    model = Item

    async def get_with_lock(self, db: AsyncSession, item_id: int) -> Item | None:
        """SELECT FOR UPDATE — use inside an open transaction for stock mutations."""
        result = await db.execute(
            select(Item).where(Item.id == item_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def apply_stock_update(
        self,
        db: AsyncSession,
        item: Item,
        *,
        new_stock: Decimal,
    ) -> None:
        """Persist pre-computed stock value. Service owns all arithmetic."""
        item.current_stock = new_stock
        db.add(item)

    async def list_items(
        self,
        db: AsyncSession,
        *,
        search: str | None = None,
        category_id: int | None = None,
        item_type=None,
        is_active: bool | None = True,
        low_stock_only: bool = False,
        skip: int = 0,
        limit: int = 20,
        sort_by: Literal["name", "current_stock", "sale_price", "created_at"] = "name",
        sort_order: Literal["asc", "desc"] = "asc",
    ) -> tuple[list[Item], int]:
        conditions = []
        if search:
            conditions.append(Item.name.ilike(f"%{search}%"))
        if category_id is not None:
            conditions.append(Item.category_id == category_id)
        if item_type is not None:
            conditions.append(Item.item_type == item_type)
        if is_active is not None:
            conditions.append(Item.is_active == is_active)
        if low_stock_only:
            # reorder_level > 0 and current_stock <= reorder_level
            conditions.append(Item.reorder_level > 0)
            conditions.append(Item.current_stock <= Item.reorder_level)

        stmt = select(Item)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "name": Item.name,
            "current_stock": Item.current_stock,
            "sale_price": Item.sale_price,
            "created_at": Item.created_at,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def get_by_sku(self, db: AsyncSession, sku: str) -> Item | None:
        result = await db.execute(select(Item).where(Item.sku == sku))
        return result.scalar_one_or_none()


class StockMovementRepository:

    async def record(
        self,
        db: AsyncSession,
        *,
        item_id: int,
        movement_type: MovementType,
        quantity: Decimal,
        stock_before: Decimal,
        stock_after: Decimal,
        reference_type: str | None,
        reference_id: int | None,
        note: str | None,
        moved_at: datetime,
        created_by: int | None,
    ) -> StockMovement:
        """Append a stock movement record. No stock mutation here."""
        movement = StockMovement(
            item_id=item_id,
            movement_type=movement_type,
            quantity=quantity,
            stock_before=stock_before,
            stock_after=stock_after,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            moved_at=moved_at,
            created_by=created_by,
        )
        db.add(movement)
        await db.flush()
        await db.refresh(movement)
        return movement

    async def list_for_item(
        self,
        db: AsyncSession,
        item_id: int,
        *,
        movement_type: MovementType | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[StockMovement], int]:
        conditions = [StockMovement.item_id == item_id]
        if movement_type is not None:
            conditions.append(StockMovement.movement_type == movement_type)

        stmt = (
            select(StockMovement)
            .where(and_(*conditions))
            .order_by(desc(StockMovement.moved_at))
        )

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total
