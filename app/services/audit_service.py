"""
Audit logging service.

Usage in any service function:
    from app.services import audit_service

    await audit_service.log(
        db,
        user_id=actor_id,
        action=AuditAction.CREATE,
        table_name="customers",
        record_id=customer.id,
        new_values=audit_service.snapshot(customer),
    )

Rules:
  - Always called AFTER the mutation and db.flush() so record_id is populated.
  - Runs inside the SAME transaction as the mutation — rolls back together.
  - old_values must be captured BEFORE any mutation (snapshot before changes).
  - new_values is captured AFTER mutation / flush.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect as sa_inspect, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import AuditAction


# Sentinel for system-generated actions (scheduled jobs, background workers).
# Use user_id=SYSTEM_ACTOR instead of bare None to make intent explicit.
SYSTEM_ACTOR: int | None = None


def snapshot(obj: Any, _depth: int = 0) -> dict[str, Any]:
    """
    Serialise an ORM object to a plain dict safe for JSONB storage.
    Strips SQLAlchemy internal state. Converts non-JSON-native types to str.
    Depth guard at 3 prevents infinite recursion on circular relationships.
    """
    if obj is None or _depth > 3:
        return {}

    state = {}
    try:
        mapper = sa_inspect(type(obj))
        for col in mapper.columns:
            val = getattr(obj, col.key, None)
            state[col.key] = _serialise(val)
    except Exception:
        # Fallback for plain dicts or non-ORM objects
        if isinstance(obj, dict):
            state = {k: _serialise(v) for k, v in obj.items()}

    return state


def _serialise(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return str(val)
    if isinstance(val, datetime):
        return val.isoformat()
    if hasattr(val, "value"):          # Enum
        return val.value
    if isinstance(val, (int, float, bool, str)):
        return val
    return str(val)


async def log(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: AuditAction,
    table_name: str,
    record_id: int,
    old_values: dict | None = None,
    new_values: dict | None = None,
) -> None:
    """Insert one audit log row in the current transaction."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        old_values=old_values or None,
        new_values=new_values or None,
    )
    db.add(entry)
    await db.flush()


_SORTABLE = {
    "created_at": AuditLog.created_at,
    "action": AuditLog.action,
    "table_name": AuditLog.table_name,
    "user_id": AuditLog.user_id,
}


async def get_logs(
    db: AsyncSession,
    *,
    table_name: str | None = None,
    record_id: int | None = None,
    user_id: int | None = None,
    action: AuditAction | None = None,
    date_from: Any | None = None,
    date_to: Any | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    limit: int = 50,
) -> tuple[list[AuditLog], int]:
    from sqlalchemy import and_

    filters = []
    if table_name:
        filters.append(AuditLog.table_name == table_name)
    if record_id is not None:
        filters.append(AuditLog.record_id == record_id)
    if user_id is not None:
        filters.append(AuditLog.user_id == user_id)
    if action is not None:
        filters.append(AuditLog.action == action)
    if date_from is not None:
        filters.append(func.date(AuditLog.created_at) >= date_from)
    if date_to is not None:
        filters.append(func.date(AuditLog.created_at) <= date_to)

    where = and_(*filters) if filters else True

    sort_col = _SORTABLE.get(sort_by, AuditLog.created_at)
    order_expr = sort_col.desc() if sort_order == "desc" else sort_col.asc()

    count_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(where)
    )
    total = count_result.scalar_one()

    rows_result = await db.execute(
        select(AuditLog)
        .where(where)
        .order_by(order_expr)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(rows_result.scalars().all()), total
