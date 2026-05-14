"""
Business logic for the Staff / Payroll module.

Domain rules:
─────────────────────────────────────────────────────────────────────────────
STAFF:
  - Unique CNIC (when provided).
  - Soft-delete only (is_active=False).

SALARY STRUCTURE:
  - Each staff member can have multiple date-ranged salary structures.
  - Creating a new structure auto-closes the current open one (effective_to = new effective_from - 1 day).
  - Structures must not overlap.

ATTENDANCE:
  - One record per staff per date (upsert: re-recording overwrites).
  - Bulk recording allowed for a single date across multiple staff.

STAFF PAYMENT (monthly salary):
  - One payment per staff per month/year (unique constraint enforced at DB level).
  - net_salary = gross_salary + total_allowances − total_deductions − advance_deduction.
  - If account_id is provided → records a transaction via transaction_service.
  - Advances scheduled for this month are automatically marked deducted.

ADVANCE:
  - Records a cash advance given to a staff member.
  - advance_deduction in StaffPayment pulls from pending advances for that month.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.enums import AuditAction, CompensationType, PaymentMode, ReferenceType, TransactionType
from app.models.staff import Advance, Attendance, SalaryStructure, Staff, StaffItem, StaffPayment
from app.services import audit_service
from app.repositories.staff_repo import (
    AdvanceRepository,
    AttendanceRepository,
    SalaryStructureRepository,
    StaffPaymentRepository,
    StaffRepository,
)
from app.schemas.staff import (
    AdvanceCreate,
    AttendanceBulkCreate,
    AttendanceCreate,
    AttendanceUpdate,
    SalaryStructureCreate,
    StaffCreate,
    StaffPaymentCreate,
    StaffUpdate,
)

_repo = StaffRepository()
_salary_repo = SalaryStructureRepository()
_att_repo = AttendanceRepository()
_pay_repo = StaffPaymentRepository()
_adv_repo = AdvanceRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _active_or_404(staff: Staff | None, staff_id: int) -> Staff:
    if staff is None or not staff.is_active:
        raise NotFoundException(f"Staff {staff_id} not found.")
    return staff


# ── Staff CRUD ────────────────────────────────────────────────────────────────

async def create_staff(
    db: AsyncSession,
    body: StaffCreate,
    *,
    created_by: int,
) -> Staff:
    if body.cnic:
        existing = await _repo.get_by_cnic(db, body.cnic)
        if existing:
            raise ConflictException(f"Staff with CNIC '{body.cnic}' already exists.")

    staff = await _repo.create(
        db,
        {
            "name": body.name,
            "phone": body.phone,
            "cnic": body.cnic,
            "address": body.address,
            "join_date": body.join_date,
            "compensation_type": body.compensation_type,
            "salary_period": body.salary_period,
            "designation": body.designation,
            "department": body.department,
            "created_by": created_by,
        },
    )

    # Auto-create initial salary structure for salary-based staff
    if body.compensation_type == CompensationType.salary_based and body.salary_amount:
        structure = SalaryStructure(
            staff_id=staff.id,
            basic_salary=body.salary_amount,
            effective_from=body.join_date,
            created_by=created_by,
        )
        db.add(structure)
        await db.flush()

    # Create item assignments
    for item in body.items:
        db.add(StaffItem(
            staff_id=staff.id,
            item_id=item.item_id,
            rate_per_unit=item.rate_per_unit,
        ))
    if body.items:
        await db.flush()

    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="staff", record_id=staff.id,
        new_values=audit_service.snapshot(staff),
    )
    return await get_staff(db, staff.id)


async def get_staff(db: AsyncSession, staff_id: int) -> Staff:
    result = await db.execute(
        select(Staff)
        .where(Staff.id == staff_id)
        .options(selectinload(Staff.items).selectinload(StaffItem.item))
        .execution_options(populate_existing=True)
    )
    staff = result.scalar_one_or_none()
    if staff is None:
        raise NotFoundException(f"Staff {staff_id} not found.")
    return _active_or_404(staff, staff_id)


async def list_staff(
    db: AsyncSession,
    *,
    compensation_type=None,
    department: str | None = None,
    is_active: bool | None = True,
    search: str | None = None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> tuple[list[Staff], int]:
    return await _repo.list_staff(
        db,
        compensation_type=compensation_type,
        department=department,
        is_active=is_active,
        search=search,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


async def update_staff(
    db: AsyncSession, staff_id: int, body: StaffUpdate, *, updated_by: int
) -> Staff:
    result = await db.execute(
        select(Staff)
        .where(Staff.id == staff_id)
        .options(selectinload(Staff.items).selectinload(StaffItem.item))
        .execution_options(populate_existing=True)
    )
    staff = result.scalar_one_or_none()
    if staff is None:
        raise NotFoundException(f"Staff {staff_id} not found.")
    _active_or_404(staff, staff_id)
    old = audit_service.snapshot(staff)

    patch = body.model_dump(exclude_unset=True, exclude={"items"})
    updated = await _repo.update(db, staff, patch)

    # Replace items when explicitly provided in the update payload
    if body.items is not None:
        for item in staff.items:
            await db.delete(item)
        await db.flush()
        for item in body.items:
            db.add(StaffItem(
                staff_id=staff_id,
                item_id=item.item_id,
                rate_per_unit=item.rate_per_unit,
            ))
        await db.flush()

    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="staff", record_id=staff_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return await get_staff(db, updated.id)


async def deactivate_staff(db: AsyncSession, staff_id: int, *, deactivated_by: int) -> None:
    staff = await _repo.get_or_404(db, staff_id)
    _active_or_404(staff, staff_id)
    old = audit_service.snapshot(staff)
    updated = await _repo.update(db, staff, {"is_active": False})
    await audit_service.log(
        db, user_id=deactivated_by, action=AuditAction.UPDATE,
        table_name="staff", record_id=staff_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )


# ── Salary Structure ──────────────────────────────────────────────────────────

async def add_salary_structure(
    db: AsyncSession,
    staff_id: int,
    body: SalaryStructureCreate,
    *,
    created_by: int,
) -> SalaryStructure:
    staff = await _repo.get_or_404(db, staff_id)
    _active_or_404(staff, staff_id)

    # Close the currently open structure one day before the new one starts
    await _salary_repo.close_current(
        db, staff_id,
        close_date=body.effective_from - timedelta(days=1),
    )

    struct = await _salary_repo.create(
        db,
        {
            "staff_id": staff_id,
            "basic_salary": body.basic_salary,
            "allowances": body.allowances,
            "deductions": body.deductions,
            "effective_from": body.effective_from,
            "effective_to": body.effective_to,
            "created_by": created_by,
        },
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="salary_structures", record_id=struct.id,
        new_values=audit_service.snapshot(struct),
    )
    return struct


async def list_salary_structures(
    db: AsyncSession, staff_id: int
) -> list[SalaryStructure]:
    staff = await _repo.get_or_404(db, staff_id)
    _active_or_404(staff, staff_id)
    return await _salary_repo.list_for_staff(db, staff_id)


# ── Attendance ────────────────────────────────────────────────────────────────

async def record_attendance(
    db: AsyncSession,
    body: AttendanceCreate,
    *,
    created_by: int,
) -> Attendance:
    staff = await _repo.get_or_404(db, body.staff_id)
    _active_or_404(staff, body.staff_id)

    existing = await _att_repo.get_for_staff_date(db, body.staff_id, body.date)
    action = AuditAction.UPDATE if existing else AuditAction.CREATE
    old = audit_service.snapshot(existing) if existing else None

    att = await _att_repo.upsert(
        db,
        staff_id=body.staff_id,
        att_date=body.date,
        status=body.status,
        notes=body.notes,
        created_by=created_by,
    )
    await audit_service.log(
        db, user_id=created_by, action=action,
        table_name="attendance", record_id=att.id,
        old_values=old, new_values=audit_service.snapshot(att),
    )
    return att


async def record_attendance_bulk(
    db: AsyncSession,
    body: AttendanceBulkCreate,
    *,
    created_by: int,
) -> list[Attendance]:
    results = []
    for record in body.records:
        staff = await _repo.get_or_404(db, record.staff_id)
        _active_or_404(staff, record.staff_id)

        existing = await _att_repo.get_for_staff_date(db, record.staff_id, body.date)
        action = AuditAction.UPDATE if existing else AuditAction.CREATE
        old = audit_service.snapshot(existing) if existing else None

        att = await _att_repo.upsert(
            db,
            staff_id=record.staff_id,
            att_date=body.date,
            status=record.status,
            notes=record.notes,
            created_by=created_by,
        )
        await audit_service.log(
            db, user_id=created_by, action=action,
            table_name="attendance", record_id=att.id,
            old_values=old, new_values=audit_service.snapshot(att),
        )
        results.append(att)
    return results


async def update_attendance(
    db: AsyncSession,
    staff_id: int,
    att_date: date,
    body: AttendanceUpdate,
    *,
    updated_by: int,
) -> Attendance:
    existing = await _att_repo.get_for_staff_date(db, staff_id, att_date)
    if existing is None:
        raise NotFoundException(
            f"No attendance record for staff {staff_id} on {att_date}."
        )
    old = audit_service.snapshot(existing)
    existing.status = body.status
    existing.notes = body.notes
    db.add(existing)
    await db.flush()
    await db.refresh(existing)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="attendance", record_id=existing.id,
        old_values=old, new_values=audit_service.snapshot(existing),
    )
    return existing


async def list_attendance(
    db: AsyncSession,
    staff_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[Attendance], int]:
    staff = await _repo.get_or_404(db, staff_id)
    _active_or_404(staff, staff_id)
    return await _att_repo.list_for_staff(
        db, staff_id,
        from_date=from_date,
        to_date=to_date,
        skip=(page - 1) * limit,
        limit=limit,
    )


# ── Salary Payment ────────────────────────────────────────────────────────────

async def disburse_salary(
    db: AsyncSession,
    body: StaffPaymentCreate,
    *,
    created_by: int,
) -> StaffPayment:
    """
    Record monthly salary disbursement for a staff member.

    - Validates no duplicate payment for the same month/year.
    - Computes net_salary = gross + allowances − deductions − advance_deduction.
    - Marks pending advances for this month as deducted.
    - If account_id is supplied → posts a debit transaction via transaction_service.
    """
    staff = await _repo.get_or_404(db, body.staff_id)
    _active_or_404(staff, body.staff_id)

    existing = await _pay_repo.get_for_month(
        db, body.staff_id, body.payment_month, body.payment_year
    )
    if existing:
        raise ConflictException(
            f"Salary for {body.staff_id} for "
            f"{body.payment_month}/{body.payment_year} already disbursed."
        )

    net_salary = (
        body.gross_salary
        + body.total_allowances
        - body.total_deductions
        - body.advance_deduction
    )
    if net_salary < Decimal("0"):
        raise ValidationException(
            "Net salary cannot be negative. Check deduction amounts.",
            field="advance_deduction",
        )

    payment = await _pay_repo.create(
        db,
        {
            "staff_id": body.staff_id,
            "payment_month": body.payment_month,
            "payment_year": body.payment_year,
            "gross_salary": body.gross_salary,
            "total_allowances": body.total_allowances,
            "total_deductions": body.total_deductions,
            "advance_deduction": body.advance_deduction,
            "net_salary": net_salary,
            "payment_mode": body.payment_mode,
            "account_id": body.account_id,
            "paid_at": datetime.now(timezone.utc),
            "notes": body.notes,
            "created_by": created_by,
        },
    )

    # Mark advances for this month as deducted
    pending_advances = await _adv_repo.get_pending_for_month(
        db, body.staff_id, body.payment_month, body.payment_year
    )
    for advance in pending_advances:
        await _adv_repo.mark_deducted(db, advance)

    from app.services import transaction_service
    if body.account_id is not None:
        # Bank / digital: post account-linked transaction (updates account balance)
        await transaction_service.record_account_transaction(
            db,
            account_id=body.account_id,
            transaction_type=TransactionType.debit,
            reference_type=ReferenceType.salary,
            reference_id=payment.id,
            amount=net_salary,
            description=f"Salary {staff.name} {body.payment_month}/{body.payment_year}",
            transaction_date=date.today(),
            created_by=created_by,
        )
    else:
        # Cash salary without a named account — post reference transaction so it
        # appears in the financial ledger
        await transaction_service.record_reference_transaction(
            db,
            payment_method=body.payment_mode.value,
            transaction_type=TransactionType.debit,
            reference_type=ReferenceType.salary,
            reference_id=payment.id,
            amount=net_salary,
            description=f"Salary {staff.name} {body.payment_month}/{body.payment_year}",
            created_by=created_by,
        )
    await db.flush()
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="staff_payments", record_id=payment.id,
        new_values=audit_service.snapshot(payment),
    )

    return payment


async def list_payments(
    db: AsyncSession,
    staff_id: int,
    *,
    page: int = 1,
    limit: int = 24,
) -> tuple[list[StaffPayment], int]:
    staff = await _repo.get_or_404(db, staff_id)
    _active_or_404(staff, staff_id)
    return await _pay_repo.list_for_staff(
        db, staff_id,
        skip=(page - 1) * limit,
        limit=limit,
    )


# ── Advances ──────────────────────────────────────────────────────────────────

async def give_advance(
    db: AsyncSession,
    body: AdvanceCreate,
    *,
    created_by: int,
) -> Advance:
    staff = await _repo.get_or_404(db, body.staff_id)
    _active_or_404(staff, body.staff_id)

    advance = await _adv_repo.create(
        db,
        {
            "staff_id": body.staff_id,
            "amount": body.amount,
            "deduct_from_month": body.deduct_from_month,
            "deduct_from_year": body.deduct_from_year,
            "reason": body.reason,
            "paid_at": datetime.now(timezone.utc),
            "created_by": created_by,
        },
    )

    # Advances are always cash — post reference transaction so they appear in the ledger
    from app.services import transaction_service
    await transaction_service.record_reference_transaction(
        db,
        payment_method="cash",
        transaction_type=TransactionType.debit,
        reference_type=ReferenceType.advance,
        reference_id=advance.id,
        amount=body.amount,
        description=f"Advance {staff.name} — deduct {body.deduct_from_month}/{body.deduct_from_year}",
        created_by=created_by,
    )

    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="advances", record_id=advance.id,
        new_values=audit_service.snapshot(advance),
    )

    return advance


async def list_advances(
    db: AsyncSession,
    staff_id: int,
    *,
    is_deducted: bool | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Advance], int]:
    staff = await _repo.get_or_404(db, staff_id)
    _active_or_404(staff, staff_id)
    return await _adv_repo.list_for_staff(
        db, staff_id,
        is_deducted=is_deducted,
        skip=(page - 1) * limit,
        limit=limit,
    )
