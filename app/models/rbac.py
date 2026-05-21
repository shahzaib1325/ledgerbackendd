"""
RBAC models for SmartLedger — dynamic role/permission access control.

Model:  User → (user_roles) → Role → (role_permissions) → Permission

- Permissions are seeded from a fixed code registry (app/core/rbac.py).
  Admins never create raw permission keys; only roles + grants are dynamic.
- A user may hold multiple roles; their effective permissions are the
  de-duplicated union of every assigned role's permissions.
- System roles / system permissions cannot be deleted (enforced in service).

All FK joins are indexed for fast permission resolution.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_system_role: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions",
        lazy="selectin",
        order_by="Permission.module, Permission.action",
    )

    __table_args__ = (Index("idx_roles_slug", "slug"),)


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    permission_key: Mapped[str] = mapped_column(
        String(110), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_system_permission: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        Index("idx_permissions_key", "permission_key"),
        Index("idx_permissions_module", "module"),
    )


class RolePermission(Base):
    """Join table — which permissions belong to which role."""

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        Index("idx_role_permissions_role", "role_id"),
        Index("idx_role_permissions_permission", "permission_id"),
    )


class UserRole(Base):
    """Join table — which roles are assigned to which user."""

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assigned_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("idx_user_roles_user", "user_id"),
        Index("idx_user_roles_role", "role_id"),
    )


class RbacActivityLog(Base):
    """
    Semantic event log for RBAC changes (role.created, user.roles_updated, …).

    Separate from the row-level audit_logs table — different purpose:
    audit_logs records table/row CRUD; this records access-control events.
    """

    __tablename__ = "rbac_activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_rbac_logs_user", "user_id"),
        Index("idx_rbac_logs_module", "module"),
        Index("idx_rbac_logs_action", "action"),
        Index("idx_rbac_logs_created_at", "created_at"),
    )
