"""
Dashboard endpoint — single consolidated API call for the frontend dashboard.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.schemas.common import SuccessResponse
from app.schemas.dashboard import DashboardResponse
from app.services import dashboard_service

from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["Dashboard"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("dashboard", "read"))]


@router.get("/dashboard", summary="Consolidated dashboard data")
async def get_dashboard(
    db: DbDep,
    _: ReadDep,
    period: Literal["this_month", "last_month", "this_quarter"] = Query("this_month"),
) -> SuccessResponse[DashboardResponse]:
    data = await dashboard_service.get_dashboard(db, period=period)
    return SuccessResponse(data=data)
