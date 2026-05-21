"""
Role management endpoints — dynamic RBAC.

All routes require the `roles` permissions. Super Admins bypass checks.
Business rules (system-role protection, last-Super-Admin guard, self-lockout
protection) live in app/services/rbac_service.py.

Cache invalidation is done HERE, after db.commit() — so a concurrent request
can never re-cache pre-commit state under the new cache version.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.core.exceptions import NotFoundException
from app.core.rbac import invalidate_permission_cache
from app.core.redis import get_redis
from app.models.auth import User
from app.models.rbac import Role
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.rbac import (
    PermissionOut,
    RoleCloneRequest,
    RoleCreateRequest,
    RoleDetailOut,
    RoleListOut,
    RolePermissionsRequest,
    RoleUpdateRequest,
)
from app.repositories.rbac_repo import rbac_repo
from app.services import rbac_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ReadDep = Annotated[User, Depends(require_permission("roles", "read"))]
WriteDep = Annotated[User, Depends(require_permission("roles", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("roles", "delete"))]


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _detail(role: Role, *, user_count: int) -> RoleDetailOut:
    return RoleDetailOut(
        id=role.id,
        name=role.name,
        slug=role.slug,
        description=role.description,
        is_system_role=role.is_system_role,
        is_active=role.is_active,
        permissions=[PermissionOut.model_validate(p) for p in role.permissions],
        user_count=user_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


# ── GET /roles ────────────────────────────────────────────────────────────────

@router.get("", summary="List roles with search, status filter and pagination")
async def list_roles(
    db: DbDep,
    _: ReadDep,
    search: str | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[RoleListOut]:
    roles, total = await rbac_repo.list_roles(
        db, search=search, is_active=is_active, skip=(page - 1) * limit, limit=limit
    )
    user_counts = await rbac_repo.user_counts(db)
    items = [
        RoleListOut(
            id=r.id,
            name=r.name,
            slug=r.slug,
            description=r.description,
            is_system_role=r.is_system_role,
            is_active=r.is_active,
            permission_count=len(r.permissions),
            user_count=user_counts.get(r.id, 0),
            created_at=r.created_at,
        )
        for r in roles
    ]
    return PaginatedResponse.build(items, total=total, page=page, limit=limit)


# ── POST /roles ───────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a role")
async def create_role(
    body: RoleCreateRequest,
    db: DbDep,
    redis: RedisDep,
    request: Request,
    current_user: WriteDep,
) -> SuccessResponse[RoleDetailOut]:
    ip, ua = _client_meta(request)
    role = await rbac_service.create_role(
        db,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        permission_keys=body.permission_keys,
        actor_id=current_user.id,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    await invalidate_permission_cache(redis)
    return SuccessResponse(data=_detail(role, user_count=0))


# ── GET /roles/{id} ───────────────────────────────────────────────────────────

@router.get("/{role_id}", summary="Get a role with its permissions")
async def get_role(
    role_id: int,
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[RoleDetailOut]:
    role = await rbac_repo.get_role(db, role_id)
    if role is None:
        raise NotFoundException("Role not found.")
    user_count = await rbac_repo.role_user_count(db, role_id)
    return SuccessResponse(data=_detail(role, user_count=user_count))


# ── PATCH /roles/{id} ─────────────────────────────────────────────────────────

@router.patch("/{role_id}", summary="Update a role (details and/or permissions)")
async def update_role(
    role_id: int,
    body: RoleUpdateRequest,
    db: DbDep,
    redis: RedisDep,
    request: Request,
    current_user: WriteDep,
) -> SuccessResponse[RoleDetailOut]:
    ip, ua = _client_meta(request)
    role = await rbac_service.update_role(
        db,
        role_id=role_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        permission_keys=body.permission_keys,
        actor_id=current_user.id,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    await invalidate_permission_cache(redis)
    user_count = await rbac_repo.role_user_count(db, role_id)
    return SuccessResponse(data=_detail(role, user_count=user_count))


# ── POST /roles/{id}/permissions ──────────────────────────────────────────────

@router.post("/{role_id}/permissions", summary="Replace a role's permissions")
async def set_role_permissions(
    role_id: int,
    body: RolePermissionsRequest,
    db: DbDep,
    redis: RedisDep,
    request: Request,
    current_user: WriteDep,
) -> SuccessResponse[RoleDetailOut]:
    ip, ua = _client_meta(request)
    role = await rbac_service.set_role_permissions(
        db,
        role_id=role_id,
        permission_keys=body.permission_keys,
        actor_id=current_user.id,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    await invalidate_permission_cache(redis)
    user_count = await rbac_repo.role_user_count(db, role_id)
    return SuccessResponse(data=_detail(role, user_count=user_count))


# ── POST /roles/{id}/clone ────────────────────────────────────────────────────

@router.post(
    "/{role_id}/clone",
    status_code=status.HTTP_201_CREATED,
    summary="Clone a role with the same permissions",
)
async def clone_role(
    role_id: int,
    body: RoleCloneRequest,
    db: DbDep,
    redis: RedisDep,
    request: Request,
    current_user: WriteDep,
) -> SuccessResponse[RoleDetailOut]:
    ip, ua = _client_meta(request)
    role = await rbac_service.clone_role(
        db,
        source_role_id=role_id,
        name=body.name,
        description=body.description,
        actor_id=current_user.id,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    await invalidate_permission_cache(redis)
    return SuccessResponse(data=_detail(role, user_count=0))


# ── DELETE /roles/{id} ────────────────────────────────────────────────────────

@router.delete("/{role_id}", summary="Delete a role")
async def delete_role(
    role_id: int,
    db: DbDep,
    redis: RedisDep,
    request: Request,
    current_user: DeleteDep,
) -> SuccessResponse[None]:
    ip, ua = _client_meta(request)
    await rbac_service.delete_role(
        db,
        role_id=role_id,
        actor_id=current_user.id,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    await invalidate_permission_cache(redis)
    return SuccessResponse(data=None)
