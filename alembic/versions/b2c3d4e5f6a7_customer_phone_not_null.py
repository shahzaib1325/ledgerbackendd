"""make customer.phone NOT NULL

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE customers SET phone = '' WHERE phone IS NULL")
    op.alter_column('customers', 'phone', nullable=False)


def downgrade() -> None:
    op.alter_column('customers', 'phone', nullable=True)
