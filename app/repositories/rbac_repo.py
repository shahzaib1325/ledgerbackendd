"""
Repository for the RBAC / administration module — data access only.

No business rules here (system-role protection, last-Super-Admin guard,
cache invalidation): those live in app/services/rbac_service.py.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import SUPER_ADMIN_SLUG
from app.models.auth import User
from app.models.rbac import (
    Permission,
    RbacActivityLog,
    Role,
    RolePermission,
    UserRole,
)


class RbacRepository:

    # ── Permissions ───────────────────────────────────────────────────────────

    async def list_permissions(self, db: AsyncSession) -> list[Permission]:
        result = await db.execute(
            select(Permission).order_by(Permission.module, Permission.action)
        )
        return list(result.scalars().all())

    async def get_permissions_by_keys(
        self, db: AsyncSession, keys: list[str]
    ) -> list[Permission]:
        if not keys:
            return []
        result = await db.execute(
            select(Permission).where(Permission.permission_key.in_(keys))
        )
        return list(result.scalars().all())

    # ── Roles ─────────────────────────────────────────────────────────────────

    async def get_role(self, db: AsyncSession, role_id: int) -> Role | None:
        result = await db.execute(
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.id == role_id)
        )
        return result.scalar_one_or_none()

    async def get_role_by_slug(self, db: AsyncSession, slug: str) -> Role | None:
        result = await db.execute(select(Role).where(Role.slug == slug))
        return result.scalar_one_or_none()

    async def get_role_by_name(self, db: AsyncSession, name: str) -> Role | None:
        result = await db.execute(
            select(Role).where(func.lower(Role.name) == name.lower())
        )
        return result.scalar_one_or_none()

    async def list_roles(
        self,
        db: AsyncSession,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Role], int]:
        conditions = []
        if search:
            conditions.append(Role.name.ilike(f"%{search}%"))
        if is_active is not None:
            conditions.append(Role.is_active == is_active)

        stmt = select(Role).options(selectinload(Role.permissions))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Role.is_system_role.desc(), Role.name)

        total = (
            await db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def create_role(
        self,
        db: AsyncSession,
        *,
        name: str,
        slug: str,
        description: str | None,
        is_active: bool,
        is_system_role: bool = False,
    ) -> Role:
        role = Role(
            name=name,
            slug=slug,
            description=description,
            is_active=is_active,
            is_system_role=is_system_role,
        )
        db.add(role)
        await db.flush()
        await db.refresh(role)
        return role

    async def update_role(
        self, db: AsyncSession, role: Role, fields: dict[str, Any]
    ) -> Role:
        for key, value in fields.items():
            setattr(role, key, value)
        db.add(role)
        await db.flush()
        await db.refresh(role)
        return role

    async def delete_role(self, db: AsyncSession, role: Role) -> None:
        await db.delete(role)
        await db.flush()

    # ── Role ↔ permission grants ──────────────────────────────────────────────

    async def set_role_permissions(
        self, db: AsyncSession, role_id: int, permission_ids: list[int]
    ) -> None:
        """Replace a role's permission grants in a single transaction."""
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        if permission_ids:
            db.add_all(
                RolePermission(role_id=role_id, permission_id=pid)
                for pid in permission_ids
            )
        await db.flush()

    # ── Counts ────────────────────────────────────────────────────────────────

    async def permission_counts(self, db: AsyncSession) -> dict[int, int]:
        """role_id → number of granted permissions."""
        result = await db.execute(
            select(RolePermission.role_id, func.count())
            .group_by(RolePermission.role_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def user_counts(self, db: AsyncSession) -> dict[int, int]:
        """role_id → number of users assigned the role."""
        result = await db.execute(
            select(UserRole.role_id, func.count()).group_by(UserRole.role_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def role_user_count(self, db: AsyncSession, role_id: int) -> int:
        result = await db.execute(
            select(func.count()).select_from(UserRole).where(
                UserRole.role_id == role_id
            )
        )
        return result.scalar_one()

    async def active_super_admin_count(
        self, db: AsyncSession, *, exclude_user_id: int | None = None
    ) -> int:
        """Count active users holding the active Super Admin role."""
        conditions = [
            Role.slug == SUPER_ADMIN_SLUG,
            Role.is_active.is_(True),
            User.is_active.is_(True),
        ]
        if exclude_user_id is not None:
            conditions.append(User.id != exclude_user_id)
        result = await db.execute(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(and_(*conditions))
        )
        return result.scalar_one()

    # ── Users / role assignment ───────────────────────────────────────────────

    async def get_user(self, db: AsyncSession, user_id: int) -> User | None:
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        db: AsyncSession,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[User], int]:
        conditions = []
        if search:
            like = f"%{search}%"
            conditions.append(
                User.full_name.ilike(like)
                | User.username.ilike(like)
                | User.email.ilike(like)
            )
        if is_active is not None:
            conditions.append(User.is_active == is_active)

        stmt = select(User).options(selectinload(User.roles))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(User.full_name)

        total = (
            await db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().unique().all()), total

    async def roles_by_ids(self, db: AsyncSession, role_ids: list[int]) -> list[Role]:
        if not role_ids:
            return []
        result = await db.execute(select(Role).where(Role.id.in_(role_ids)))
        return list(result.scalars().all())

    async def set_user_roles(
        self,
        db: AsyncSession,
        user_id: int,
        role_ids: list[int],
        *,
        assigned_by: int | None,
    ) -> None:
        """Replace a user's role assignments in a single transaction."""
        await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        if role_ids:
            db.add_all(
                UserRole(user_id=user_id, role_id=rid, assigned_by=assigned_by)
                for rid in role_ids
            )
        await db.flush()

    # ── Activity log ──────────────────────────────────────────────────────────

    async def add_activity_log(
        self,
        db: AsyncSession,
        *,
        user_id: int | None,
        action: str,
        module: str,
        target_type: str | None = None,
        target_id: int | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        db.add(
            RbacActivityLog(
                user_id=user_id,
                action=action,
                module=module,
                target_type=target_type,
                target_id=target_id,
                old_value=old_value,
                new_value=new_value,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await db.flush()

    async def list_activity_logs(
        self,
        db: AsyncSession,
        *,
        module: str | None = None,
        action: str | None = None,
        user_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[RbacActivityLog], int]:
        conditions = []
        if module:
            conditions.append(RbacActivityLog.module == module)
        if action:
            conditions.append(RbacActivityLog.action == action)
        if user_id is not None:
            conditions.append(RbacActivityLog.user_id == user_id)
        if date_from is not None:
            conditions.append(
                RbacActivityLog.created_at >= datetime.combine(date_from, datetime.min.time())
            )
        if date_to is not None:
            conditions.append(
                RbacActivityLog.created_at <= datetime.combine(date_to, datetime.max.time())
            )

        stmt = select(RbacActivityLog)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(RbacActivityLog.created_at.desc())

        total = (
            await db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        result = await db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total


rbac_repo = RbacRepository()
