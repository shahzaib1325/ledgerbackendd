"""add rejection fields to sale_returns

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-12

"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sale_returns', sa.Column('rejected_by', sa.Integer(), nullable=True))
    op.add_column('sale_returns', sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sale_returns', sa.Column('rejection_reason', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_sale_returns_rejected_by_users',
        'sale_returns', 'users',
        ['rejected_by'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_sale_returns_rejected_by_users', 'sale_returns', type_='foreignkey')
    op.drop_column('sale_returns', 'rejection_reason')
    op.drop_column('sale_returns', 'rejected_at')
    op.drop_column('sale_returns', 'rejected_by')
