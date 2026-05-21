"""
RBAC activity log endpoint — semantic audit trail of access-control changes
(role.created, role.permissions_updated, user.roles_updated, …).

Separate from /audit-logs, which records row-level table CRUD.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.repositories.rbac_repo import rbac_repo
from app.schemas.common import PaginatedResponse
from app.schemas.rbac import RbacActivityLogOut

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("audit", "read"))]


@router.get("", summary="List RBAC activity logs with filters")
async def list_rbac_logs(
    db: DbDep,
    _: ReadDep,
    module: str | None = Query(None),
    action: str | None = Query(None),
    user_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[RbacActivityLogOut]:
    logs, total = await rbac_repo.list_activity_logs(
        db,
        module=module,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        skip=(page - 1) * limit,
        limit=limit,
    )
    items = [RbacActivityLogOut.model_validate(log) for log in logs]
    return PaginatedResponse.build(items, total=total, page=page, limit=limit)
