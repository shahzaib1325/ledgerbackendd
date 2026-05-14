"""
Repository for the Staff / Payroll module. Data access only.

Entities:
  StaffRepository          — staff CRUD + filtered list
  SalaryStructureRepository — structure per staff, date-ranged lookup
  AttendanceRepository     — daily record, unique per staff+date
  StaffPaymentRepository   — monthly disbursement
  AdvanceRepository        — advance records
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import UniqueConstraint, and_, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AttendanceStatus, CompensationType
from app.models.staff import Advance, Attendance, SalaryStructure, Staff, StaffItem, StaffPayment
from app.repositories.base_repo import BaseRepository


class StaffRepository(BaseRepository[Staff]):
    model = Staff

    async def list_staff(
        self,
        db: AsyncSession,
        *,
        compensation_type: CompensationType | None = None,
        department: str | None = None,
        is_active: bool | None = True,
        search: str | None = None,
        skip: int = 0,
        limit: int = 20,
        sort_by: Literal["name", "join_date", "created_at"] = "name",
        sort_order: Literal["asc", "desc"] = "asc",
    ) -> tuple[list[Staff], int]:
        conditions = []
        if compensation_type is not None:
            conditions.append(Staff.compensation_type == compensation_type)
        if department is not None:
            conditions.append(Staff.department.ilike(f"%{department}%"))
        if is_active is not None:
            conditions.append(Staff.is_active == is_active)
        if search is not None:
            conditions.append(
                Staff.name.ilike(f"%{search}%") | Staff.cnic.ilike(f"%{search}%")
            )

        stmt = select(Staff)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        sort_col = {
            "name": Staff.name,
            "join_date": Staff.join_date,
            "created_at": Staff.created_at,
        }[sort_by]
        stmt = stmt.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def get_by_cnic(self, db: AsyncSession, cnic: str) -> Staff | None:
        result = await db.execute(select(Staff).where(Staff.cnic == cnic))
        return result.scalar_one_or_none()


class SalaryStructureRepository:

    async def create(
        self,
        db: AsyncSession,
        data: dict[str, Any],
    ) -> SalaryStructure:
        obj = SalaryStructure(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def get_active_for_staff(
        self, db: AsyncSession, staff_id: int, on_date: date
    ) -> SalaryStructure | None:
        """Return the salary structure active on a given date."""
        result = await db.execute(
            select(SalaryStructure)
            .where(
                and_(
                    SalaryStructure.staff_id == staff_id,
                    SalaryStructure.effective_from <= on_date,
                    (SalaryStructure.effective_to == None) | (SalaryStructure.effective_to >= on_date),  # noqa: E711
                )
            )
            .order_by(desc(SalaryStructure.effective_from))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_staff(
        self, db: AsyncSession, staff_id: int
    ) -> list[SalaryStructure]:
        result = await db.execute(
            select(SalaryStructure)
            .where(SalaryStructure.staff_id == staff_id)
            .order_by(desc(SalaryStructure.effective_from))
        )
        return list(result.scalars().all())

    async def close_current(
        self, db: AsyncSession, staff_id: int, close_date: date
    ) -> None:
        """Set effective_to on the currently-open structure (if any)."""
        current = await self.get_active_for_staff(db, staff_id, close_date)
        if current and current.effective_to is None:
            current.effective_to = close_date
            db.add(current)
            await db.flush()


class AttendanceRepository:

    async def upsert(
        self,
        db: AsyncSession,
        *,
        staff_id: int,
        att_date: date,
        status: AttendanceStatus,
        notes: str | None,
        created_by: int | None,
    ) -> Attendance:
        """Insert or update attendance for a staff member on a given date."""
        existing = await self.get_for_staff_date(db, staff_id, att_date)
        if existing:
            existing.status = status
            existing.notes = notes
            db.add(existing)
            await db.flush()
            await db.refresh(existing)
            return existing

        obj = Attendance(
            staff_id=staff_id,
            date=att_date,
            status=status,
            notes=notes,
            created_by=created_by,
        )
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def get_for_staff_date(
        self, db: AsyncSession, staff_id: int, att_date: date
    ) -> Attendance | None:
        result = await db.execute(
            select(Attendance).where(
                and_(Attendance.staff_id == staff_id, Attendance.date == att_date)
            )
        )
        return result.scalar_one_or_none()

    async def list_for_staff(
        self,
        db: AsyncSession,
        staff_id: int,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Attendance], int]:
        conditions = [Attendance.staff_id == staff_id]
        if from_date:
            conditions.append(Attendance.date >= from_date)
        if to_date:
            conditions.append(Attendance.date <= to_date)

        stmt = select(Attendance).where(and_(*conditions)).order_by(desc(Attendance.date))

        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def list_for_date(
        self, db: AsyncSession, att_date: date
    ) -> list[Attendance]:
        result = await db.execute(
            select(Attendance).where(Attendance.date == att_date).order_by(Attendance.staff_id)
        )
        return list(result.scalars().all())


class StaffPaymentRepository:

    async def get_for_month(
        self, db: AsyncSession, staff_id: int, month: int, year: int
    ) -> StaffPayment | None:
        result = await db.execute(
            select(StaffPayment).where(
                and_(
                    StaffPayment.staff_id == staff_id,
                    StaffPayment.payment_month == month,
                    StaffPayment.payment_year == year,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, db: AsyncSession, data: dict[str, Any]
    ) -> StaffPayment:
        obj = StaffPayment(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def list_for_staff(
        self,
        db: AsyncSession,
        staff_id: int,
        *,
        skip: int = 0,
        limit: int = 24,
    ) -> tuple[list[StaffPayment], int]:
        stmt = (
            select(StaffPayment)
            .where(StaffPayment.staff_id == staff_id)
            .order_by(desc(StaffPayment.payment_year), desc(StaffPayment.payment_month))
        )
        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()
        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total


class AdvanceRepository:

    async def create(
        self, db: AsyncSession, data: dict[str, Any]
    ) -> Advance:
        obj = Advance(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def list_for_staff(
        self,
        db: AsyncSession,
        staff_id: int,
        *,
        is_deducted: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Advance], int]:
        conditions = [Advance.staff_id == staff_id]
        if is_deducted is not None:
            conditions.append(Advance.is_deducted == is_deducted)

        stmt = (
            select(Advance)
            .where(and_(*conditions))
            .order_by(desc(Advance.paid_at))
        )
        count_result = await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total: int = count_result.scalar_one()
        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def get_pending_for_month(
        self, db: AsyncSession, staff_id: int, month: int, year: int
    ) -> list[Advance]:
        """Return undeducted advances scheduled for a given month/year."""
        result = await db.execute(
            select(Advance).where(
                and_(
                    Advance.staff_id == staff_id,
                    Advance.deduct_from_month == month,
                    Advance.deduct_from_year == year,
                    Advance.is_deducted == False,  # noqa: E712
                )
            )
        )
        return list(result.scalars().all())

    async def mark_deducted(self, db: AsyncSession, advance: Advance) -> None:
        advance.is_deducted = True
        db.add(advance)
        await db.flush()
