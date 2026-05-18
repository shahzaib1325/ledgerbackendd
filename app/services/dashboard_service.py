"""
Dashboard service — aggregates all dashboard data in a single DB session.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import text, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import report_service
from app.models.sale import SaleInvoice, SaleReturn
from app.models.purchase import Purchase, PurchaseReturn
from app.models.enums import ReturnStatus
from app.schemas.dashboard import (
    DashboardResponse,
    DashboardKPIs,
    MonthRevenue,
    ActivityFeedItem,
    LowStockItem,
    OverdueSale,
)


DashboardPeriod = Literal["this_month", "last_month", "this_quarter"]


def _last_day(year: int, month: int) -> date:
    """Return the last day of a given month."""
    _, last = calendar.monthrange(year, month)
    return date(year, month, last)


def _add_months(d: date, months: int) -> date:
    """Add N months to a date, clamping to last day of target month."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _period_dates(period: DashboardPeriod) -> tuple[date, date]:
    """Return (date_from, date_to) for the given period."""
    today = date.today()
    if period == "last_month":
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        last = today.replace(day=1) - timedelta(days=1)
        return first, last
    if period == "this_quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        first = today.replace(month=q_start_month, day=1)
        last = _last_day(first.year, first.month + 2) if first.month + 2 <= 12 else _last_day(first.year + 1, (first.month + 2) % 12)
        return first, last
    # this_month
    first = today.replace(day=1)
    last = _last_day(first.year, first.month)
    return first, last


def _previous_period_dates(period: DashboardPeriod) -> tuple[date, date]:
    """Return the comparison period dates."""
    today = date.today()
    if period == "last_month":
        ref = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        first = (ref - timedelta(days=1)).replace(day=1)
        last = ref - timedelta(days=1)
        return first, last
    if period == "this_quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        first_current = today.replace(month=q_start_month, day=1)
        prev_end = first_current - timedelta(days=1)
        prev_start_month = ((prev_end.month - 1) // 3) * 3 + 1
        first = prev_end.replace(month=prev_start_month, day=1)
        return first, prev_end
    # this_month → previous is last month
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev, last_prev


async def get_dashboard(
    db: AsyncSession,
    period: DashboardPeriod = "this_month",
) -> DashboardResponse:
    current_from, current_to = _period_dates(period)
    prev_from, prev_to = _previous_period_dates(period)

    # ── KPIs ──────────────────────────────────────────────────────────────────

    # Total cash from active accounts
    cash_row = await db.execute(text(
        "SELECT COALESCE(SUM(current_balance), 0), COUNT(*) FROM accounts WHERE is_active = true"
    ))
    cash_result = cash_row.one()
    total_cash = str(cash_result[0]) if cash_result[0] else None
    account_count = int(cash_result[1])

    # Revenue (current + previous)
    sales_current = await report_service.sales_summary(db, current_from, current_to)
    sales_previous = await report_service.sales_summary(db, prev_from, prev_to)

    # Profit/Loss (current + previous)
    pl_current = await report_service.profit_loss(db, current_from, current_to)
    pl_previous = await report_service.profit_loss(db, prev_from, prev_to)

    # Receivables
    cust_bal = await report_service.customer_balances(db)

    kpis = DashboardKPIs(
        total_cash=total_cash,
        account_count=account_count,
        revenue=str(sales_current.total_invoiced),
        revenue_previous=str(sales_previous.total_invoiced),
        net_profit=str(pl_current.net_profit),
        net_profit_previous=str(pl_previous.net_profit),
        total_receivable=str(cust_bal.total_receivable),
    )

    # ── Monthly Revenue (last 6 months) ───────────────────────────────────────

    today = date.today()
    monthly_revenue: list[MonthRevenue] = []
    for i in range(5, -1, -1):
        m_date = _add_months(today, -i)
        m_from = m_date.replace(day=1)
        m_to = _last_day(m_from.year, m_from.month)
        try:
            m_summary = await report_service.sales_summary(db, m_from, m_to)
            value = str(m_summary.total_invoiced)
        except Exception:
            value = None
        monthly_revenue.append(MonthRevenue(
            label=m_from.strftime("%b"),
            value=value,
            is_current=(i == 0),
        ))

    # ── Activity Feed (merged, sorted, top 10) ────────────────────────────────

    feed_items: list[ActivityFeedItem] = []

    # Recent sales
    recent_sales = await db.execute(
        select(SaleInvoice)
        .where(SaleInvoice.status.notin_(["draft", "void"]))
        .order_by(desc(SaleInvoice.invoice_date))
        .limit(8)
    )
    for s in recent_sales.scalars().all():
        feed_items.append(ActivityFeedItem(
            id=f"sale-{s.id}",
            type="sale",
            reference=s.invoice_no or f"INV #{s.id}",
            date=str(s.invoice_date),
            amount=str(s.total_amount),
            status=s.status.value if hasattr(s.status, "value") else str(s.status),
            href_id=s.id,
        ))

    # Recent purchases
    recent_purchases = await db.execute(
        select(Purchase)
        .where(Purchase.status.notin_(["draft", "void"]))
        .order_by(desc(Purchase.purchase_date))
        .limit(8)
    )
    for p in recent_purchases.scalars().all():
        feed_items.append(ActivityFeedItem(
            id=f"purchase-{p.id}",
            type="purchase",
            reference=p.invoice_no or f"PO #{p.id}",
            date=str(p.purchase_date),
            amount=str(p.total_amount),
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            href_id=p.id,
        ))

    # Approved sale returns
    sale_returns = await db.execute(
        select(SaleReturn)
        .where(SaleReturn.status == ReturnStatus.approved)
        .order_by(desc(SaleReturn.created_at))
        .limit(8)
    )
    for sr in sale_returns.scalars().all():
        feed_items.append(ActivityFeedItem(
            id=f"sale-return-{sr.id}",
            type="sale_return",
            reference=f"Return #{sr.id}",
            date=str(sr.return_date),
            amount=f"-{sr.refund_amount}",
            status="approved",
            href_id=sr.invoice_id,
        ))

    # Approved purchase returns
    purchase_returns = await db.execute(
        select(PurchaseReturn)
        .where(PurchaseReturn.status == ReturnStatus.approved)
        .order_by(desc(PurchaseReturn.created_at))
        .limit(8)
    )
    for pr in purchase_returns.scalars().all():
        feed_items.append(ActivityFeedItem(
            id=f"purchase-return-{pr.id}",
            type="purchase_return",
            reference=f"Return #{pr.id}",
            date=str(pr.return_date),
            amount=f"-{pr.refund_amount}",
            status="approved",
            href_id=pr.purchase_id,
        ))

    # Sort by date descending, take top 10
    feed_items.sort(key=lambda x: x.date, reverse=True)
    feed_items = feed_items[:10]

    # ── Low Stock ─────────────────────────────────────────────────────────────

    stock = await report_service.stock_summary(db, below_reorder_only=True)
    low_stock_items = [
        LowStockItem(
            item_id=item.item_id,
            item_name=item.item_name,
            sku=item.sku,
            current_stock=str(item.current_stock),
            reorder_level=str(item.reorder_level),
        )
        for item in stock.items[:5]
    ]

    # ── Overdue Sales ─────────────────────────────────────────────────────────

    overdue_result = await db.execute(
        select(SaleInvoice)
        .where(
            SaleInvoice.due_date < date.today(),
            SaleInvoice.due_amount > 0,
        )
        .order_by(SaleInvoice.due_date.asc())
        .limit(5)
    )
    overdue_sales = [
        OverdueSale(
            id=s.id,
            invoice_no=s.invoice_no or f"INV #{s.id}",
            due_date=str(s.due_date),
            due_amount=str(s.due_amount),
        )
        for s in overdue_result.scalars().all()
    ]

    return DashboardResponse(
        kpis=kpis,
        monthly_revenue=monthly_revenue,
        activity_feed=feed_items,
        low_stock_items=low_stock_items,
        low_stock_count=stock.below_reorder_count,
        overdue_sales=overdue_sales,
    )
