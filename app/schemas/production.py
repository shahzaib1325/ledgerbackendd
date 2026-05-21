"""
Pydantic schemas for the Production module.

Entities:
  ProductionOrder       — header: product item, quantity, dates, costs, status
  ProductionRawMaterial — BOM line: what raw material is consumed and how much
  ProductionLabor       — labor entry: staff hours × rate
  ProductionCost        — other overhead costs (electricity, packaging, etc.)
  ProductionOutput      — actual output recorded when order completes

Status lifecycle: planned → in_progress → completed | cancelled
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ProductionStatus


# ── Raw Material ──────────────────────────────────────────────────────────────

class RawMaterialCreate(BaseModel):
    item_id: int
    unit_id: int | None = None
    required_quantity: Decimal = Field(..., gt=0, decimal_places=3)
    unit_cost: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)


class RawMaterialOut(BaseModel):
    id: int
    order_id: int
    item_id: int
    unit_id: int | None
    required_quantity: Decimal
    used_quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal

    model_config = {"from_attributes": True}


# ── Labor ─────────────────────────────────────────────────────────────────────

class LaborCreate(BaseModel):
    staff_id: int | None = None
    item_id: int | None = None
    quantity_produced: Decimal = Field(..., ge=0, decimal_places=3)
    rate_per_unit: Decimal = Field(..., ge=0, decimal_places=2)


class LaborOut(BaseModel):
    id: int
    order_id: int
    staff_id: int | None
    item_id: int | None
    quantity_produced: Decimal
    rate_per_unit: Decimal
    total_cost: Decimal

    model_config = {"from_attributes": True}


# ── Other Cost ────────────────────────────────────────────────────────────────

class ProductionCostCreate(BaseModel):
    cost_type: str = Field(..., min_length=1, max_length=100)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    note: str | None = None


class ProductionCostOut(BaseModel):
    id: int
    order_id: int
    cost_type: str
    amount: Decimal
    note: str | None

    model_config = {"from_attributes": True}


# ── Output ────────────────────────────────────────────────────────────────────

class ProductionOutputCreate(BaseModel):
    quantity_produced: Decimal = Field(..., gt=0, decimal_places=3)


class ProductionOutputOut(BaseModel):
    id: int
    order_id: int
    item_id: int
    quantity_produced: Decimal
    produced_at: datetime

    model_config = {"from_attributes": True}


# ── Production Order ──────────────────────────────────────────────────────────

class ProductionOrderCreate(BaseModel):
    order_no: str = Field(..., min_length=1, max_length=50)
    product_item_id: int
    quantity_to_produce: Decimal = Field(..., gt=0, decimal_places=3)
    start_date: date | None = None
    end_date: date | None = None
    selling_price: Decimal | None = Field(None, ge=0, decimal_places=2)
    notes: str | None = None
    raw_materials: list[RawMaterialCreate] = Field(default_factory=list)
    labor: list[LaborCreate] = Field(default_factory=list)
    costs: list[ProductionCostCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def end_after_start(self) -> "ProductionOrderCreate":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")
        return self


class ProductionOrderUpdate(BaseModel):
    """Editable while status is planned or in_progress."""
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None


class ProductionOrderOut(BaseModel):
    id: int
    order_no: str
    product_item_id: int
    product_item_name: str = ""
    quantity_to_produce: Decimal
    start_date: date | None
    end_date: date | None
    status: ProductionStatus
    total_material_cost: Decimal
    total_labor_cost: Decimal
    total_other_cost: Decimal
    total_cost: Decimal
    selling_price: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    raw_materials: list[RawMaterialOut]
    labor: list[LaborOut]
    costs: list[ProductionCostOut]
    outputs: list[ProductionOutputOut]

    model_config = {"from_attributes": True}


class ProductionOrderListOut(BaseModel):
    id: int
    order_no: str
    product_item_id: int
    product_item_name: str
    quantity_to_produce: Decimal
    start_date: date | None
    end_date: date | None
    status: ProductionStatus
    total_cost: Decimal
    selling_price: Decimal | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Query params ──────────────────────────────────────────────────────────────

ProductionSortField = Literal["created_at", "start_date", "end_date", "total_cost"]
SortOrder = Literal["asc", "desc"]
