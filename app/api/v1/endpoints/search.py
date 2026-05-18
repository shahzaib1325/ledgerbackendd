"""Global search endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.schemas.common import SuccessResponse
from app.schemas.search import SearchResponse
from app.services import search_service

router = APIRouter(tags=["Search"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("transactions", "read"))]


@router.get("/search", summary="Global search across all entities")
async def search(
    db: DbDep,
    _: ReadDep,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SuccessResponse[SearchResponse]:
    results = await search_service.global_search(db, q, limit=limit)
    return SuccessResponse(data=results)
