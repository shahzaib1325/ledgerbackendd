"""Pydantic schemas for the Audit Log module (read-only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import AuditAction


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None
    action: AuditAction
    table_name: str
    record_id: int
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    request_id: str | None
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    limit: int
