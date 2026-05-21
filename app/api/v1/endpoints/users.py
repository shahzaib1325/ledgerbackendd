"""
User management endpoints — listing users, creating them, assigning roles,
toggling status, and deletion.

Password changes remain in /auth. Cache invalidation happens here, after
db.commit().
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.core.exceptions import NotFoundException, ValidationException
from app.core.rbac import (
    SUPER_ADMIN_SLUG,
    invalidate_permission_cache,
    resolve_user_permissions,
)
from app.core.redis import get_redis
from app.models.auth import User
from app.repositories.rbac_repo import rbac_repo
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.rbac import (
    AssignUserRolesRequest,
    CreateUserRequest,
    UserListOut,
    UserPermissionsOut,
    UserRoleBrief,
    UserStatusRequest,
)
from app.services import auth_service, rbac_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ReadDep = Annotated[User, Depends(require_permission("users", "read"))]
WriteDep = Annotated[User, Depends(require_permission("users", "write"))]
DeleteDep = Annotated[User, Depends(require_permission("users", "delete"))]


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


# ── GET /users ────────────────────────────────────────────────────────────────

@router.get("", summary="List users with their assigned roles")
async def list_users(
    db: DbDep,
    _: ReadDep,
    search: str | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[UserListOut]:
    users, total = await rbac_repo.list_users(
        db, search=search, is_active=is_active, skip=(page - 1) * limit, limit=limit
    )
    items = [UserListOut.model_validate(u) for u in users]
    return PaginatedResponse.build(items, total=total, page=page, limit=limit)


# ── POST /users ───────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a user")
async def create_user(
    body: CreateUserRequest,
    db: DbDep,
    redis: RedisDep,
    request: Request,
    current_user: WriteDep,
) -> SuccessResponse[UserListOut]:
    try:
        user = await auth_service.register_user(
            db,
            username=body.username,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
        )
    except ValueError as exc:
        await db.rollback()
        raise ValidationException(str(exc), field="password") from exc

    if body.role_ids:
        ip, ua = _client_meta(request)
        await rbac_service.assign_user_roles(
            db,
            user_id=user.id,
            role_ids=body.role_ids,
            actor_id=current_user.id,
            ip=ip,
            user_agent=ua,
        )
    await db.commit()
    await invalidate_permission_cache(redis)

    created = await rbac_repo.get_user(db, user.id)
    return SuccessResponse(data=UserListOut.model_validate(created))


# ── GET /users/{id}/permissions ───────────────────────────────────────────────

@router.get(
    "/{user_id}/permissions",
    summary="Get a user's final (flattened) permissions",
)
async def get_user_permissions(
    user_id: int,
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[UserPermissionsOut]:
    user = await rbac_repo.get_user(db, user_id)
    if user is None:
        raise NotFoundException("User not found.")
    perms = await resolve_user_permissions(db, user_id)
    return SuccessResponse(
        data=UserPermissionsOut(
            user_id=user_id,
            roles=[UserRoleBrief.model_validate(r) for r in user.roles],
            permissions=sorted(perms),
        )
    )


# ── POST /users/{id}/roles ────────────────────────────────────────────────────

@router.post("/{user_id}/roles", summary="Replace a user's role assignments")
async def assign_user_roles(
    user_id: int,
    body: AssignUserRolesRequest,
    db: DbDep,
    redis: RedisDep,
    request: Request,
    current_user: WriteDep,
) -> SuccessResponse[UserPermissionsOut]:
    ip, ua = _client_meta(request)
    await rbac_service.assign_user_roles(
        db,
        user_id=user_id,
        role_ids=body.role_ids,
        actor_id=current_user.id,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    await invalidate_permission_cache(redis)

    user = await rbac_repo.get_user(db, user_id)
    perms = await resolve_user_permissions(db, user_id)
    return SuccessResponse(
        data=UserPermissionsOut(
            user_id=user_id,
            roles=[UserRoleBrief.model_validate(r) for r in user.roles],
            permissions=sorted(perms),
        )
    )


# ── PATCH /users/{id} ─────────────────────────────────────────────────────────

@router.patch("/{user_id}", summary="Activate or deactivate a user")
async def set_user_status(
    user_id: int,
    body: UserStatusRequest,
    db: DbDep,
    redis: RedisDep,
    current_user: WriteDep,
) -> SuccessResponse[UserListOut]:
    user = await rbac_repo.get_user(db, user_id)
    if user is None:
        raise NotFoundException("User not found.")

    # Last-Super-Admin guard: never deactivate the only remaining one.
    if not body.is_active and user.is_active:
        if any(r.slug == SUPER_ADMIN_SLUG for r in user.roles):
            remaining = await rbac_repo.active_super_admin_count(
                db, exclude_user_id=user_id
            )
            if remaining == 0:
                raise ValidationException(
                    "Cannot deactivate the last Super Admin.",
                    code="LAST_SUPER_ADMIN",
                )

    user.is_active = body.is_active
    db.add(user)
    await rbac_repo.add_activity_log(
        db,
        user_id=current_user.id,
        action="user.status_changed",
        module="rbac",
        target_type="user",
        target_id=user_id,
        new_value={"is_active": body.is_active},
    )
    await db.commit()
    await invalidate_permission_cache(redis)

    user = await rbac_repo.get_user(db, user_id)
    return SuccessResponse(data=UserListOut.model_validate(user))


# ── DELETE /users/{id} ────────────────────────────────────────────────────────

@router.delete("/{user_id}", summary="Delete a user")
async def delete_user(
    user_id: int,
    db: DbDep,
    redis: RedisDep,
    current_user: DeleteDep,
) -> SuccessResponse[None]:
    if user_id == current_user.id:
        raise ValidationException(
            "You cannot delete your own account.", code="SELF_DELETE"
        )

    user = await rbac_repo.get_user(db, user_id)
    if user is None:
        raise NotFoundException("User not found.")

    # Last-Super-Admin guard.
    if any(r.slug == SUPER_ADMIN_SLUG for r in user.roles):
        remaining = await rbac_repo.active_super_admin_count(
            db, exclude_user_id=user_id
        )
        if remaining == 0:
            raise ValidationException(
                "Cannot delete the last Super Admin.", code="LAST_SUPER_ADMIN"
            )

    await rbac_repo.add_activity_log(
        db,
        user_id=current_user.id,
        action="user.deleted",
        module="rbac",
        target_type="user",
        target_id=user_id,
        old_value={"username": user.username, "email": user.email},
    )
    await db.delete(user)
    await db.commit()
    await invalidate_permission_cache(redis)
    return SuccessResponse(data=None)
