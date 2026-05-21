"""
Permission endpoints — read the permission catalogue, grouped by module.

Permissions are seeded from the code registry (app/core/rbac.py); admins
cannot create arbitrary permission keys. The seed endpoint only re-syncs
the registry into the database (idempotent).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.core.rbac import MODULE_LABELS, sync_permissions
from app.models.auth import User
from app.repositories.rbac_repo import rbac_repo
from app.schemas.common import SuccessResponse
from app.schemas.rbac import PermissionGroupOut, PermissionOut

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("roles", "read"))]
WriteDep = Annotated[User, Depends(require_permission("roles", "write"))]


# ── GET /permissions ──────────────────────────────────────────────────────────

@router.get("", summary="List all permissions, grouped by module")
async def list_permissions(
    db: DbDep,
    _: ReadDep,
) -> SuccessResponse[list[PermissionGroupOut]]:
    permissions = await rbac_repo.list_permissions(db)

    grouped: dict[str, list[PermissionOut]] = {}
    for perm in permissions:
        grouped.setdefault(perm.module, []).append(PermissionOut.model_validate(perm))

    groups = [
        PermissionGroupOut(
            module=module,
            label=MODULE_LABELS.get(module, module.title()),
            permissions=perms,
        )
        for module, perms in grouped.items()
    ]
    return SuccessResponse(data=groups)


# ── POST /permissions/seed ────────────────────────────────────────────────────

@router.post("/seed", summary="Re-sync the permission registry into the database")
async def seed_permissions(
    db: DbDep,
    _: WriteDep,
) -> SuccessResponse[dict[str, int]]:
    result = await sync_permissions(db)
    await db.commit()
    return SuccessResponse(data=result)
