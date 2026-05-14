"""fix balance_type server defaults

Revision ID: d28f20ecaaeb
Revises: a5e87f75ee17
Create Date: 2026-04-21 16:47:31.240517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd28f20ecaaeb'
down_revision: Union[str, None] = 'a5e87f75ee17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop stale column from suppliers table
    op.drop_column('suppliers', 'opening_balance_type')

    # Fix customers.balance_type server default — must be 'receivable' (customer owes us).
    # Alembic does not auto-detect server_default changes; this is a manual correction.
    op.alter_column(
        'customers',
        'balance_type',
        server_default=sa.text("'receivable'::balance_type"),
    )


def downgrade() -> None:
    # Revert customers.balance_type server default
    op.alter_column(
        'customers',
        'balance_type',
        server_default=sa.text("'payable'::balance_type"),
    )

    # Re-add the stale column to suppliers
    op.add_column('suppliers', sa.Column(
        'opening_balance_type',
        postgresql.ENUM('payable', 'receivable', name='balance_type'),
        server_default=sa.text("'payable'::balance_type"),
        autoincrement=False,
        nullable=False,
    ))
