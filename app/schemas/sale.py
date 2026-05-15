"""
Pydantic schemas for the Sales module.

Status lifecycle: draft → confirmed → partially_paid / paid → returned / void
due_amount is a PostgreSQL Computed column — never in input schemas.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import re

from pydantic import BaseModel, EmailStr, Field, model_validator

_PHONE_RE = re.compile(r'^[\d\s\-\+\(\)]+$')

from app.models.enums import PaymentMode, PaymentType, ReturnStatus, SaleStatus


# ── Line items ────────────────────────────────────────────────────────────────

class SaleItemCreate(BaseModel):
    item_id: int
    quantity: Decimal = Field(..., gt=0, decimal_places=3)
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)
    discount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)

    @model_validator(mode="after")
    def discount_not_exceed_line_total(self) -> "SaleItemCreate":
        if self.discount > self.quantity * self.unit_price:
            raise ValueError("Discount cannot exceed line total.")
        return self


class SaleItemOut(BaseModel):
    id: int
    item_id: int
    unit_id: int
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    total_price: Decimal

    model_config = {"from_attributes": True}


# ── Sale invoice (header) ─────────────────────────────────────────────────────

class SaleCreate(BaseModel):
    customer_type: Literal["regular", "walking"] = "regular"
    customer_id: int | None = None
    # Walk-in customer details (required when customer_type == 'walking')
    walking_customer_name: str | None = Field(None, max_length=200)
    walking_customer_phone: str | None = Field(None, max_length=20)
    walking_customer_email: EmailStr | None = None
    walking_customer_address: str | None = Field(None, max_length=500)
    walking_customer_tax_id: str | None = Field(None, max_length=50)
    invoice_date: date | None = None          # defaults to today in service
    due_date: date | None = None
    payment_type: PaymentType
    amount_paid: Decimal | None = Field(None, ge=0, decimal_places=2)
    discount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    tax: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    notes: str | None = None
    items: list[SaleItemCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_customer_and_payment(self) -> "SaleCreate":
        if self.customer_type == "regular":
            if self.customer_id is None:
                raise ValueError("customer_id is required for regular customers.")
        if self.customer_type == "walking" and self.payment_type != PaymentType.cash:
            raise ValueError("Walking customers can only use cash payment.")
        if self.customer_type == "walking":
            if not self.walking_customer_name or not self.walking_customer_name.strip():
                raise ValueError("walking_customer_name is required for walk-in customers.")
            if not self.walking_customer_phone or not self.walking_customer_phone.strip():
                raise ValueError("walking_customer_phone is required for walk-in customers.")
            if self.walking_customer_phone and not _PHONE_RE.match(self.walking_customer_phone):
                raise ValueError("walking_customer_phone must contain only digits, spaces, +, -, or ().")
        return self


class SaleUpdate(BaseModel):
    """Only editable while status=draft. Sending items replaces all existing line items."""

    customer_type: Literal["regular", "walking"] | None = None
    customer_id: int | None = None
    walking_customer_name: str | None = Field(None, max_length=200)
    walking_customer_phone: str | None = Field(None, max_length=20)
    walking_customer_email: EmailStr | None = None
    walking_customer_address: str | None = Field(None, max_length=500)
    walking_customer_tax_id: str | None = Field(None, max_length=50)
    payment_type: PaymentType | None = None
    amount_paid: Decimal | None = Field(None, ge=0, decimal_places=2)
    invoice_date: date | None = None
    due_date: date | None = None
    discount: Decimal | None = Field(None, ge=0, decimal_places=2)
    tax: Decimal | None = Field(None, ge=0, decimal_places=2)
    notes: str | None = None
    items: list[SaleItemCreate] | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "SaleUpdate":
        # If type is specified as walking, or if it remains walking (from existing data - handled in service),
        # we enforce contact details.
        if self.customer_type == "walking":
            if self.payment_type and self.payment_type != PaymentType.cash:
                raise ValueError("Walking customers can only use cash payment.")
            if not self.walking_customer_name or not self.walking_customer_name.strip():
                raise ValueError("walking_customer_name is required for walk-in customers.")
            if not self.walking_customer_phone or not self.walking_customer_phone.strip():
                raise ValueError("walking_customer_phone is required for walk-in customers.")
            if self.walking_customer_phone and not _PHONE_RE.match(self.walking_customer_phone):
                raise ValueError("walking_customer_phone must contain only digits, spaces, +, -, or ().")
        
        if self.customer_type == "regular" and self.customer_id is None:
            # Note: This is a bit complex for update because customer_id might already be on the DB record.
            # The service layer handles the final merge validation, but this schema can catch explicit invalidation.
            pass

        return self


class SaleOut(BaseModel):
    id: int
    customer_id: int | None
    customer_type: str
    customer_name: str = ""
    walking_customer_name: str | None
    walking_customer_phone: str | None
    walking_customer_email: str | None
    walking_customer_address: str | None
    walking_customer_tax_id: str | None
    invoice_no: str
    invoice_date: date
    due_date: date | None
    payment_type: PaymentType
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    due_amount: Decimal
    status: SaleStatus
    notes: str | None
    confirmed_at: datetime | None
    confirmed_by: int | None
    created_by: int
    created_at: datetime
    updated_at: datetime
    items: list[SaleItemOut]

    model_config = {"from_attributes": True}


class SaleListOut(BaseModel):
    id: int
    customer_id: int | None
    customer_type: str
    customer_name: str = ""
    invoice_no: str
    invoice_date: date
    due_date: date | None
    payment_type: PaymentType
    total_amount: Decimal
    paid_amount: Decimal
    due_amount: Decimal
    status: SaleStatus
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Payments ──────────────────────────────────────────────────────────────────

class SalePaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_mode: PaymentMode
    account_id: int | None = None
    reference_no: str | None = Field(None, max_length=100)
    received_at: datetime | None = None

    @model_validator(mode="after")
    def account_required_for_non_cash(self) -> "SalePaymentCreate":
        if self.payment_mode in (PaymentMode.bank, PaymentMode.digital):
            if self.account_id is None:
                raise ValueError("account_id is required for bank or digital payments.")
        return self


class SalePaymentOut(BaseModel):
    id: int
    invoice_id: int
    amount: Decimal
    payment_mode: PaymentMode
    account_id: int | None
    reference_no: str | None
    received_at: datetime

    model_config = {"from_attributes": True}


# ── Returns ───────────────────────────────────────────────────────────────────

class SaleReturnItemCreate(BaseModel):
    item_id: int
    quantity: Decimal = Field(..., gt=0, decimal_places=3)
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)


class SaleReturnItemOut(BaseModel):
    id: int
    item_id: int
    quantity: Decimal
    unit_price: Decimal
    total_price: Decimal

    model_config = {"from_attributes": True}


class SaleReturnCreate(BaseModel):
    return_type: Literal["complete", "partial"] = "partial"
    reason: str | None = None
    penalty: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    items: list[SaleReturnItemCreate] = Field(..., min_length=1)


class SaleReturnRejectRequest(BaseModel):
    rejection_reason: str | None = None


class SaleReturnOut(BaseModel):
    id: int
    invoice_id: int
    return_date: date
    return_type: str
    reason: str | None
    total_amount: Decimal
    penalty: Decimal
    refund_amount: Decimal
    status: ReturnStatus
    approved_by: int | None
    approved_at: datetime | None
    rejected_by: int | None
    rejected_at: datetime | None
    rejection_reason: str | None
    created_by: int | None
    created_at: datetime
    return_items: list[SaleReturnItemOut] = []

    model_config = {"from_attributes": True}


# ── Query params ──────────────────────────────────────────────────────────────

SaleSortField = Literal["invoice_date", "total_amount", "created_at", "due_date"]
SortOrder = Literal["asc", "desc"]
