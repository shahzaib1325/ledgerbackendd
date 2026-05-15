"""Add penalty, refund_amount, return_type to sale_returns and purchase_returns.
Add rejection fields to purchase_returns for parity with sale_returns.

Revision ID: g1h2i3j4k5l6
Revises: e4f5a6b7c8d9
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = "g1h2i3j4k5l6"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sale_returns ──────────────────────────────────────────────────────────
    op.add_column("sale_returns", sa.Column("penalty", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("sale_returns", sa.Column("refund_amount", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("sale_returns", sa.Column("return_type", sa.String(10), nullable=False, server_default="partial"))

    # Backfill existing rows: refund_amount = total_amount (no penalty existed before)
    op.execute("UPDATE sale_returns SET refund_amount = total_amount WHERE refund_amount = 0 AND total_amount > 0")

    # ── purchase_returns ──────────────────────────────────────────────────────
    op.add_column("purchase_returns", sa.Column("penalty", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("purchase_returns", sa.Column("refund_amount", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("purchase_returns", sa.Column("return_type", sa.String(10), nullable=False, server_default="partial"))
    op.add_column("purchase_returns", sa.Column("rejected_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("purchase_returns", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("purchase_returns", sa.Column("rejection_reason", sa.Text(), nullable=True))

    # Backfill existing rows
    op.execute("UPDATE purchase_returns SET refund_amount = total_amount WHERE refund_amount = 0 AND total_amount > 0")


def downgrade() -> None:
    op.drop_column("purchase_returns", "rejection_reason")
    op.drop_column("purchase_returns", "rejected_at")
    op.drop_column("purchase_returns", "rejected_by")
    op.drop_column("purchase_returns", "return_type")
    op.drop_column("purchase_returns", "refund_amount")
    op.drop_column("purchase_returns", "penalty")

    op.drop_column("sale_returns", "return_type")
    op.drop_column("sale_returns", "refund_amount")
    op.drop_column("sale_returns", "penalty")
