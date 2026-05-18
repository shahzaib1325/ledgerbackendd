"""
Dashboard consolidated response schema.
Single endpoint returns all data needed by the frontend dashboard.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class DashboardKPIs(BaseModel):
    total_cash: str | None
    account_count: int
    revenue: str
    revenue_previous: str
    net_profit: str
    net_profit_previous: str
    total_receivable: str


class MonthRevenue(BaseModel):
    label: str
    value: str | None
    is_current: bool


class ActivityFeedItem(BaseModel):
    id: str
    type: str          # sale | purchase | sale_return | purchase_return
    reference: str
    date: str
    amount: str
    status: str
    href_id: int


class LowStockItem(BaseModel):
    item_id: int
    item_name: str
    sku: str | None
    current_stock: str
    reorder_level: str


class OverdueSale(BaseModel):
    id: int
    invoice_no: str
    due_date: str
    due_amount: str


class DashboardResponse(BaseModel):
    kpis: DashboardKPIs
    monthly_revenue: list[MonthRevenue]
    activity_feed: list[ActivityFeedItem]
    low_stock_items: list[LowStockItem]
    low_stock_count: int
    overdue_sales: list[OverdueSale]
