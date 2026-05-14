from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """
    Generic async CRUD repository.

    Subclasses set `model` at the class level:

        class SupplierRepository(BaseRepository[Supplier]):
            model = Supplier
    """

    model: type[ModelT]

    async def get(self, db: AsyncSession, id: int) -> ModelT | None:
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_or_404(self, db: AsyncSession, id: int) -> ModelT:
        obj = await self.get(db, id)
        if obj is None:
            raise NotFoundException(
                f"{self.model.__name__} with id={id} not found.",
                code="NOT_FOUND",
            )
        return obj

    async def list(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 20,
        filters: list[Any] | None = None,
    ) -> tuple[list[ModelT], int]:
        """Returns (items, total_count) for pagination."""
        stmt = select(self.model)
        if filters:
            stmt = stmt.where(*filters)

        total_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = total_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def create(self, db: AsyncSession, obj_in: dict[str, Any]) -> ModelT:
        db_obj = self.model(**obj_in)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self, db: AsyncSession, db_obj: ModelT, obj_in: dict[str, Any]
    ) -> ModelT:
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def soft_delete(self, db: AsyncSession, id: int) -> None:
        """Sets is_active=False rather than physically deleting the row."""
        obj = await self.get_or_404(db, id)
        obj.is_active = False  # type: ignore[attr-defined]
        db.add(obj)
        await db.flush()
