"""
Export service for the Reports module.

Two export paths:
  - Sync  (≤ EXPORT_MAX_ROWS_SYNC rows): caller streams the response directly.
  - Async (> EXPORT_MAX_ROWS_SYNC rows): enqueue ARQ job, return job_id for polling.

Report name → service function whitelist prevents arbitrary code execution.
"""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from typing import Any

from arq.connections import ArqRedis

from app.core.config import settings
from app.schemas.reports import ExportJobOut
from app.services import report_service

# Whitelist: report_name → callable that accepts (db, **params) → report object
_REPORT_REGISTRY: dict[str, Any] = {
    "profit-loss": report_service.profit_loss,
    "sales-summary": report_service.sales_summary,
    "purchase-summary": report_service.purchase_summary,
    "stock-summary": report_service.stock_summary,
    "stock-movements": report_service.stock_movements,
    "customer-balances": report_service.customer_balances,
    "supplier-balances": report_service.supplier_balances,
    "cash-flow": report_service.cash_flow,
    "payroll-summary": report_service.payroll_summary,
    "production-summary": report_service.production_summary,
}


def get_report_fn(report_name: str) -> Any | None:
    return _REPORT_REGISTRY.get(report_name)


def _ensure_export_dir() -> None:
    os.makedirs(settings.EXPORT_STORAGE_PATH, exist_ok=True)


def export_file_path(job_id: str, fmt: str) -> str:
    return os.path.join(settings.EXPORT_STORAGE_PATH, f"{job_id}.{fmt}")


def _dedup_job_id(user_id: int, report_name: str, params: dict, fmt: str) -> str:
    """
    Deterministic job ID from (user, report, params, fmt).
    ARQ reuses an existing job when enqueue_job is called with the same _job_id
    and that job is still queued or in-progress — preventing duplicate work from
    rapid repeated clicks.
    """
    key = json.dumps(
        {"u": user_id, "r": report_name, "p": params, "f": fmt},
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()[:32]


async def enqueue_export(
    pool: ArqRedis,
    report_name: str,
    params: dict,
    fmt: str,
    user_id: int,
) -> ExportJobOut:
    _ensure_export_dir()
    job_id = _dedup_job_id(user_id, report_name, params, fmt)
    job = await pool.enqueue_job(
        "generate_report_export",
        report_name,
        params,
        fmt,
        user_id,
        _job_id=job_id,
    )
    # ARQ returns None when a job with this ID already exists in Redis (still
    # queued or in-progress). Surface this explicitly so the caller knows this
    # is a reuse, not a fresh enqueue.
    if job is None:
        return await get_export_status(pool, job_id, already_running=True)

    return ExportJobOut(job_id=job_id, status="queued")


async def get_export_status(
    pool: ArqRedis,
    job_id: str,
    already_running: bool = False,
) -> ExportJobOut:
    job = await pool.job(job_id)
    if job is None:
        return ExportJobOut(job_id=job_id, status="failed", error="Job not found")

    info = await job.info()
    if info is None:
        # Key expired from Redis but job was previously known — treat as lost
        return ExportJobOut(job_id=job_id, status="failed", error="Job info unavailable")

    # info.success is None while job is queued/running, True/False once finished
    if info.success is None:
        status = "in_progress" if info.start_time is not None else "queued"
        return ExportJobOut(job_id=job_id, status=status, already_running=already_running)

    if not info.success:
        return ExportJobOut(job_id=job_id, status="failed", error="Export task raised an exception")

    # Job succeeded — read the stored result without blocking
    try:
        result = await job.result(timeout=0.01)
    except Exception:
        result = None

    if isinstance(result, dict) and result.get("error"):
        return ExportJobOut(job_id=job_id, status="failed", error=result["error"])

    return ExportJobOut(
        job_id=job_id,
        status="complete",
        download_url=f"/api/v1/reports/exports/{job_id}/download",
    )


def rows_to_csv_bytes(rows: list[dict]) -> bytes:
    import csv
    import io

    buf = io.StringIO()
    if not rows:
        return b""
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def rows_to_xlsx_bytes(rows: list[dict]) -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    if not rows:
        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([str(v) if isinstance(v, Decimal) else v for v in row.values()])

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def report_to_rows(report_obj: Any) -> list[dict]:
    """Flatten a report schema object into a list of dicts for export."""
    # Reports with a primary row list
    for attr in ("rows", "items", "customers", "suppliers", "accounts"):
        collection = getattr(report_obj, attr, None)
        if collection is not None:
            return [_model_to_dict(r) for r in collection]
    # Flat reports (e.g. ProfitLossReport)
    return [_model_to_dict(report_obj)]


def _model_to_dict(obj: Any) -> dict:
    if hasattr(obj, "model_dump"):
        return {k: str(v) if isinstance(v, Decimal) else v
                for k, v in obj.model_dump().items()}
    return dict(obj)
