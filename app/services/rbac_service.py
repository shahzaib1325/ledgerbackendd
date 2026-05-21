"""
RBAC service — business logic for roles, permissions, and user-role assignment.

Enforces all RBAC invariants:
  - Role name and slug are unique.
  - System roles cannot be renamed, deactivated, deleted, or have their
    permission grants modified (the Super Admin role is always all-access).
  - A role assigned to users cannot be deleted.
  - The last active Super Admin cannot lose the Super Admin role.
  - The acting user cannot make a change that strips their own ability to
    manage roles (self-lockout protection).
  - Submitted permission keys must exist in the permission registry.

Every mutating operation writes an entry to rbac_activity_logs.

Cache invalidation is the CALLER's responsibility: the endpoint bumps the
Redis permission-cache version AFTER db.commit(), so a concurrent request
can never re-cache pre-commit state under the new version.

No FastAPI imports. Callers (endpoints) own the DB transaction commit.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.core.rbac import SUPER_ADMIN_SLUG, resolve_user_permissions
from app.models.rbac import Role
from app.repositories.rbac_repo import rbac_repo

logger = structlog.get_logger(__name__)

_MODULE = "rbac"
_ROLE_ADMIN_KEY = "roles:write"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValidationException("Role name must contain alphanumeric characters.")
    return slug


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = _slugify(name)
    slug = base
    suffix = 2
    while await rbac_repo.get_role_by_slug(db, slug) is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _serialize_role(role: Role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "slug": role.slug,
        "is_active": role.is_active,
        "permission_keys": sorted(p.permission_key for p in role.permissions),
    }


async def _assert_actor_keeps_role_access(db: AsyncSession, actor_id: int) -> None:
    """
    Self-lockout guard. Called after a change has been flushed (but not yet
    committed): re-resolves the acting user's effective permissions and aborts
    the transaction if they would lose the ability to manage roles.

    The Super Admin role grants `roles:write`, so Super Admins pass naturally.
    """
    perms = await resolve_user_permissions(db, actor_id)
    if _ROLE_ADMIN_KEY not in perms:
        raise ValidationException(
            "This change would remove your own permission to manage roles. "
            "Ask another administrator to make it instead.",
            code="SELF_LOCKOUT",
        )


# ── Roles ─────────────────────────────────────────────────────────────────────

async def create_role(
    db: AsyncSession,
    *,
    name: str,
    description: str | None,
    is_active: bool,
    permission_keys: list[str],
    actor_id: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Role:
    if await rbac_repo.get_role_by_name(db, name) is not None:
        raise ConflictException(
            f"A role named '{name}' already exists.", code="CONFLICT", field="name"
        )

    slug = await _unique_slug(db, name)
    role = await rbac_repo.create_role(
        db,
        name=name,
        slug=slug,
        description=description,
        is_active=is_active,
    )

    perm_ids = await _resolve_permission_ids(db, permission_keys)
    await rbac_repo.set_role_permissions(db, role.id, perm_ids)

    role = await rbac_repo.get_role(db, role.id)  # reload with permissions
    await rbac_repo.add_activity_log(
        db,
        user_id=actor_id,
        action="role.created",
        module=_MODULE,
        target_type="role",
        target_id=role.id,
        new_value=_serialize_role(role),
        ip_address=ip,
        user_agent=user_agent,
    )
    logger.info("role_created", role_id=role.id, actor_id=actor_id)
    return role


async def update_role(
    db: AsyncSession,
    *,
    role_id: int,
    name: str | None,
    description: str | None,
    is_active: bool | None,
    permission_keys: list[str] | None,
    actor_id: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Role:
    role = await rbac_repo.get_role(db, role_id)
    if role is None:
        raise NotFoundException("Role not found.")

    before = _serialize_role(role)
    fields: dict = {}

    if name is not None and name != role.name:
        if role.is_system_role:
            raise ValidationException(
                "System roles cannot be renamed.", code="SYSTEM_ROLE_PROTECTED"
            )
        if await rbac_repo.get_role_by_name(db, name) is not None:
            raise ConflictException(
                f"A role named '{name}' already exists.",
                code="CONFLICT",
                field="name",
            )
        fields["name"] = name

    if description is not None:
        fields["description"] = description

    if is_active is not None and is_active != role.is_active:
        if role.is_system_role:
            raise ValidationException(
                "System roles cannot be deactivated.", code="SYSTEM_ROLE_PROTECTED"
            )
        fields["is_active"] = is_active

    if fields:
        role = await rbac_repo.update_role(db, role, fields)

    # Optional atomic permission update — same request, same transaction.
    if permission_keys is not None:
        if role.is_system_role:
            raise ValidationException(
                "The Super Admin role always has every permission and cannot be edited.",
                code="SYSTEM_ROLE_PROTECTED",
            )
        perm_ids = await _resolve_permission_ids(db, permission_keys)
        await rbac_repo.set_role_permissions(db, role_id, perm_ids)

    role = await rbac_repo.get_role(db, role_id)
    await _assert_actor_keeps_role_access(db, actor_id)

    await rbac_repo.add_activity_log(
        db,
        user_id=actor_id,
        action="role.updated",
        module=_MODULE,
        target_type="role",
        target_id=role.id,
        old_value=before,
        new_value=_serialize_role(role),
        ip_address=ip,
        user_agent=user_agent,
    )
    return role


async def set_role_permissions(
    db: AsyncSession,
    *,
    role_id: int,
    permission_keys: list[str],
    actor_id: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Role:
    role = await rbac_repo.get_role(db, role_id)
    if role is None:
        raise NotFoundException("Role not found.")
    if role.is_system_role:
        raise ValidationException(
            "The Super Admin role always has every permission and cannot be edited.",
            code="SYSTEM_ROLE_PROTECTED",
        )

    before = _serialize_role(role)
    perm_ids = await _resolve_permission_ids(db, permission_keys)
    await rbac_repo.set_role_permissions(db, role_id, perm_ids)
    role = await rbac_repo.get_role(db, role_id)
    await _assert_actor_keeps_role_access(db, actor_id)

    await rbac_repo.add_activity_log(
        db,
        user_id=actor_id,
        action="role.permissions_updated",
        module=_MODULE,
        target_type="role",
        target_id=role.id,
        old_value=before,
        new_value=_serialize_role(role),
        ip_address=ip,
        user_agent=user_agent,
    )
    return role


async def clone_role(
    db: AsyncSession,
    *,
    source_role_id: int,
    name: str,
    description: str | None,
    actor_id: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Role:
    source = await rbac_repo.get_role(db, source_role_id)
    if source is None:
        raise NotFoundException("Source role not found.")
    if await rbac_repo.get_role_by_name(db, name) is not None:
        raise ConflictException(
            f"A role named '{name}' already exists.", code="CONFLICT", field="name"
        )

    slug = await _unique_slug(db, name)
    clone = await rbac_repo.create_role(
        db,
        name=name,
        description=description,
        slug=slug,
        is_active=True,
    )
    await rbac_repo.set_role_permissions(
        db, clone.id, [p.id for p in source.permissions]
    )
    clone = await rbac_repo.get_role(db, clone.id)

    await rbac_repo.add_activity_log(
        db,
        user_id=actor_id,
        action="role.cloned",
        module=_MODULE,
        target_type="role",
        target_id=clone.id,
        old_value={"source_role_id": source_role_id, "source_name": source.name},
        new_value=_serialize_role(clone),
        ip_address=ip,
        user_agent=user_agent,
    )
    return clone


async def delete_role(
    db: AsyncSession,
    *,
    role_id: int,
    actor_id: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    role = await rbac_repo.get_role(db, role_id)
    if role is None:
        raise NotFoundException("Role not found.")
    if role.is_system_role:
        raise ValidationException(
            "System roles cannot be deleted.", code="SYSTEM_ROLE_PROTECTED"
        )

    user_count = await rbac_repo.role_user_count(db, role_id)
    if user_count > 0:
        raise ConflictException(
            f"This role is assigned to {user_count} user(s). "
            "Reassign those users before deleting the role.",
            code="ROLE_IN_USE",
        )

    before = _serialize_role(role)
    await rbac_repo.delete_role(db, role)
    await rbac_repo.add_activity_log(
        db,
        user_id=actor_id,
        action="role.deleted",
        module=_MODULE,
        target_type="role",
        target_id=role_id,
        old_value=before,
        ip_address=ip,
        user_agent=user_agent,
    )


# ── User-role assignment ──────────────────────────────────────────────────────

async def assign_user_roles(
    db: AsyncSession,
    *,
    user_id: int,
    role_ids: list[int],
    actor_id: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    user = await rbac_repo.get_user(db, user_id)
    if user is None:
        raise NotFoundException("User not found.")

    unique_ids = list(dict.fromkeys(role_ids))
    found = await rbac_repo.roles_by_ids(db, unique_ids)
    if len(found) != len(unique_ids):
        raise ValidationException("One or more role IDs do not exist.")

    before_role_ids = {r.id for r in user.roles}
    new_role_slugs = {r.slug for r in found}

    # Last-Super-Admin guard: block removing the Super Admin role from the
    # only remaining active Super Admin.
    had_super_admin = any(r.slug == SUPER_ADMIN_SLUG for r in user.roles)
    losing_super_admin = had_super_admin and SUPER_ADMIN_SLUG not in new_role_slugs
    if losing_super_admin:
        remaining = await rbac_repo.active_super_admin_count(
            db, exclude_user_id=user_id
        )
        if remaining == 0:
            raise ValidationException(
                "Cannot remove the Super Admin role from the last Super Admin.",
                code="LAST_SUPER_ADMIN",
            )

    await rbac_repo.set_user_roles(db, user_id, unique_ids, assigned_by=actor_id)

    # Self-lockout guard — only relevant when editing your own roles.
    if user_id == actor_id:
        await _assert_actor_keeps_role_access(db, actor_id)

    await rbac_repo.add_activity_log(
        db,
        user_id=actor_id,
        action="user.roles_updated",
        module=_MODULE,
        target_type="user",
        target_id=user_id,
        old_value={"role_ids": sorted(before_role_ids)},
        new_value={"role_ids": sorted(unique_ids)},
        ip_address=ip,
        user_agent=user_agent,
    )


# ── Internal ──────────────────────────────────────────────────────────────────

async def _resolve_permission_ids(
    db: AsyncSession, permission_keys: list[str]
) -> list[int]:
    unique = list(dict.fromkeys(permission_keys))
    if not unique:
        return []
    perms = await rbac_repo.get_permissions_by_keys(db, unique)
    if len(perms) != len(unique):
        found = {p.permission_key for p in perms}
        missing = sorted(set(unique) - found)
        raise ValidationException(
            f"Unknown permission key(s): {', '.join(missing)}",
            code="UNKNOWN_PERMISSION",
        )
    return [p.id for p in perms]
