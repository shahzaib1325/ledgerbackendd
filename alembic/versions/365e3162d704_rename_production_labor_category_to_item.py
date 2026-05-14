"""rename_production_labor_category_to_item

Revision ID: 365e3162d704
Revises: 547c54af53db
Create Date: 2026-05-11 10:30:17.046360

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '365e3162d704'
down_revision: Union[str, None] = '547c54af53db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename category_id to item_id
    op.alter_column('production_labor', 'category_id', new_column_name='item_id')
    
    # Update foreign key
    op.drop_constraint('production_labor_category_id_fkey', 'production_labor', type_='foreignkey')
    op.create_foreign_key(None, 'production_labor', 'items', ['item_id'], ['id'], ondelete='SET NULL')

    # Ensure total_cost is NOT NULL (as per current model)
    op.alter_column('production_labor', 'total_cost',
               existing_type=sa.NUMERIC(precision=15, scale=2),
               nullable=False,
               existing_server_default=sa.Computed('(quantity_produced * rate_per_unit)', persisted=True))


def downgrade() -> None:
    op.alter_column('production_labor', 'total_cost',
               existing_type=sa.NUMERIC(precision=15, scale=2),
               nullable=True,
               existing_server_default=sa.Computed('(quantity_produced * rate_per_unit)', persisted=True))
    
    op.drop_constraint(None, 'production_labor', type_='foreignkey')
    op.create_foreign_key('production_labor_category_id_fkey', 'production_labor', 'categories', ['item_id'], ['id'], ondelete='SET NULL')
    
    op.alter_column('production_labor', 'item_id', new_column_name='category_id')
