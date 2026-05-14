"""
Pydantic schemas for the Suppliers module.

Naming: {Entity}Create / {Entity}Update / {Entity}Out / {Entity}ListOut
Internal fields (balance, is_active via delete) are never accepted as input.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import BalanceType, PaymentMode


# ── Items ─────────────────────────────────────────────────────────────────────

class SupplierItemCreate(BaseModel):
    item_id: int


class SupplierItemOut(BaseModel):
    id: int
    item_id: int

    model_config = {"from_attributes": True}


# ── Input schemas ─────────────────────────────────────────────────────────────

class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., max_length=20)
    email: EmailStr | None = None
    address: str | None = None
    opening_balance: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    balance_type: BalanceType = BalanceType.payable
    notes: str | None = None
    items: list[SupplierItemCreate] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class SupplierUpdate(BaseModel):
    """All fields optional — PATCH semantics."""

    name: str | None = Field(None, min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    address: str | None = None
    notes: str | None = None
    items: list[SupplierItemCreate] | None = None
    # opening_balance and balance are intentionally excluded

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class SupplierPaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_mode: PaymentMode
    account_id: int | None = None
    reference_no: str | None = Field(None, max_length=100)
    note: str | None = None
    paid_at: datetime | None = None  # defaults to now() in service

    @model_validator(mode="after")
    def account_required_for_non_cash(self) -> "SupplierPaymentCreate":
        if self.payment_mode in (PaymentMode.bank, PaymentMode.digital):
            if self.account_id is None:
                raise ValueError(
                    "account_id is required for bank or digital payments."
                )
        return self


# ── Output schemas ────────────────────────────────────────────────────────────

class SupplierOut(BaseModel):
    id: int
    name: str
    phone: str
    email: str | None
    address: str | None
    opening_balance: Decimal
    balance: Decimal
    balance_type: BalanceType
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    items: list[SupplierItemOut] = []

    model_config = {"from_attributes": True}


class SupplierListOut(BaseModel):
    """Lightweight projection for list endpoints."""

    id: int
    name: str
    phone: str | None
    balance: Decimal
    balance_type: BalanceType
    is_active: bool

    model_config = {"from_attributes": True}


class SupplierPaymentOut(BaseModel):
    id: int
    supplier_id: int
    amount: Decimal
    payment_mode: PaymentMode
    reference_no: str | None
    note: str | None
    paid_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SupplierLedgerEntry(BaseModel):
    date: date
    description: str
    debit: Decimal        # amount paid to supplier (decreases payable)
    credit: Decimal       # amount owed to supplier from purchase (increases payable)
    balance: Decimal      # absolute running balance after this entry (>= 0)
    balance_type: BalanceType  # direction of balance: payable | receivable
    reference_type: str   # 'opening' | 'purchase' | 'payment'
    reference_id: int     # 0 for opening balance row


class SupplierBalanceSummary(BaseModel):
    id: int
    name: str
    balance: Decimal
    balance_type: BalanceType

    model_config = {"from_attributes": True}


# ── Query params ──────────────────────────────────────────────────────────────

SortField = Literal["name", "balance", "created_at"]
SortOrder = Literal["asc", "desc"]
