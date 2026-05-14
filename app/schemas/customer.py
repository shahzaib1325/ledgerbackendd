"""
Pydantic schemas for the Customers module.

Naming: {Entity}Create / {Entity}Update / {Entity}Out / {Entity}ListOut
Internal fields (balance, is_active via delete) are never accepted as input.

Customer balance direction is the mirror of Supplier:
  receivable → customer owes us money (default after a sale)
  payable    → we owe the customer (overpayment / credit note)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import BalanceType, PaymentMode


# ── Input schemas ─────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., max_length=20)
    email: EmailStr | None = None
    address: str | None = None
    credit_limit: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    opening_balance: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    balance_type: BalanceType = BalanceType.receivable
    is_active: bool = True
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class CustomerUpdate(BaseModel):
    """All fields optional — PATCH semantics."""

    name: str | None = Field(None, min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    address: str | None = None
    credit_limit: Decimal | None = Field(None, ge=0, decimal_places=2)
    is_active: bool | None = None
    notes: str | None = None
    # opening_balance and balance intentionally excluded

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class CustomerPaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_mode: PaymentMode
    account_id: int | None = None
    reference_no: str | None = Field(None, max_length=100)
    note: str | None = None
    received_at: datetime | None = None  # defaults to now() in service

    @model_validator(mode="after")
    def account_required_for_non_cash(self) -> "CustomerPaymentCreate":
        if self.payment_mode in (PaymentMode.bank, PaymentMode.digital):
            if self.account_id is None:
                raise ValueError(
                    "account_id is required for bank or digital payments."
                )
        return self


# ── Output schemas ────────────────────────────────────────────────────────────

class CustomerOut(BaseModel):
    id: int
    name: str
    phone: str
    email: str | None
    address: str | None
    credit_limit: Decimal
    opening_balance: Decimal
    balance: Decimal
    balance_type: BalanceType
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerListOut(BaseModel):
    """Lightweight projection for list endpoints."""

    id: int
    name: str
    phone: str
    balance: Decimal
    balance_type: BalanceType
    credit_limit: Decimal
    is_active: bool

    model_config = {"from_attributes": True}


class CustomerPaymentOut(BaseModel):
    id: int
    customer_id: int
    amount: Decimal
    payment_mode: PaymentMode
    reference_no: str | None
    note: str | None
    received_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomerLedgerEntry(BaseModel):
    date: date
    description: str
    debit: Decimal        # sale amount — increases Accounts Receivable (asset ↑)
    credit: Decimal       # payment received — decreases Accounts Receivable (asset ↓)
    balance: Decimal      # absolute running balance after this entry (>= 0)
    balance_type: BalanceType  # direction: receivable | payable
    reference_type: str   # 'opening' | 'sale' | 'payment'
    reference_id: int     # 0 for opening balance row


class CustomerBalanceSummary(BaseModel):
    id: int
    name: str
    balance: Decimal
    balance_type: BalanceType
    credit_limit: Decimal

    model_config = {"from_attributes": True}


# ── Query params ──────────────────────────────────────────────────────────────

SortField = Literal["name", "balance", "created_at"]
SortOrder = Literal["asc", "desc"]
