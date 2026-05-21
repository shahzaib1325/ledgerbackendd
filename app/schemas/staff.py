"""
Pydantic schemas for the Staff / Payroll module.

Entities:
  Staff            — employee profile
  SalaryStructure  — basic + allowances/deductions JSONB, date-ranged
  Attendance       — daily presence record (unique per staff per date)
  StaffPayment     — monthly salary disbursement (unique per staff per month/year)
  Advance          — salary advance, deducted in a future month
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import AttendanceStatus, CompensationType, PaymentMode, SalaryPeriod


# ── Staff Items ──────────────────────────────────────────────────────────

class StaffItemCreate(BaseModel):
    item_id: int
    rate_per_unit: Decimal | None = Field(None, gt=0, decimal_places=2)


class StaffItemOut(BaseModel):
    id: int
    item_id: int
    item_name: str = ""
    rate_per_unit: Decimal | None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _extract_relation_names(cls, data: object) -> object:
        if not hasattr(data, "__dict__"):
            return data
        result = {
            k: v for k, v in vars(data).items()
            if not k.startswith("_")
        }
        item = getattr(data, "item", None)
        if item is not None:
            result["item_name"] = item.name
        return result


# ── Staff ─────────────────────────────────────────────────────────────────────

class StaffCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=20)
    cnic: str | None = Field(None, max_length=20)
    address: str | None = None
    join_date: date
    compensation_type: CompensationType
    salary_amount: Decimal | None = Field(None, gt=0, decimal_places=2)
    salary_period: SalaryPeriod | None = None
    designation: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)
    items: list[StaffItemCreate] = Field(default_factory=list)

    @field_validator("cnic")
    @classmethod
    def strip_cnic(cls, v: str | None) -> str | None:
        return v.strip() if v else None

    @model_validator(mode="after")
    def salary_fields_consistent(self) -> "StaffCreate":
        if self.compensation_type == CompensationType.salary_based:
            if not self.salary_amount:
                raise ValueError("salary_amount is required for salary-based staff.")
            if not self.salary_period:
                raise ValueError("salary_period is required for salary-based staff.")
        return self


class StaffUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=20)
    address: str | None = None
    designation: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)
    compensation_type: CompensationType | None = None
    salary_period: SalaryPeriod | None = None
    items: list[StaffItemCreate] | None = None


class StaffOut(BaseModel):
    id: int
    name: str
    phone: str | None
    cnic: str | None
    address: str | None
    join_date: date
    compensation_type: CompensationType
    salary_period: SalaryPeriod | None
    designation: str | None
    department: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    items: list[StaffItemOut] = []

    model_config = {"from_attributes": True}


class StaffListOut(BaseModel):
    id: int
    name: str
    phone: str | None
    compensation_type: CompensationType
    designation: str | None
    department: str | None
    is_active: bool

    model_config = {"from_attributes": True}


# ── Salary Structure ──────────────────────────────────────────────────────────

class SalaryStructureCreate(BaseModel):
    basic_salary: Decimal = Field(..., gt=0, decimal_places=2)
    allowances: dict[str, Any] = Field(default_factory=dict)
    deductions: dict[str, Any] = Field(default_factory=dict)
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def effective_range_valid(self) -> "SalaryStructureCreate":
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from.")
        return self


class SalaryStructureOut(BaseModel):
    id: int
    staff_id: int
    basic_salary: Decimal
    allowances: dict[str, Any]
    deductions: dict[str, Any]
    effective_from: date
    effective_to: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Attendance ────────────────────────────────────────────────────────────────

class AttendanceCreate(BaseModel):
    staff_id: int
    date: date
    status: AttendanceStatus
    notes: str | None = None


class AttendanceBulkCreate(BaseModel):
    """Record attendance for multiple staff on the same date."""
    date: date
    records: list["AttendanceRecord"] = Field(..., min_length=1)


class AttendanceRecord(BaseModel):
    staff_id: int
    status: AttendanceStatus
    notes: str | None = None


class AttendanceUpdate(BaseModel):
    status: AttendanceStatus
    notes: str | None = None


class AttendanceOut(BaseModel):
    id: int
    staff_id: int
    date: date
    status: AttendanceStatus
    notes: str | None

    model_config = {"from_attributes": True}


# ── Staff Payment (salary disbursement) ───────────────────────────────────────

class StaffPaymentCreate(BaseModel):
    staff_id: int
    payment_month: int = Field(..., ge=1, le=12)
    payment_year: int = Field(..., ge=2000, le=2100)
    gross_salary: Decimal = Field(..., gt=0, decimal_places=2)
    total_allowances: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    total_deductions: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    advance_deduction: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    payment_mode: PaymentMode
    account_id: int | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def account_required_for_non_cash(self) -> "StaffPaymentCreate":
        if self.payment_mode in (PaymentMode.bank, PaymentMode.digital):
            if self.account_id is None:
                raise ValueError("account_id is required for bank or digital payments.")
        return self


class StaffPaymentOut(BaseModel):
    id: int
    staff_id: int
    payment_month: int
    payment_year: int
    gross_salary: Decimal
    total_allowances: Decimal
    total_deductions: Decimal
    advance_deduction: Decimal
    net_salary: Decimal
    payment_mode: PaymentMode
    account_id: int | None
    paid_at: datetime
    notes: str | None

    model_config = {"from_attributes": True}


# ── Advance ───────────────────────────────────────────────────────────────────

class AdvanceCreate(BaseModel):
    staff_id: int
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    deduct_from_month: int = Field(..., ge=1, le=12)
    deduct_from_year: int = Field(..., ge=2000, le=2100)
    reason: str | None = None


class AdvanceOut(BaseModel):
    id: int
    staff_id: int
    amount: Decimal
    deduct_from_month: int
    deduct_from_year: int
    reason: str | None
    is_deducted: bool
    paid_at: datetime

    model_config = {"from_attributes": True}


# ── Per-Unit Earnings ────────────────────────────────────────────────────────

class ProductionEarningEntry(BaseModel):
    """One labour entry from a completed production order."""
    order_id: int
    order_no: str
    item_name: str
    quantity_produced: Decimal
    rate_per_unit: Decimal
    labour_earning: Decimal
    completed_at: date | None

    model_config = {"from_attributes": True}


class PerUnitEarningsSummary(BaseModel):
    """Payroll-period earnings summary for a per-unit staff member."""
    staff_id: int
    month: int
    year: int
    total_earned: Decimal
    total_disbursed: Decimal
    due_amount: Decimal
    production_entries: list[ProductionEarningEntry]


class UnpaidLaborEntry(BaseModel):
    """A production labor row with remaining unpaid amount."""
    labor_id: int
    order_id: int
    order_no: str
    item_name: str
    quantity_produced: Decimal
    rate_per_unit: Decimal
    total_earning: Decimal
    remaining_amount: Decimal
    completed_at: date | None

    model_config = {"from_attributes": True}


class UnpaidEarningsSummary(BaseModel):
    """Full unpaid earnings ledger for a per-unit staff member."""
    staff_id: int
    carry_forward_balance: Decimal
    new_earnings: Decimal
    total_due: Decimal
    unpaid_entries: list[UnpaidLaborEntry]


# ── Query params ──────────────────────────────────────────────────────────────

StaffSortField = Literal["name", "join_date", "created_at"]
SortOrder = Literal["asc", "desc"]
