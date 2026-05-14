"""sale: add walking customer detail fields to sale_invoices

Revision ID: f7e8d9c0b1a2
Revises: e5f6a7b8c9d0
Create Date: 2026-05-11

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f7e8d9c0b1a2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sale_invoices", sa.Column("walking_customer_name", sa.String(200), nullable=True))
    op.add_column("sale_invoices", sa.Column("walking_customer_phone", sa.String(20), nullable=True))
    op.add_column("sale_invoices", sa.Column("walking_customer_email", sa.String(255), nullable=True))
    op.add_column("sale_invoices", sa.Column("walking_customer_address", sa.Text(), nullable=True))
    op.add_column("sale_invoices", sa.Column("walking_customer_tax_id", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("sale_invoices", "walking_customer_tax_id")
    op.drop_column("sale_invoices", "walking_customer_address")
    op.drop_column("sale_invoices", "walking_customer_email")
    op.drop_column("sale_invoices", "walking_customer_phone")
    op.drop_column("sale_invoices", "walking_customer_name")
