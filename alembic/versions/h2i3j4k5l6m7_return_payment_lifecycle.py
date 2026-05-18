"""Add return payment lifecycle: received_amount, settlement_status on returns,
plus purchase_return_payments and sale_return_payments tables.

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Settlement fields on existing return tables ───────────────────────────
    op.add_column("purchase_returns", sa.Column("received_amount", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("purchase_returns", sa.Column("settlement_status", sa.String(20), nullable=False, server_default="unsettled"))

    op.add_column("sale_returns", sa.Column("received_amount", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("sale_returns", sa.Column("settlement_status", sa.String(10), nullable=False, server_default="unsettled"))

    # Backfill: existing approved returns that had balance adjusted should be marked settled
    op.execute("""
        UPDATE purchase_returns
        SET received_amount = refund_amount, settlement_status = 'settled'
        WHERE status = 'approved' AND refund_amount > 0
    """)
    op.execute("""
        UPDATE sale_returns
        SET received_amount = refund_amount, settlement_status = 'settled'
        WHERE status = 'approved' AND refund_amount > 0
    """)

    # ── Purchase return payments table ────────────────────────────────────────
    op.create_table(
        "purchase_return_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("purchase_returns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("payment_mode", sa.String(20), nullable=False),
        sa.Column("reference_no", sa.String(100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )

    # ── Sale return payments table ────────────────────────────────────────────
    op.create_table(
        "sale_return_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("payment_mode", sa.String(20), nullable=False),
        sa.Column("reference_no", sa.String(100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sale_return_payments")
    op.drop_table("purchase_return_payments")

    op.drop_column("sale_returns", "settlement_status")
    op.drop_column("sale_returns", "received_amount")
    op.drop_column("purchase_returns", "settlement_status")
    op.drop_column("purchase_returns", "received_amount")
