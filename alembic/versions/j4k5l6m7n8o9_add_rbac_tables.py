"""add dynamic RBAC tables, seed permissions and Super Admin

Replaces the static user_role enum with a dynamic role/permission system:
  User -> user_roles -> Role -> role_permissions -> Permission

Upgrade steps:
  1. Create roles, permissions, role_permissions, user_roles, rbac_activity_logs
  2. Seed all permissions from the code registry
  3. Create the 'Super Admin' system role with every permission
  4. Attach existing admin user(s) to Super Admin (or create the default admin)
  5. Drop the uq_one_admin index, users.role column, the old roles_permissions
     table, and the user_role enum type

WARNING: this is a destructive migration (drops users.role). Back up the
database before running it.

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rbac import PERMISSION_REGISTRY, SUPER_ADMIN_NAME, SUPER_ADMIN_SLUG

revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ADMIN_EMAIL = "admin@smartledger.com"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "AdminPass1!"
DEFAULT_ADMIN_NAME = "Super Administrator"


def upgrade() -> None:
    # ── 1. Tables ─────────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_system_role", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("idx_roles_slug", "roles", ["slug"], unique=False)

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("permission_key", sa.String(length=110), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_system_permission", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("permission_key"),
    )
    op.create_index("idx_permissions_key", "permissions", ["permission_key"], unique=False)
    op.create_index("idx_permissions_module", "permissions", ["module"], unique=False)

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    op.create_index("idx_role_permissions_role", "role_permissions", ["role_id"], unique=False)
    op.create_index("idx_role_permissions_permission", "role_permissions", ["permission_id"], unique=False)

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assigned_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    op.create_index("idx_user_roles_user", "user_roles", ["user_id"], unique=False)
    op.create_index("idx_user_roles_role", "user_roles", ["role_id"], unique=False)

    op.create_table(
        "rbac_activity_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_rbac_logs_user", "rbac_activity_logs", ["user_id"], unique=False)
    op.create_index("idx_rbac_logs_module", "rbac_activity_logs", ["module"], unique=False)
    op.create_index("idx_rbac_logs_action", "rbac_activity_logs", ["action"], unique=False)
    op.create_index("idx_rbac_logs_created_at", "rbac_activity_logs", ["created_at"], unique=False)

    conn = op.get_bind()

    # ── 2. Seed permissions ───────────────────────────────────────────────────
    for entry in PERMISSION_REGISTRY:
        conn.execute(
            sa.text(
                "INSERT INTO permissions (module, action, permission_key, description, "
                "is_system_permission, created_at, updated_at) "
                "VALUES (:module, :action, :key, :description, true, now(), now())"
            ),
            {
                "module": entry["module"],
                "action": entry["action"],
                "key": entry["permission_key"],
                "description": entry["description"],
            },
        )

    # ── 3. Super Admin role + grant every permission ─────────────────────────
    role_id = conn.execute(
        sa.text(
            "INSERT INTO roles (name, slug, description, is_system_role, is_active, "
            "created_at, updated_at) "
            "VALUES (:name, :slug, :description, true, true, now(), now()) RETURNING id"
        ),
        {
            "name": SUPER_ADMIN_NAME,
            "slug": SUPER_ADMIN_SLUG,
            "description": "Full, unrestricted access to every module. System role.",
        },
    ).scalar_one()

    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT :role_id, id FROM permissions"
        ),
        {"role_id": role_id},
    )

    # ── 4. Attach existing admin user(s) — or create the default admin ───────
    admin_ids = conn.execute(
        sa.text("SELECT id FROM users WHERE role = 'admin'")
    ).scalars().all()

    if not admin_ids:
        from app.core.security import hash_password

        new_id = conn.execute(
            sa.text(
                "INSERT INTO users (username, email, hashed_password, full_name, "
                "is_active, created_at, updated_at) "
                "VALUES (:u, :e, :p, :n, true, now(), now()) RETURNING id"
            ),
            {
                "u": DEFAULT_ADMIN_USERNAME,
                "e": DEFAULT_ADMIN_EMAIL,
                "p": hash_password(DEFAULT_ADMIN_PASSWORD),
                "n": DEFAULT_ADMIN_NAME,
            },
        ).scalar_one()
        admin_ids = [new_id]

    for uid in admin_ids:
        conn.execute(
            sa.text(
                "INSERT INTO user_roles (user_id, role_id, assigned_at) "
                "VALUES (:uid, :rid, now())"
            ),
            {"uid": uid, "rid": role_id},
        )

    # ── 5. Drop the legacy enum-based RBAC ────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS uq_one_admin")
    op.drop_column("users", "role")
    op.drop_table("roles_permissions")
    op.execute("DROP TYPE IF EXISTS user_role")


def downgrade() -> None:
    # Recreate the user_role enum and the static structures.
    user_role = postgresql.ENUM("admin", "manager", "staff", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "role",
            user_role,
            server_default="staff",
            nullable=False,
        ),
    )

    op.create_table(
        "roles_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("can_read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("can_write", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("can_delete", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role", "module", name="uq_roles_permissions_role_module"),
    )

    op.drop_index("idx_rbac_logs_created_at", table_name="rbac_activity_logs")
    op.drop_index("idx_rbac_logs_action", table_name="rbac_activity_logs")
    op.drop_index("idx_rbac_logs_module", table_name="rbac_activity_logs")
    op.drop_index("idx_rbac_logs_user", table_name="rbac_activity_logs")
    op.drop_table("rbac_activity_logs")

    op.drop_index("idx_user_roles_role", table_name="user_roles")
    op.drop_index("idx_user_roles_user", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_index("idx_role_permissions_permission", table_name="role_permissions")
    op.drop_index("idx_role_permissions_role", table_name="role_permissions")
    op.drop_table("role_permissions")

    op.drop_index("idx_permissions_module", table_name="permissions")
    op.drop_index("idx_permissions_key", table_name="permissions")
    op.drop_table("permissions")

    op.drop_index("idx_roles_slug", table_name="roles")
    op.drop_table("roles")
