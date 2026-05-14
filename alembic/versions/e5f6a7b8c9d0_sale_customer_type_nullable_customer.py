"""sale: add customer_type, make customer_id nullable

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-11

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sale_invoices",
        sa.Column(
            "customer_type",
            sa.String(10),
            nullable=False,
            server_default="regular",
        ),
    )
    op.alter_column("sale_invoices", "customer_id", nullable=True)


def downgrade() -> None:
    op.alter_column("sale_invoices", "customer_id", nullable=False)
    op.drop_column("sale_invoices", "customer_type")
