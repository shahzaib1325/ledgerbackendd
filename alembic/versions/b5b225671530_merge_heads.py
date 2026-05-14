"""merge heads

Revision ID: b5b225671530
Revises: e3f1a2b4c5d6, e5f6a7b8c9d0
Create Date: 2026-05-11 07:48:07.574736

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5b225671530'
down_revision: Union[str, None] = ('e3f1a2b4c5d6', 'e5f6a7b8c9d0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
