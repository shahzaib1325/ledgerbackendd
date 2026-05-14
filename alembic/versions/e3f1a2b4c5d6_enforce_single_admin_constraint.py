"""enforce single admin constraint

Revision ID: e3f1a2b4c5d6
Revises: d28f20ecaaeb
Create Date: 2026-04-28

Adds a PostgreSQL partial unique index on the users table:

    CREATE UNIQUE INDEX uq_one_admin ON users (role)
    WHERE role = 'admin';

A partial unique index only indexes rows that match the WHERE clause.
Because all matching rows share the same role value ('admin'), only one
such row can exist — any INSERT or UPDATE that would create a second
admin is rejected by PostgreSQL with a unique constraint violation.

This is enforced at the database level, independent of application code.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "e3f1a2b4c5d6"
down_revision: Union[str, None] = "d28f20ecaaeb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Demote all existing admin users to 'staff' so referential integrity
    # (created_by FKs with ON DELETE RESTRICT) is preserved.
    # The seed script (scripts/create_admin.py) must be run immediately
    # after this migration to create the single authorised admin.
    op.execute("UPDATE users SET role = 'staff' WHERE role = 'admin'")

    op.execute(
        """
        CREATE UNIQUE INDEX uq_one_admin
        ON users (role)
        WHERE role = 'admin'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_one_admin")
