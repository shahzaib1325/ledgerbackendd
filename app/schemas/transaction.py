"""
Pydantic schemas for the Transactions / Accounts module.

Entities:
  Account     — cash / bank / digital account with running balance
  Transaction — immutable ledger entry linked to an account
  Transfer    — moves funds between two accounts atomically
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AccountType, ReferenceType, TransactionType


# ── Account ───────────────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    account_type: AccountType
    account_no: str | None = Field(None, max_length=100)
    bank_name: str | None = Field(None, max_length=150)
    opening_balance: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)

    @model_validator(mode="after")
    def bank_fields_for_bank_type(self) -> "AccountCreate":
        if self.account_type == AccountType.bank and not self.bank_name:
            raise ValueError("bank_name is required for bank accounts.")
        return self


class AccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    account_no: str | None = Field(None, max_length=100)
    bank_name: str | None = Field(None, max_length=150)


class AccountOut(BaseModel):
    id: int
    name: str
    account_type: AccountType
    account_no: str | None
    bank_name: str | None
    opening_balance: Decimal
    current_balance: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountListOut(BaseModel):
    id: int
    name: str
    account_type: AccountType
    account_no: str | None
    bank_name: str | None
    current_balance: Decimal
    is_active: bool

    model_config = {"from_attributes": True}


# ── Transaction ───────────────────────────────────────────────────────────────

class TransactionOut(BaseModel):
    id: int
    account_id: int | None
    payment_method: str | None
    transaction_type: TransactionType
    reference_type: ReferenceType
    reference_id: int | None
    amount: Decimal
    balance_after: Decimal | None
    description: str
    transaction_date: date
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Transfer ──────────────────────────────────────────────────────────────────

class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    reference_no: str | None = Field(None, max_length=100)
    note: str | None = None

    @model_validator(mode="after")
    def accounts_must_differ(self) -> "TransferCreate":
        if self.from_account_id == self.to_account_id:
            raise ValueError("from_account_id and to_account_id must differ.")
        return self


class TransferOut(BaseModel):
    id: int
    from_account_id: int
    to_account_id: int
    amount: Decimal
    reference_no: str | None
    note: str | None
    transferred_at: datetime
    created_by: int | None

    model_config = {"from_attributes": True}


# ── Query params ──────────────────────────────────────────────────────────────

AccountSortField = Literal["name", "current_balance", "created_at"]
TransactionSortField = Literal["transaction_date", "amount", "created_at"]
SortOrder = Literal["asc", "desc"]
ReferenceTypeLiteral = Literal[
    "purchase", "sale", "purchase_payment", "sale_payment",
    "salary", "advance", "transfer", "expense", "adjustment",
]
