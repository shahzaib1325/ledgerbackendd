"""add supplier_categories table and make supplier.phone NOT NULL

Revision ID: a1b2c3d4e5f6
Revises: f3c9a1d2e4b5
Create Date: 2026-05-09 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f3c9a1d2e4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Back-fill any NULL phone values before enforcing NOT NULL
    op.execute("UPDATE suppliers SET phone = '' WHERE phone IS NULL")

    op.alter_column('suppliers', 'phone', nullable=False)

    op.create_table(
        'supplier_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('supplier_id', 'category_id', name='uq_supplier_categories_supplier_category'),
    )


def downgrade() -> None:
    op.drop_table('supplier_categories')
    op.alter_column('suppliers', 'phone', nullable=True)
