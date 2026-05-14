"""
Reports endpoints — all read-only, manager/admin access.

  GET /reports/profit-loss              — P&L for a date range
  GET /reports/sales-summary            — sales totals + customer breakdown
  GET /reports/purchase-summary         — purchase totals + supplier breakdown
  GET /reports/stock-summary            — current stock levels per item
  GET /reports/stock-movements          — stock movement log
  GET /reports/customer-balances        — all customer outstanding balances
  GET /reports/supplier-balances        — all supplier outstanding balances
  GET /reports/cash-flow                — account-level cash flow for a date range
  GET /reports/payroll-summary          — monthly payroll disbursement
  GET /reports/production-summary       — production orders + costs for a date range

Export routes:
  POST /reports/{report_name}/export    — enqueue async export job
  GET  /reports/exports/{job_id}        — poll job status
  GET  /reports/exports/{job_id}/download — stream completed file

RBAC:
  read → manager, admin  (staff excluded — reports are financial)
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arq_pool import get_arq_pool
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.models.enums import BalanceType, MovementType
from app.schemas.common import SuccessResponse
from app.schemas.reports import (
    CashFlowReport,
    CustomerBalanceReport,
    ExportFormat,
    ExportJobOut,
    PayrollSummaryReport,
    ProductionSummaryReport,
    ProfitLossReport,
    PurchaseSummaryReport,
    SalesSummaryReport,
    StockMovementReport,
    StockSummaryReport,
    SupplierBalanceReport,
)
from app.services import export_service, report_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
ReadDep = Annotated[User, Depends(require_permission("reports", "read"))]


def _mime(fmt: str) -> str:
    return (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "xlsx"
        else "text/csv"
    )


# ── Profit & Loss ─────────────────────────────────────────────────────────────

@router.get("/profit-loss", summary="Profit & Loss report for a date range")
async def profit_loss(
    db: DbDep,
    _: ReadDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[ProfitLossReport]:
    report = await report_service.profit_loss(db, date_from, date_to)
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=profit-loss.{format}"},
        )
    return SuccessResponse(data=report)


# ── Sales Summary ─────────────────────────────────────────────────────────────

@router.get("/sales-summary", summary="Sales summary with per-customer breakdown")
async def sales_summary(
    db: DbDep,
    _: ReadDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[SalesSummaryReport]:
    report = await report_service.sales_summary(db, date_from, date_to)
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=sales-summary.{format}"},
        )
    return SuccessResponse(data=report)


# ── Purchase Summary ──────────────────────────────────────────────────────────

@router.get("/purchase-summary", summary="Purchase summary with per-supplier breakdown")
async def purchase_summary(
    db: DbDep,
    _: ReadDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[PurchaseSummaryReport]:
    report = await report_service.purchase_summary(db, date_from, date_to)
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=purchase-summary.{format}"},
        )
    return SuccessResponse(data=report)


# ── Stock Summary ─────────────────────────────────────────────────────────────

@router.get("/stock-summary", summary="Current stock levels for all items")
async def stock_summary(
    db: DbDep,
    _: ReadDep,
    category_id: Annotated[int | None, Query()] = None,
    below_reorder_only: Annotated[bool, Query()] = False,
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[StockSummaryReport]:
    report = await report_service.stock_summary(
        db, category_id=category_id, below_reorder_only=below_reorder_only
    )
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=stock-summary.{format}"},
        )
    return SuccessResponse(data=report)


# ── Stock Movements ───────────────────────────────────────────────────────────

@router.get("/stock-movements", summary="Stock movement log for a date range")
async def stock_movements(
    db: DbDep,
    _: ReadDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    item_id: Annotated[int | None, Query()] = None,
    movement_type: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[StockMovementReport]:
    report = await report_service.stock_movements(
        db, date_from, date_to,
        item_id=item_id,
        movement_type=movement_type,
        page=page,
        limit=limit,
    )
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=stock-movements.{format}"},
        )
    return SuccessResponse(data=report)


# ── Customer Balances ─────────────────────────────────────────────────────────

@router.get("/customer-balances", summary="Outstanding balances for all customers")
async def customer_balances(
    db: DbDep,
    _: ReadDep,
    balance_type: Annotated[BalanceType | None, Query()] = None,
    min_balance: Annotated[Decimal | None, Query(ge=0)] = None,
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[CustomerBalanceReport]:
    report = await report_service.customer_balances(
        db,
        balance_type=balance_type.value if balance_type else None,
        min_balance=min_balance,
    )
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=customer-balances.{format}"},
        )
    return SuccessResponse(data=report)


# ── Supplier Balances ─────────────────────────────────────────────────────────

@router.get("/supplier-balances", summary="Outstanding balances for all suppliers")
async def supplier_balances(
    db: DbDep,
    _: ReadDep,
    balance_type: Annotated[BalanceType | None, Query()] = None,
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[SupplierBalanceReport]:
    report = await report_service.supplier_balances(
        db,
        balance_type=balance_type.value if balance_type else None,
    )
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=supplier-balances.{format}"},
        )
    return SuccessResponse(data=report)


# ── Cash Flow ─────────────────────────────────────────────────────────────────

@router.get("/cash-flow", summary="Account-level cash flow for a date range")
async def cash_flow(
    db: DbDep,
    _: ReadDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[CashFlowReport]:
    report = await report_service.cash_flow(db, date_from, date_to)
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=cash-flow.{format}"},
        )
    return SuccessResponse(data=report)


# ── Payroll Summary ───────────────────────────────────────────────────────────

@router.get("/payroll-summary", summary="Payroll disbursement for a given month/year")
async def payroll_summary(
    db: DbDep,
    _: ReadDep,
    payment_month: Annotated[int, Query(ge=1, le=12)],
    payment_year: Annotated[int, Query(ge=2000, le=2100)],
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[PayrollSummaryReport]:
    report = await report_service.payroll_summary(db, payment_month, payment_year)
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=payroll-summary.{format}"},
        )
    return SuccessResponse(data=report)


# ── Production Summary ────────────────────────────────────────────────────────

@router.get("/production-summary", summary="Production orders and costs for a date range")
async def production_summary(
    db: DbDep,
    _: ReadDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    format: Annotated[ExportFormat | None, Query()] = None,
) -> SuccessResponse[ProductionSummaryReport]:
    report = await report_service.production_summary(db, date_from, date_to)
    if format:
        rows = export_service.report_to_rows(report)
        content = (
            export_service.rows_to_xlsx_bytes(rows)
            if format == "xlsx"
            else export_service.rows_to_csv_bytes(rows)
        )
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=production-summary.{format}"},
        )
    return SuccessResponse(data=report)


# ── Async Export routes ───────────────────────────────────────────────────────

@router.post("/{report_name}/export", summary="Enqueue an async export job")
async def enqueue_export(
    current_user: ReadDep,
    report_name: Annotated[str, Path()],
    fmt: Annotated[ExportFormat, Query()] = "csv",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    payment_month: Annotated[int | None, Query(ge=1, le=12)] = None,
    payment_year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    category_id: Annotated[int | None, Query()] = None,
    below_reorder_only: Annotated[bool, Query()] = False,
    item_id: Annotated[int | None, Query()] = None,
) -> SuccessResponse[ExportJobOut]:
    if export_service.get_report_fn(report_name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown report: {report_name}")

    # Serialize date params to ISO strings (JSON-safe for ARQ)
    params: dict = {}
    if date_from is not None:
        params["date_from"] = date_from.isoformat()
    if date_to is not None:
        params["date_to"] = date_to.isoformat()
    if payment_month is not None:
        params["payment_month"] = payment_month
    if payment_year is not None:
        params["payment_year"] = payment_year
    if category_id is not None:
        params["category_id"] = category_id
    if below_reorder_only:
        params["below_reorder_only"] = below_reorder_only
    if item_id is not None:
        params["item_id"] = item_id

    pool = await get_arq_pool()
    job_out = await export_service.enqueue_export(
        pool, report_name, params, fmt, current_user.id
    )
    return SuccessResponse(data=job_out)


@router.get("/exports/{job_id}", summary="Poll async export job status")
async def export_status(
    _: ReadDep,
    job_id: Annotated[str, Path()],
) -> SuccessResponse[ExportJobOut]:
    pool = await get_arq_pool()
    status = await export_service.get_export_status(pool, job_id)
    return SuccessResponse(data=status)


@router.get("/exports/{job_id}/download", summary="Download a completed export file")
async def export_download(
    _: ReadDep,
    job_id: Annotated[str, Path()],
) -> FileResponse:
    for fmt in ("csv", "xlsx"):
        path = export_service.export_file_path(job_id, fmt)
        if os.path.isfile(path):
            media_type = _mime(fmt)
            return FileResponse(
                path,
                media_type=media_type,
                filename=f"export-{job_id}.{fmt}",
            )
    raise HTTPException(status_code=404, detail="Export file not found or not yet ready")
