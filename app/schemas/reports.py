"""
Pydantic schemas for the Reports module.

All report schemas are read-only (output only).

Reports available:
  - Profit & Loss summary          (revenue, COGS, gross profit, expenses, net)
  - Sales summary                  (total invoiced, collected, outstanding, by customer)
  - Purchase summary               (total purchased, paid, outstanding, by supplier)
  - Stock summary                  (current stock levels per item)
  - Stock movement report          (movements per item over a date range)
  - Customer balance report        (all customers with outstanding balances)
  - Supplier balance report        (all suppliers with outstanding balances)
  - Cash flow report               (account balances + net inflows/outflows)
  - Payroll summary                (monthly salary disbursements)
  - Production summary             (orders, quantities, costs)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

# ── Export types ──────────────────────────────────────────────────────────────

ExportFormat = Literal["csv", "xlsx"]
ExportJobStatus = Literal["queued", "in_progress", "complete", "failed"]


class ExportJobOut(BaseModel):
    job_id: str
    status: ExportJobStatus
    already_running: bool = False
    download_url: str | None = None
    error: str | None = None

from app.models.enums import (
    AccountType,
    BalanceType,
    MovementType,
    ProductionStatus,
    StaffType,
)


# ── Profit & Loss ─────────────────────────────────────────────────────────────

class ProfitLossReport(BaseModel):
    date_from: date
    date_to: date
    total_revenue: Decimal
    total_purchase_cost: Decimal
    gross_profit: Decimal
    total_salary_expense: Decimal
    total_advance_expense: Decimal
    total_production_labor_expense: Decimal
    total_other_expense: Decimal
    net_profit: Decimal


# ── Sales Summary ─────────────────────────────────────────────────────────────

class SalesSummaryReport(BaseModel):
    date_from: date
    date_to: date
    total_invoiced: Decimal
    total_collected: Decimal
    total_outstanding: Decimal
    invoice_count: int
    customer_breakdown: list["CustomerSalesRow"]


class CustomerSalesRow(BaseModel):
    customer_id: int
    customer_name: str
    invoice_count: int
    total_invoiced: Decimal
    total_collected: Decimal
    total_outstanding: Decimal


# ── Purchase Summary ──────────────────────────────────────────────────────────

class PurchaseSummaryReport(BaseModel):
    date_from: date
    date_to: date
    total_purchased: Decimal
    total_paid: Decimal
    total_outstanding: Decimal
    order_count: int
    supplier_breakdown: list["SupplierPurchaseRow"]


class SupplierPurchaseRow(BaseModel):
    supplier_id: int
    supplier_name: str
    order_count: int
    total_purchased: Decimal
    total_paid: Decimal
    total_outstanding: Decimal


# ── Stock Summary ─────────────────────────────────────────────────────────────

class StockSummaryRow(BaseModel):
    item_id: int
    item_name: str
    sku: str | None
    category_id: int | None
    category_name: str | None
    current_stock: Decimal
    reorder_level: Decimal
    is_below_reorder: bool


class StockSummaryReport(BaseModel):
    generated_at: datetime
    items: list[StockSummaryRow]
    total_items: int
    below_reorder_count: int


# ── Stock Movement ────────────────────────────────────────────────────────────

class StockMovementRow(BaseModel):
    movement_id: int
    item_id: int
    item_name: str
    movement_type: MovementType
    quantity: Decimal
    stock_after: Decimal
    reference_id: int | None
    movement_date: date
    created_at: datetime


class StockMovementReport(BaseModel):
    date_from: date
    date_to: date
    item_id: int | None
    rows: list[StockMovementRow]
    total: int


# ── Customer Balances ─────────────────────────────────────────────────────────

class CustomerBalanceRow(BaseModel):
    customer_id: int
    customer_name: str
    phone: str | None
    balance: Decimal
    balance_type: BalanceType
    credit_limit: Decimal


class CustomerBalanceReport(BaseModel):
    generated_at: datetime
    customers: list[CustomerBalanceRow]
    total_receivable: Decimal
    total_payable: Decimal


# ── Supplier Balances ─────────────────────────────────────────────────────────

class SupplierBalanceRow(BaseModel):
    supplier_id: int
    supplier_name: str
    phone: str | None
    balance: Decimal
    balance_type: BalanceType


class SupplierBalanceReport(BaseModel):
    generated_at: datetime
    suppliers: list[SupplierBalanceRow]
    total_payable: Decimal
    total_receivable: Decimal


# ── Cash Flow ─────────────────────────────────────────────────────────────────

class AccountCashFlowRow(BaseModel):
    account_id: int
    account_name: str
    account_type: AccountType
    opening_balance: Decimal
    total_credits: Decimal
    total_debits: Decimal
    closing_balance: Decimal


class CashFlowReport(BaseModel):
    date_from: date
    date_to: date
    accounts: list[AccountCashFlowRow]
    net_cash_in: Decimal
    net_cash_out: Decimal
    net_position: Decimal


# ── Payroll Summary ───────────────────────────────────────────────────────────

class PayrollSummaryRow(BaseModel):
    staff_id: int
    staff_name: str
    staff_type: StaffType
    payment_month: int
    payment_year: int
    gross_salary: Decimal
    total_allowances: Decimal
    total_deductions: Decimal
    advance_deduction: Decimal
    net_salary: Decimal


class PayrollSummaryReport(BaseModel):
    payment_month: int
    payment_year: int
    rows: list[PayrollSummaryRow]
    total_gross: Decimal
    total_net: Decimal
    total_staff_paid: int


# ── Production Summary ────────────────────────────────────────────────────────

class ProductionSummaryRow(BaseModel):
    order_id: int
    order_no: str
    product_item_id: int
    product_item_name: str
    quantity_to_produce: Decimal
    quantity_produced: Decimal
    status: ProductionStatus
    total_cost: Decimal
    start_date: date | None
    end_date: date | None


class ProductionSummaryReport(BaseModel):
    date_from: date
    date_to: date
    rows: list[ProductionSummaryRow]
    total_orders: int
    completed_orders: int
    total_production_cost: Decimal
