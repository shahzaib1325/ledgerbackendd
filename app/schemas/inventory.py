"""
Pydantic schemas for the Inventory module.

Entities: Unit, Category, Item, StockMovement.
current_stock is never accepted as input — it is maintained by StockMovement.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ItemType, MovementType


# ── Unit ──────────────────────────────────────────────────────────────────────

class UnitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    abbreviation: str = Field(..., min_length=1, max_length=10)

    @field_validator("name", "abbreviation")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class UnitUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50)
    abbreviation: str | None = Field(None, min_length=1, max_length=10)

    @field_validator("name", "abbreviation")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class UnitOut(BaseModel):
    id: int
    name: str
    abbreviation: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Category ──────────────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    parent_id: int | None = None

    @field_validator("name")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    parent_id: int | None = None

    @field_validator("name")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Item ──────────────────────────────────────────────────────────────────────

class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    sku: str | None = Field(None, max_length=100)
    category_id: int | None = None
    unit_id: int
    item_type: ItemType
    reorder_level: Decimal = Field(Decimal("0"), ge=0, decimal_places=3)
    sale_price: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    purchase_price: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)

    @field_validator("name")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("sku")
    @classmethod
    def strip_sku(cls, v: str | None) -> str | None:
        return v.strip() if v else None


class ItemUpdate(BaseModel):
    """PATCH semantics — all fields optional. current_stock excluded."""

    name: str | None = Field(None, min_length=1, max_length=200)
    sku: str | None = Field(None, max_length=100)
    category_id: int | None = None
    unit_id: int | None = None
    reorder_level: Decimal | None = Field(None, ge=0, decimal_places=3)
    sale_price: Decimal | None = Field(None, ge=0, decimal_places=2)
    purchase_price: Decimal | None = Field(None, ge=0, decimal_places=2)

    @field_validator("name")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class ItemOut(BaseModel):
    id: int
    name: str
    sku: str | None
    category_id: int | None
    unit_id: int
    item_type: ItemType
    current_stock: Decimal
    reorder_level: Decimal
    sale_price: Decimal
    purchase_price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ItemListOut(BaseModel):
    """Lightweight projection for list endpoints."""

    id: int
    name: str
    sku: str | None
    item_type: ItemType
    current_stock: Decimal
    reorder_level: Decimal
    sale_price: Decimal
    purchase_price: Decimal
    is_active: bool

    model_config = {"from_attributes": True}


# ── StockMovement ─────────────────────────────────────────────────────────────

class StockAdjustmentCreate(BaseModel):
    """
    Manual stock adjustment (movement_type=adjustment).
    quantity > 0 adds stock, < 0 removes stock.
    item_id is injected from the URL path parameter by the endpoint.
    """
    item_id: int = 0
    quantity: Decimal = Field(..., decimal_places=3)
    note: str | None = None

    @field_validator("quantity")
    @classmethod
    def non_zero(cls, v: Decimal) -> Decimal:
        if v == Decimal("0"):
            raise ValueError("Adjustment quantity must be non-zero.")
        return v


class StockMovementOut(BaseModel):
    id: int
    item_id: int
    movement_type: MovementType
    quantity: Decimal
    stock_before: Decimal
    stock_after: Decimal
    reference_type: str | None
    reference_id: int | None
    note: str | None
    moved_at: datetime

    model_config = {"from_attributes": True}


# ── Query params ──────────────────────────────────────────────────────────────

ItemSortField = Literal["name", "current_stock", "sale_price", "created_at"]
SortOrder = Literal["asc", "desc"]
