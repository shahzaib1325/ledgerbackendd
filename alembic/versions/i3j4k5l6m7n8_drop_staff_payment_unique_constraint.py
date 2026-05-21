"""Drop unique constraint on staff_payments (staff_id, payment_month, payment_year)
to allow multiple partial disbursements for per-unit staff.

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-05-20
"""
from alembic import op

revision = "i3j4k5l6m7n8"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_staff_payments_staff_month_year",
        "staff_payments",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_staff_payments_staff_month_year",
        "staff_payments",
        ["staff_id", "payment_month", "payment_year"],
    )
