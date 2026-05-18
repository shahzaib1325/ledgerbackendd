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

Export:
  POST /reports/{report_name}/export?fmt=csv|xlsx|pdf — generate and download

RBAC:
  read → manager, admin  (staff excluded — reports are financial)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.models.enums import BalanceType, MovementType
from app.schemas.common import SuccessResponse
from app.schemas.reports import (
    ActivityLedgerReport,
    CashFlowReport,
    CustomerBalanceReport,
    ExportFormat,
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
    if fmt == "xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if fmt == "pdf":
        return "application/pdf"
    return "text/csv"


def _export_bytes(rows: list[dict], fmt: str, title: str = "Report") -> bytes:
    if fmt == "xlsx":
        return export_service.rows_to_xlsx_bytes(rows)
    if fmt == "pdf":
        return export_service.rows_to_pdf_bytes(rows, title=title)
    return export_service.rows_to_csv_bytes(rows)


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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
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
        content = _export_bytes(rows, format)
        return StreamingResponse(
            iter([content]), media_type=_mime(format),
            headers={"Content-Disposition": f"attachment; filename=production-summary.{format}"},
        )
    return SuccessResponse(data=report)


# ── Sync Export ───────────────────────────────────────────────────────────────

@router.post("/{report_name}/export", summary="Generate and download report export")
async def export_report(
    db: DbDep,
    _: ReadDep,
    report_name: Annotated[str, Path()],
    fmt: Annotated[ExportFormat, Query()] = "csv",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    payment_month: Annotated[int | None, Query(ge=1, le=12)] = None,
    payment_year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    category_id: Annotated[int | None, Query()] = None,
    below_reorder_only: Annotated[bool, Query()] = False,
    item_id: Annotated[int | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    activity_type: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    report_fn = export_service.get_report_fn(report_name)
    if report_fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown report: {report_name}")

    kwargs: dict = {}
    if date_from is not None:
        kwargs["date_from"] = date_from
    if date_to is not None:
        kwargs["date_to"] = date_to
    if payment_month is not None:
        kwargs["payment_month"] = payment_month
    if payment_year is not None:
        kwargs["payment_year"] = payment_year
    if category_id is not None:
        kwargs["category_id"] = category_id
    if below_reorder_only:
        kwargs["below_reorder_only"] = below_reorder_only
    if item_id is not None:
        kwargs["item_id"] = item_id
    if entity_type is not None:
        kwargs["entity_type"] = entity_type
    if activity_type is not None:
        kwargs["activity_type"] = activity_type

    report = await report_fn(db, **kwargs)
    rows = export_service.report_to_rows(report)
    title = report_name.replace("-", " ").title()
    content = _export_bytes(rows, fmt, title=title)

    return StreamingResponse(
        iter([content]),
        media_type=_mime(fmt),
        headers={"Content-Disposition": f"attachment; filename={report_name}.{fmt}"},
    )


# ── Activity Ledger ──────────────────────────────────────────────────────────

@router.get("/activity-ledger", summary="Unified activity ledger across suppliers, customers, and staff")
async def activity_ledger(
    db: DbDep,
    _: ReadDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[int | None, Query()] = None,
    activity_type: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SuccessResponse[ActivityLedgerReport]:
    from app.core.exceptions import ValidationException

    # Max 90 days range to prevent heavy queries
    if (date_to - date_from).days > 90:
        raise ValidationException("Date range cannot exceed 90 days.")

    # Validate entity_type if provided
    if entity_type and entity_type not in ("supplier", "customer", "staff"):
        raise ValidationException(f"Invalid entity_type: {entity_type}. Must be supplier, customer, or staff.")

    # Validate activity_type if provided
    valid_activities = ("purchase", "sale", "payment", "return", "salary", "attendance", "production")
    if activity_type and activity_type not in valid_activities:
        raise ValidationException(f"Invalid activity_type: {activity_type}.")

    # entity_id requires entity_type
    if entity_id and not entity_type:
        raise ValidationException("entity_type is required when entity_id is specified.")

    report = await report_service.activity_ledger(
        db, date_from, date_to,
        entity_type=entity_type,
        entity_id=entity_id,
        activity_type=activity_type,
        page=page,
        limit=limit,
    )
    return SuccessResponse(data=report)
