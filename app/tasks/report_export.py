"""
ARQ background task: generate_report_export

Enqueued on-demand by POST /reports/{report_name}/export when the estimated
row count exceeds EXPORT_MAX_ROWS_SYNC.

Steps:
  1. Resolve report_name → service function via export_service whitelist.
  2. Call the service function with deserialized params.
  3. Flatten result to list[dict] via export_service.report_to_rows().
  4. Serialize to CSV (stdlib) or XLSX (openpyxl).
  5. Write to {EXPORT_STORAGE_PATH}/{job_id}.{fmt}.
  6. Return {"fmt": fmt, "path": path} so get_export_status can build download URL.

Also registers: cleanup_old_exports — cron at 03:00 deletes files older than 24 h.
"""

from __future__ import annotations

import os
import structlog

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.export_service import (
    export_file_path,
    get_report_fn,
    report_to_rows,
    rows_to_csv_bytes,
    rows_to_xlsx_bytes,
)

logger = structlog.get_logger(__name__)

_PARAM_DATE_KEYS = {"date_from", "date_to"}


def _deserialize_params(params: dict) -> dict:
    """Convert ISO date strings back to date objects for report functions."""
    from datetime import date
    result = {}
    for k, v in params.items():
        if k in _PARAM_DATE_KEYS and isinstance(v, str):
            result[k] = date.fromisoformat(v)
        else:
            result[k] = v
    return result


async def generate_report_export(
    ctx: dict,
    report_name: str,
    params: dict,
    fmt: str,
    user_id: int,
) -> dict:
    """Generate and persist a report export file. Returns path metadata."""
    job_id: str = ctx["job_id"]
    logger.info(
        "generate_report_export.started",
        report_name=report_name,
        fmt=fmt,
        user_id=user_id,
        job_id=job_id,
    )

    report_fn = get_report_fn(report_name)
    if report_fn is None:
        logger.error("generate_report_export.unknown_report", report_name=report_name)
        return {"error": f"Unknown report: {report_name}"}

    try:
        deserialized = _deserialize_params(params)

        async with AsyncSessionLocal() as db:
            report_obj = await report_fn(db, **deserialized)

        rows = report_to_rows(report_obj)

        path = export_file_path(job_id, fmt)
        os.makedirs(settings.EXPORT_STORAGE_PATH, exist_ok=True)

        if fmt == "xlsx":
            content = rows_to_xlsx_bytes(rows)
        else:
            content = rows_to_csv_bytes(rows)

        with open(path, "wb") as f:
            f.write(content)

        logger.info(
            "generate_report_export.completed",
            job_id=job_id,
            rows=len(rows),
            path=path,
        )
        return {"fmt": fmt, "path": path}

    except Exception:
        logger.exception("generate_report_export.failed", job_id=job_id)
        return {"error": "Export generation failed"}


async def cleanup_old_exports(ctx: dict) -> dict:
    """Delete export files older than 24 hours. Runs nightly at 03:00."""
    import time

    export_dir = settings.EXPORT_STORAGE_PATH
    if not os.path.isdir(export_dir):
        return {"deleted": 0}

    cutoff = time.time() - 86400  # 24 hours
    deleted = 0
    for fname in os.listdir(export_dir):
        fpath = os.path.join(export_dir, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except OSError:
            logger.exception("cleanup_old_exports.delete_failed", path=fpath)

    logger.info("cleanup_old_exports.completed", deleted=deleted)
    return {"deleted": deleted}
