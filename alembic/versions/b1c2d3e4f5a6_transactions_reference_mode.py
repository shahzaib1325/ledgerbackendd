"""transactions: account_id nullable, add payment_method, balance_after nullable

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-05-11

Allows transactions to be recorded without a real Account FK (reference-only
mode) so that sale/purchase/production events can be logged with just a
payment_method label (cash, bank, digital) without maintaining account balances.

Existing account-linked transactions (transfers, salary) are unaffected —
they still carry a non-null account_id.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make account_id nullable (reference-only transactions have no account FK)
    op.alter_column("transactions", "account_id", nullable=True)

    # Make balance_after nullable (no meaningful running balance without an account)
    op.alter_column("transactions", "balance_after", nullable=True)

    # Add payment_method label column (cash | bank | digital)
    op.add_column(
        "transactions",
        sa.Column("payment_method", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "payment_method")

    # Restore NOT NULL constraints (only safe if all rows have account_id / balance_after)
    op.alter_column("transactions", "balance_after", nullable=False)
    op.alter_column("transactions", "account_id", nullable=False)
