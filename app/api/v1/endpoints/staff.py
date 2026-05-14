"""
Staff / Payroll endpoints.

Staff routes:
  POST   /staff                              — create staff profile
  GET    /staff                              — list staff
  GET    /staff/{id}                         — staff detail
  PATCH  /staff/{id}                         — update staff profile
  DELETE /staff/{id}                         — deactivate staff

Salary structure routes:
  POST   /staff/{id}/salary-structures       — add salary structure
  GET    /staff/{id}/salary-structures       — list salary structures

Attendance routes:
  POST   /staff/attendance                   — record attendance (single)
  POST   /staff/attendance/bulk             — record attendance (bulk, one date many staff)
  GET    /staff/{id}/attendance             — list attendance for a staff member
  PATCH  /staff/{id}/attendance/{date}      — update an attendance record

Payroll routes:
  POST   /staff/payments                     — disburse salary
  GET    /staff/{id}/payments               — list salary payments

Advance routes:
  POST   /staff/advances                     — give an advance
  GET    /staff/{id}/advances               — list advances for a staff member

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
from app.models.enums import CompensationType
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.staff import (
    AdvanceCreate,
    AdvanceOut,
    AttendanceBulkCreate,
    AttendanceCreate,
    AttendanceOut,
    AttendanceUpdate,
    SalaryStructureCreate,
    SalaryStructureOut,
    SortOrder,
    StaffCreate,
    StaffListOut,
    StaffOut,
    StaffPaymentCreate,
    StaffPaymentOut,
    StaffSortField,
    StaffUpdate,
)
from app.services import staff_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("staff", "read"))]
WriteDep = Annotated[User, Depends(require_permission("staff", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("staff", "delete"))]


# ── Staff ─────────────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff profile",
)
async def create_staff(
    body: StaffCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[StaffOut]:
    staff = await staff_service.create_staff(db, body, created_by=current_user.id)
    await db.commit()
    await db.refresh(staff)
    return SuccessResponse(data=StaffOut.model_validate(staff))


@router.get("", summary="List staff")
async def list_staff(
    db: DbDep,
    _: ReadDep,
    compensation_type: Annotated[CompensationType | None, Query()] = None,
    department: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = True,
    search: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=1000)] = 20,
    sort_by: Annotated[StaffSortField, Query()] = "name",
    sort_order: Annotated[SortOrder, Query()] = "asc",
) -> PaginatedResponse[StaffListOut]:
    staff_list, total = await staff_service.list_staff(
        db,
        compensation_type=compensation_type,
        department=department,
        is_active=is_active,
        search=search,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.build(
        [StaffListOut.model_validate(s) for s in staff_list],
        total=total, page=page, limit=limit,
    )


@router.get("/{staff_id}", summary="Get staff detail")
async def get_staff(
    staff_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[StaffOut]:
    staff = await staff_service.get_staff(db, staff_id)
    return SuccessResponse(data=StaffOut.model_validate(staff))


@router.patch("/{staff_id}", summary="Update staff profile")
async def update_staff(
    staff_id: int,
    body: StaffUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[StaffOut]:
    staff = await staff_service.update_staff(db, staff_id, body, updated_by=current_user.id)
    await db.commit()
    await db.refresh(staff)
    return SuccessResponse(data=StaffOut.model_validate(staff))


@router.delete(
    "/{staff_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Deactivate a staff member",
)
async def deactivate_staff(
    staff_id: int,
    db: DbDep,
    current_user: DeleteDep,
) -> None:
    await staff_service.deactivate_staff(db, staff_id, deactivated_by=current_user.id)
    await db.commit()


# ── Salary Structure ──────────────────────────────────────────────────────────

@router.post(
    "/{staff_id}/salary-structures",
    status_code=status.HTTP_201_CREATED,
    summary="Add a salary structure for a staff member",
)
async def add_salary_structure(
    staff_id: int,
    body: SalaryStructureCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[SalaryStructureOut]:
    structure = await staff_service.add_salary_structure(
        db, staff_id, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(structure)
    return SuccessResponse(data=SalaryStructureOut.model_validate(structure))


@router.get(
    "/{staff_id}/salary-structures",
    summary="List salary structures for a staff member",
)
async def list_salary_structures(
    staff_id: int, db: DbDep, _: ReadDep
) -> SuccessResponse[list[SalaryStructureOut]]:
    structures = await staff_service.list_salary_structures(db, staff_id)
    return SuccessResponse(
        data=[SalaryStructureOut.model_validate(s) for s in structures]
    )


# ── Attendance ────────────────────────────────────────────────────────────────

@router.post(
    "/attendance",
    status_code=status.HTTP_201_CREATED,
    summary="Record attendance for a single staff member",
)
async def record_attendance(
    body: AttendanceCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[AttendanceOut]:
    attendance = await staff_service.record_attendance(
        db, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(attendance)
    return SuccessResponse(data=AttendanceOut.model_validate(attendance))


@router.post(
    "/attendance/bulk",
    status_code=status.HTTP_201_CREATED,
    summary="Record attendance for multiple staff on the same date",
)
async def record_attendance_bulk(
    body: AttendanceBulkCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[list[AttendanceOut]]:
    records = await staff_service.record_attendance_bulk(
        db, body, created_by=current_user.id
    )
    await db.commit()
    return SuccessResponse(
        data=[AttendanceOut.model_validate(r) for r in records]
    )


@router.get("/{staff_id}/attendance", summary="List attendance for a staff member")
async def list_attendance(
    staff_id: int,
    db: DbDep,
    _: ReadDep,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PaginatedResponse[AttendanceOut]:
    records, total = await staff_service.list_attendance(
        db, staff_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
    )
    return PaginatedResponse.build(
        [AttendanceOut.model_validate(r) for r in records],
        total=total, page=page, limit=limit,
    )


@router.patch(
    "/{staff_id}/attendance/{att_date}",
    summary="Update an attendance record",
)
async def update_attendance(
    staff_id: int,
    att_date: date,
    body: AttendanceUpdate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[AttendanceOut]:
    attendance = await staff_service.update_attendance(db, staff_id, att_date, body, updated_by=current_user.id)
    await db.commit()
    await db.refresh(attendance)
    return SuccessResponse(data=AttendanceOut.model_validate(attendance))


# ── Payroll ───────────────────────────────────────────────────────────────────

@router.post(
    "/payments",
    status_code=status.HTTP_201_CREATED,
    summary="Disburse monthly salary for a staff member",
)
async def disburse_salary(
    body: StaffPaymentCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[StaffPaymentOut]:
    payment = await staff_service.disburse_salary(
        db, body, created_by=current_user.id
    )
    await db.commit()
    await db.refresh(payment)
    return SuccessResponse(data=StaffPaymentOut.model_validate(payment))


@router.get("/{staff_id}/payments", summary="List salary payments for a staff member")
async def list_payments(
    staff_id: int,
    db: DbDep,
    _: ReadDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> PaginatedResponse[StaffPaymentOut]:
    payments, total = await staff_service.list_payments(
        db, staff_id, page=page, limit=limit
    )
    return PaginatedResponse.build(
        [StaffPaymentOut.model_validate(p) for p in payments],
        total=total, page=page, limit=limit,
    )


# ── Advances ──────────────────────────────────────────────────────────────────

@router.post(
    "/advances",
    status_code=status.HTTP_201_CREATED,
    summary="Record a salary advance given to a staff member",
)
async def give_advance(
    body: AdvanceCreate,
    db: DbDep,
    current_user: WriteDep,
) -> SuccessResponse[AdvanceOut]:
    advance = await staff_service.give_advance(db, body, created_by=current_user.id)
    await db.commit()
    await db.refresh(advance)
    return SuccessResponse(data=AdvanceOut.model_validate(advance))


@router.get("/{staff_id}/advances", summary="List advances for a staff member")
async def list_advances(
    staff_id: int,
    db: DbDep,
    _: ReadDep,
    is_deducted: Annotated[bool | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[AdvanceOut]:
    advances, total = await staff_service.list_advances(
        db, staff_id,
        is_deducted=is_deducted,
        page=page,
        limit=limit,
    )
    return PaginatedResponse.build(
        [AdvanceOut.model_validate(a) for a in advances],
        total=total, page=page, limit=limit,
    )
