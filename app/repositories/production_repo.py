"""
Repository for the Production module. Data access only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import ProductionStatus
from app.models.production import (
    ProductionCost,
    ProductionLabor,
    ProductionOrder,
    ProductionOutput,
    ProductionRawMaterial,
)
from app.repositories.base_repo import BaseRepository


class ProductionOrderRepository(BaseRepository[ProductionOrder]):
    model = ProductionOrder

    async def get_with_details(
        self, db: AsyncSession, order_id: int
    ) -> ProductionOrder | None:
        result = await db.execute(
            select(ProductionOrder)
            .options(
                selectinload(ProductionOrder.product_item),
                selectinload(ProductionOrder.raw_materials),
                selectinload(ProductionOrder.labor).selectinload(ProductionLabor.item),
                selectinload(ProductionOrder.costs),
                selectinload(ProductionOrder.outputs),
            )
            .where(ProductionOrder.id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_order_no(
        self, db: AsyncSession, order_no: str
    ) -> ProductionOrder | None:
        result = await db.execute(
            select(ProductionOrder).where(ProductionOrder.order_no == order_no)
        )
        return result.scalar_one_or_none()

    async def list_orders(
        self,
        db: AsyncSession,
        *,
        status: ProductionStatus | None = None,
        product_item_id: int | None = None,
        from_date=None,
        to_date=None,
        skip: int = 0,
        limit: int = 20,
        sort_by: Literal["created_at", "start_date", "end_date", "total_cost"] = "created_at",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> tuple[list[ProductionOrder], int]:
        conditions = []
        if status is not None:
            conditions.append(ProductionOrder.status == status)
        if product_item_id is not None:
            conditions.append(ProductionOrder.product_item_id == product_item_id)
        if from_date is not None:
            conditions.append(ProductionOrder.start_date >= from_date)
        if to_date is not None:
            conditions.append(ProductionOrder.end_date <= to_date)

        stmt = select(ProductionOrder).options(selectinload(ProductionOrder.product_item))
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "created_at": ProductionOrder.created_at,
            "start_date": ProductionOrder.start_date,
            "end_date": ProductionOrder.end_date,
            "total_cost": ProductionOrder.total_cost,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def update_costs(
        self,
        db: AsyncSession,
        order: ProductionOrder,
        *,
        total_material_cost: Decimal,
        total_labor_cost: Decimal,
        total_other_cost: Decimal,
    ) -> None:
        order.total_material_cost = total_material_cost
        order.total_labor_cost = total_labor_cost
        order.total_other_cost = total_other_cost
        db.add(order)

    async def set_status(
        self,
        db: AsyncSession,
        order: ProductionOrder,
        *,
        status: ProductionStatus,
    ) -> None:
        order.status = status
        db.add(order)


class ProductionRawMaterialRepository:

    async def bulk_create(
        self, db: AsyncSession, items: list[dict[str, Any]]
    ) -> list[ProductionRawMaterial]:
        objs = [ProductionRawMaterial(**item) for item in items]
        db.add_all(objs)
        await db.flush()
        return objs

    async def update_used(
        self,
        db: AsyncSession,
        material: ProductionRawMaterial,
        used_quantity: Decimal,
        total_cost: Decimal,
    ) -> None:
        material.used_quantity = used_quantity
        material.total_cost = total_cost
        db.add(material)


class ProductionLaborRepository:

    async def bulk_create(
        self, db: AsyncSession, items: list[dict[str, Any]]
    ) -> list[ProductionLabor]:
        objs = [ProductionLabor(**item) for item in items]
        db.add_all(objs)
        await db.flush()
        return objs

    async def create(
        self, db: AsyncSession, data: dict[str, Any]
    ) -> ProductionLabor:
        obj = ProductionLabor(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj


class ProductionCostRepository:

    async def bulk_create(
        self, db: AsyncSession, items: list[dict[str, Any]]
    ) -> list[ProductionCost]:
        objs = [ProductionCost(**item) for item in items]
        db.add_all(objs)
        await db.flush()
        return objs

    async def create(
        self, db: AsyncSession, data: dict[str, Any]
    ) -> ProductionCost:
        obj = ProductionCost(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj


class ProductionOutputRepository:

    async def create(
        self, db: AsyncSession, data: dict[str, Any]
    ) -> ProductionOutput:
        obj = ProductionOutput(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def list_for_order(
        self, db: AsyncSession, order_id: int
    ) -> list[ProductionOutput]:
        from sqlalchemy import select
        result = await db.execute(
            select(ProductionOutput)
            .where(ProductionOutput.order_id == order_id)
            .order_by(ProductionOutput.produced_at)
        )
        return list(result.scalars().all())
