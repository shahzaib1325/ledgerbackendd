from datetime import date, datetime
from decimal import Decimal
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AttendanceStatus, CompensationType, PaymentMode, SalaryPeriod, StaffType


if TYPE_CHECKING:
    from app.models.inventory import Item
    from app.models.production import ProductionLabor


class Staff(TimestampMixin, Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cnic: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    join_date: Mapped[date] = mapped_column(Date, nullable=False)
    staff_type: Mapped[StaffType | None] = mapped_column(
        Enum(StaffType, name="staff_type", native_enum=True), nullable=True
    )
    compensation_type: Mapped[CompensationType] = mapped_column(
        Enum(CompensationType, name="compensation_type", native_enum=True),
        nullable=False,
        server_default="salary_based",
    )
    salary_period: Mapped[SalaryPeriod | None] = mapped_column(
        Enum(SalaryPeriod, name="salary_period", native_enum=True), nullable=True
    )
    designation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    salary_structures: Mapped[list["SalaryStructure"]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )
    attendances: Mapped[list["Attendance"]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )
    payments: Mapped[list["StaffPayment"]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )
    advances: Mapped[list["Advance"]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )
    items: Mapped[list["StaffItem"]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )


class SalaryStructure(Base):
    __tablename__ = "salary_structures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("staff.id", ondelete="RESTRICT"), nullable=False
    )
    basic_salary: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    allowances: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    deductions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    staff: Mapped["Staff"] = relationship(back_populates="salary_structures")


class Attendance(Base):
    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("staff.id", ondelete="RESTRICT"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, name="attendance_status", native_enum=True),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    staff: Mapped["Staff"] = relationship(back_populates="attendances")

    __table_args__ = (
        UniqueConstraint("staff_id", "date", name="uq_attendance_staff_date"),
    )


class StaffPayment(Base):
    __tablename__ = "staff_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("staff.id", ondelete="RESTRICT"), nullable=False
    )
    payment_month: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    payment_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gross_salary: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    total_allowances: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_deductions: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    advance_deduction: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    net_salary: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_mode: Mapped[PaymentMode] = mapped_column(
        Enum(PaymentMode, name="payment_mode", native_enum=True, create_type=False),
        nullable=False,
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    staff: Mapped["Staff"] = relationship(back_populates="payments")
    account: Mapped["Account"] = relationship(foreign_keys=[account_id])  # type: ignore[name-defined]

    __table_args__ = (
        CheckConstraint(
            "payment_month BETWEEN 1 AND 12",
            name="chk_staff_payments_month_range",
        ),
    )


class Advance(Base):
    __tablename__ = "advances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("staff.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    deduct_from_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    deduct_from_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deducted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    staff: Mapped["Staff"] = relationship(back_populates="advances")


class PaymentLaborEntry(Base):
    """Links a staff payment to the production_labor rows it covers (audit trail)."""

    __tablename__ = "payment_labor_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("staff_payments.id", ondelete="CASCADE"), nullable=False
    )
    labor_id: Mapped[int] = mapped_column(
        ForeignKey("production_labor.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    payment: Mapped["StaffPayment"] = relationship()
    labor: Mapped["ProductionLabor"] = relationship()

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_payment_labor_amount_positive"),
    )


class StaffItem(Base):
    """Links a staff member to inventory items they can produce, with an optional rate."""

    __tablename__ = "staff_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    rate_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    staff: Mapped["Staff"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()

    __table_args__ = (
        UniqueConstraint("staff_id", "item_id", name="uq_staff_items_staff_item"),
    )
