"""production labor: category/qty/rate model; add selling_price to orders

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-11 00:00:00.000000

Changes:
  production_labor:
    - Drop: description, hours, rate_per_hour, total_cost (generated)
    - Add: category_id (FK categories), quantity_produced, rate_per_unit
    - Add: total_cost as GENERATED ALWAYS AS (quantity_produced * rate_per_unit) STORED
  production_orders:
    - Add: selling_price (nullable numeric)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── production_labor: remove old generated column first ──────────────────
    op.drop_column("production_labor", "total_cost")

    # Drop old constraints and columns
    op.drop_constraint("chk_production_labor_hours_positive", "production_labor", type_="check")
    op.drop_column("production_labor", "description")
    op.drop_column("production_labor", "hours")
    op.drop_column("production_labor", "rate_per_hour")

    # Add new columns
    op.add_column(
        "production_labor",
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "production_labor",
        sa.Column("quantity_produced", sa.Numeric(15, 3), nullable=False, server_default="0"),
    )
    op.add_column(
        "production_labor",
        sa.Column("rate_per_unit", sa.Numeric(15, 2), nullable=False, server_default="0"),
    )

    # Add new generated column (PostgreSQL GENERATED ALWAYS AS ... STORED)
    op.execute(
        "ALTER TABLE production_labor "
        "ADD COLUMN total_cost NUMERIC(15,2) GENERATED ALWAYS AS (quantity_produced * rate_per_unit) STORED"
    )

    # Add new check constraint
    op.create_check_constraint(
        "chk_production_labor_qty_nonneg",
        "production_labor",
        "quantity_produced >= 0",
    )

    # ── production_orders: add selling_price ─────────────────────────────────
    op.add_column(
        "production_orders",
        sa.Column("selling_price", sa.Numeric(15, 2), nullable=True),
    )


def downgrade() -> None:
    # Reverse selling_price
    op.drop_column("production_orders", "selling_price")

    # Reverse labor changes
    op.drop_constraint("chk_production_labor_qty_nonneg", "production_labor", type_="check")
    op.drop_column("production_labor", "total_cost")
    op.drop_column("production_labor", "rate_per_unit")
    op.drop_column("production_labor", "quantity_produced")
    op.drop_column("production_labor", "category_id")

    op.add_column("production_labor", sa.Column("description", sa.String(200), nullable=False, server_default=""))
    op.add_column("production_labor", sa.Column("hours", sa.Numeric(8, 2), nullable=False, server_default="0"))
    op.add_column("production_labor", sa.Column("rate_per_hour", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.execute(
        "ALTER TABLE production_labor "
        "ADD COLUMN total_cost NUMERIC(15,2) GENERATED ALWAYS AS (hours * rate_per_hour) STORED"
    )
    op.create_check_constraint(
        "chk_production_labor_hours_positive",
        "production_labor",
        "hours > 0",
    )
