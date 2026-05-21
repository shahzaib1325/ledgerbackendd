"""
Pydantic schemas for the Purchases module.

Status lifecycle: draft → confirmed → (returned | void)
due_amount is Computed by PostgreSQL — never in input schemas.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import PaymentMode, PaymentType, PurchaseStatus, ReturnStatus


# ── Line items ────────────────────────────────────────────────────────────────

class PurchaseItemCreate(BaseModel):
    item_id: int
    quantity: Decimal = Field(..., gt=0, decimal_places=3)
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)
    discount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)

    @model_validator(mode="after")
    def discount_not_exceed_line_total(self) -> "PurchaseItemCreate":
        line_total = self.quantity * self.unit_price
        if self.discount > line_total:
            raise ValueError("Discount cannot exceed line total.")
        return self


class PurchaseItemOut(BaseModel):
    id: int
    item_id: int
    item_name: str = ""
    item_sku: str | None = None
    unit_id: int
    unit_name: str = ""
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    total_price: Decimal

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _extract_relation_names(cls, data: object) -> object:
        """Pull item.name/sku and unit.name from ORM relationships when present."""
        if not hasattr(data, "__dict__"):
            return data
        result = {
            k: v for k, v in vars(data).items()
            if not k.startswith("_")
        }
        item = getattr(data, "item", None)
        if item is not None:
            result["item_name"] = item.name
            result["item_sku"] = item.sku
        unit = getattr(data, "unit", None)
        if unit is not None:
            result["unit_name"] = unit.name
        return result


# ── Purchase (header) ─────────────────────────────────────────────────────────

class PurchaseCreate(BaseModel):
    supplier_id: int
    invoice_no: str | None = None              # supplier's own invoice number (optional)
    purchase_date: date | None = None          # defaults to today in service
    payment_type: PaymentType
    paid_amount: Decimal | None = Field(None, ge=0, decimal_places=2)  # required for partial
    discount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    overhead_cost: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    notes: str | None = None
    items: list[PurchaseItemCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_partial_payment(self) -> "PurchaseCreate":
        if self.payment_type == PaymentType.partial:
            if self.paid_amount is None:
                raise ValueError("paid_amount is required when payment_type is partial.")
            if self.paid_amount <= Decimal("0"):
                raise ValueError("paid_amount must be greater than 0 for partial payment.")
        return self


class PurchaseUpdate(BaseModel):
    """Only editable while status=confirmed."""

    invoice_no: str | None = None
    purchase_date: date | None = None
    payment_type: PaymentType | None = None
    paid_amount: Decimal | None = Field(None, ge=0, decimal_places=2)
    discount: Decimal | None = Field(None, ge=0, decimal_places=2)
    items: list[PurchaseItemCreate] | None = None
    notes: str | None = None


class PurchaseOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str = ""
    invoice_no: str | None
    purchase_date: date
    payment_type: PaymentType
    subtotal: Decimal
    discount: Decimal
    overhead_cost: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    due_amount: Decimal
    status: PurchaseStatus
    notes: str | None
    confirmed_at: datetime | None
    confirmed_by: int | None
    created_by: int
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseItemOut]

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _extract_supplier_name(cls, data: object) -> object:
        if not hasattr(data, "__dict__"):
            return data
        result = {k: v for k, v in vars(data).items() if not k.startswith("_")}
        supplier = getattr(data, "supplier", None)
        if supplier is not None:
            result["supplier_name"] = supplier.name
        return result


class PurchaseListOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str = ""
    invoice_no: str | None
    purchase_date: date
    payment_type: PaymentType
    total_amount: Decimal
    paid_amount: Decimal
    due_amount: Decimal
    status: PurchaseStatus
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Payments ──────────────────────────────────────────────────────────────────

class PurchasePaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_mode: PaymentMode
    account_id: int | None = None
    reference_no: str | None = Field(None, max_length=100)
    paid_at: datetime | None = None

    @model_validator(mode="after")
    def account_required_for_non_cash(self) -> "PurchasePaymentCreate":
        if self.payment_mode in (PaymentMode.bank, PaymentMode.digital):
            if self.account_id is None:
                raise ValueError("account_id is required for bank or digital payments.")
        return self


class PurchasePaymentOut(BaseModel):
    id: int
    purchase_id: int
    amount: Decimal
    payment_mode: PaymentMode
    account_id: int | None
    reference_no: str | None
    paid_at: datetime

    model_config = {"from_attributes": True}


# ── Returns ───────────────────────────────────────────────────────────────────

class PurchaseReturnItemCreate(BaseModel):
    item_id: int
    quantity: Decimal = Field(..., gt=0, decimal_places=3)
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)


class PurchaseReturnCreate(BaseModel):
    return_type: Literal["complete", "partial"] = "partial"
    reason: str | None = None
    penalty: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    items: list[PurchaseReturnItemCreate] = Field(..., min_length=1)


class PurchaseReturnRejectRequest(BaseModel):
    rejection_reason: str | None = None


class PurchaseReturnItemOut(BaseModel):
    id: int
    item_id: int
    quantity: Decimal
    unit_price: Decimal
    total_price: Decimal

    model_config = {"from_attributes": True}


class PurchaseReturnPaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_mode: str = Field(..., min_length=1)
    reference_no: str | None = None
    note: str | None = None


class PurchaseReturnPaymentOut(BaseModel):
    id: int
    return_id: int
    amount: Decimal
    payment_mode: str
    reference_no: str | None
    note: str | None
    paid_at: datetime
    created_by: int | None

    model_config = {"from_attributes": True}


class PurchaseReturnOut(BaseModel):
    id: int
    purchase_id: int
    return_date: date
    return_type: str
    reason: str | None
    total_amount: Decimal
    penalty: Decimal
    refund_amount: Decimal
    received_amount: Decimal
    settlement_status: str
    status: ReturnStatus
    approved_by: int | None
    approved_at: datetime | None
    rejected_by: int | None
    rejected_at: datetime | None
    rejection_reason: str | None
    created_by: int | None
    created_at: datetime
    return_items: list[PurchaseReturnItemOut] = []
    payments: list[PurchaseReturnPaymentOut] = []

    model_config = {"from_attributes": True}


# ── Query params ──────────────────────────────────────────────────────────────

PurchaseSortField = Literal["purchase_date", "total_amount", "created_at"]
SortOrder = Literal["asc", "desc"]
