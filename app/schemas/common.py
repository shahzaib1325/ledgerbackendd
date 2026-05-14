from __future__ import annotations

from datetime import date
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


# ── Pagination meta ───────────────────────────────────────────────────────────

class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


# ── Response envelope ─────────────────────────────────────────────────────────
# API_CONVENTIONS.md §3 — all four fields present on every response.
#   success=true  → data=<payload>, error=null, meta=null|PaginationMeta
#   success=false → data=null,      error=<detail>, meta=null

class ApiResponse(BaseModel, Generic[T]):
    """
    Universal response envelope.

    Use SuccessResponse / ErrorResponse / PaginatedResponse factories
    instead of constructing this directly.
    """

    success: bool
    data: T | None = None
    error: ErrorDetail | None = None  # type: ignore[name-defined]
    meta: PaginationMeta | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


# Re-declare ApiResponse now that ErrorDetail is defined.
# Pydantic resolves forward references at model_rebuild time, but
# defining both in order is cleaner — forward ref works fine in practice.

class SuccessResponse(BaseModel, Generic[T]):
    """Single-object success envelope."""

    success: bool = True
    data: T
    error: ErrorDetail | None = None
    meta: PaginationMeta | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """List success envelope with pagination meta."""

    success: bool = True
    data: list[T]
    error: ErrorDetail | None = None
    meta: PaginationMeta

    @classmethod
    def build(
        cls,
        items: list[T],
        *,
        total: int,
        page: int,
        limit: int,
    ) -> "PaginatedResponse[T]":
        pages = max(1, -(-total // limit))  # ceiling division
        return cls(
            data=items,
            meta=PaginationMeta(page=page, limit=limit, total=total, pages=pages),
        )


class ErrorResponse(BaseModel):
    """Error envelope."""

    success: bool = False
    data: None = None
    error: ErrorDetail
    meta: None = None


# ── Pagination params ─────────────────────────────────────────────────────────

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


# ── Date range ────────────────────────────────────────────────────────────────

class DateRange(BaseModel):
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_range(self) -> "DateRange":
        if self.date_from > self.date_to:
            raise ValueError("date_from must be before or equal to date_to")
        return self
