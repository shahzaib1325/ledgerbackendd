"""
Audit log endpoints — admin only.

  GET /audit-logs   — paginated, filterable audit trail
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.models.enums import AuditAction
from app.schemas.audit import AuditLogListOut, AuditLogOut
from app.schemas.common import SuccessResponse
from app.services import audit_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
AdminDep = Annotated[User, Depends(require_permission("audit", "read"))]


@router.get("", summary="Paginated audit log (admin only)")
async def list_audit_logs(
    db: DbDep,
    _: AdminDep,
    table_name: Annotated[str | None, Query()] = None,
    record_id: Annotated[int | None, Query()] = None,
    user_id: Annotated[int | None, Query()] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    sort_by: Annotated[str, Query()] = "created_at",
    sort_order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SuccessResponse[AuditLogListOut]:
    logs, total = await audit_service.get_logs(
        db,
        table_name=table_name,
        record_id=record_id,
        user_id=user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit,
    )
    return SuccessResponse(
        data=AuditLogListOut(
            items=[AuditLogOut.model_validate(log) for log in logs],
            total=total,
            page=page,
            limit=limit,
        )
    )
