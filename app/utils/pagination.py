from fastapi import Query

from app.schemas.common import PaginationParams


def pagination_params(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=200, description="Items per page"),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)
