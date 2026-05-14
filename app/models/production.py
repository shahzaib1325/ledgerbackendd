from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ProductionStatus


if TYPE_CHECKING:
    from app.models.inventory import Item


class ProductionOrder(TimestampMixin, Base):
    __tablename__ = "production_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    product_item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_to_produce: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ProductionStatus] = mapped_column(
        Enum(ProductionStatus, name="production_status", native_enum=True),
        nullable=False,
        default=ProductionStatus.planned,
        server_default=ProductionStatus.planned.value,
    )
    total_material_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_labor_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_other_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        Computed(
            "total_material_cost + total_labor_cost + total_other_cost",
            persisted=True,
        ),
        nullable=False,
    )
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    product_item: Mapped["Item"] = relationship(  # type: ignore[name-defined]
        foreign_keys=[product_item_id]
    )
    raw_materials: Mapped[list["ProductionRawMaterial"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    labor: Mapped[list["ProductionLabor"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    costs: Mapped[list["ProductionCost"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    outputs: Mapped[list["ProductionOutput"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("quantity_to_produce > 0", name="chk_production_qty_positive"),
        Index("idx_production_orders_status", "status"),
    )


class ProductionRawMaterial(Base):
    __tablename__ = "production_raw_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), nullable=True
    )
    required_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    used_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), nullable=False, default=0, server_default="0"
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    order: Mapped["ProductionOrder"] = relationship(back_populates="raw_materials")
    item: Mapped["Item"] = relationship(foreign_keys=[item_id])  # type: ignore[name-defined]
    unit: Mapped["Unit | None"] = relationship(foreign_keys=[unit_id])  # type: ignore[name-defined]


class ProductionLabor(Base):
    __tablename__ = "production_labor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("staff.id", ondelete="SET NULL"), nullable=True
    )
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True
    )
    quantity_produced: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), nullable=False, default=0, server_default="0"
    )
    rate_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        Computed("quantity_produced * rate_per_unit", persisted=True),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    order: Mapped["ProductionOrder"] = relationship(back_populates="labor")
    staff: Mapped["Staff | None"] = relationship(  # type: ignore[name-defined]
        foreign_keys=[staff_id]
    )
    item: Mapped["Item | None"] = relationship(  # type: ignore[name-defined]
        foreign_keys=[item_id]
    )

    __table_args__ = (
        CheckConstraint("quantity_produced >= 0", name="chk_production_labor_qty_nonneg"),
    )


class ProductionCost(Base):
    __tablename__ = "production_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False
    )
    cost_type: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    order: Mapped["ProductionOrder"] = relationship(back_populates="costs")

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_production_cost_amount_positive"),
    )


class ProductionOutput(Base):
    __tablename__ = "production_output"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_produced: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    order: Mapped["ProductionOrder"] = relationship(back_populates="outputs")
    item: Mapped["Item"] = relationship(foreign_keys=[item_id])  # type: ignore[name-defined]
