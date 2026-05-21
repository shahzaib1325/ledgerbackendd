"""Add payment_labor_entries table for tracking which production work
each staff payment covers.

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-05-21
"""
import sqlalchemy as sa
from alembic import op

revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_labor_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "payment_id",
            sa.Integer,
            sa.ForeignKey("staff_payments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "labor_id",
            sa.Integer,
            sa.ForeignKey("production_labor.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.CheckConstraint("amount > 0", name="chk_payment_labor_amount_positive"),
    )
    op.create_index(
        "ix_payment_labor_entries_payment_id",
        "payment_labor_entries",
        ["payment_id"],
    )
    op.create_index(
        "ix_payment_labor_entries_labor_id",
        "payment_labor_entries",
        ["labor_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_labor_entries_labor_id")
    op.drop_index("ix_payment_labor_entries_payment_id")
    op.drop_table("payment_labor_entries")
