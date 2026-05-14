"""add compensation_type, salary_period to staff and create staff_categories

Revision ID: f3c9a1d2e4b5
Revises: d28f20ecaaeb
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f3c9a1d2e4b5'
down_revision: Union[str, None] = 'd28f20ecaaeb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create new enum types
    op.execute("CREATE TYPE compensation_type AS ENUM ('salary_based', 'per_unit')")
    op.execute("CREATE TYPE salary_period AS ENUM ('monthly', 'weekly')")

    # Make staff_type nullable (it was NOT NULL; existing data keeps values)
    op.alter_column('staff', 'staff_type', nullable=True)

    # Add compensation_type column (NOT NULL with default so existing rows get a value)
    op.add_column(
        'staff',
        sa.Column(
            'compensation_type',
            postgresql.ENUM('salary_based', 'per_unit', name='compensation_type', create_type=False),
            nullable=False,
            server_default=sa.text("'salary_based'::compensation_type"),
        ),
    )

    # Add salary_period column (nullable)
    op.add_column(
        'staff',
        sa.Column(
            'salary_period',
            postgresql.ENUM('monthly', 'weekly', name='salary_period', create_type=False),
            nullable=True,
        ),
    )

    # Create staff_categories join table
    op.create_table(
        'staff_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('staff_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('rate_per_unit', sa.Numeric(15, 2), nullable=True),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('staff_id', 'category_id', name='uq_staff_categories_staff_category'),
    )


def downgrade() -> None:
    op.drop_table('staff_categories')

    op.drop_column('staff', 'salary_period')
    op.drop_column('staff', 'compensation_type')

    # Restore staff_type to NOT NULL (if any NULLs exist this will fail —
    # acceptable for downgrade since we can't recover original values)
    op.alter_column('staff', 'staff_type', nullable=False)

    op.execute("DROP TYPE salary_period")
    op.execute("DROP TYPE compensation_type")
