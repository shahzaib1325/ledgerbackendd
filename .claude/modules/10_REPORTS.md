# Module 10 — Reports

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Reports |
| Prefix | `/api/v1/reports` |
| Files | `schemas/report.py`, `api/v1/endpoints/reports.py`, `services/report_service.py`, `repositories/report_repo.py` |
| Dependencies | All modules (read-only queries across all tables) |

The Reports module is **entirely read-only** — it performs no writes. It aggregates, summarizes, and presents financial and operational data in structured formats. Reports are consumed by business owners and managers to make decisions. Heavy reports use pre-computed materialized views for performance.

---

## 2. Report Categories

| Category | Reports |
|----------|---------|
| Financial | Profit & Loss, Income & Expenses |
| Inventory | Stock Report, Stock Movement |
| Sales & Purchase | Sales Report, Purchases Report |
| Account Ledgers | Customer Ledger, Supplier Ledger, General Ledger |
| Party Balances | Customer Balances, Supplier Balances, Customer Aging, Supplier Aging |
| Cash & Bank | Cash Book, Bank Book |
| Staff & Production | Staff Payments, Production Report |

---

## 3. Common Query Parameters

All reports share these base parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `from_date` | date (YYYY-MM-DD) | Start date (required for financial reports) |
| `to_date` | date (YYYY-MM-DD) | End date (required for financial reports) |
| `page` | int | Page number (default 1) |
| `limit` | int | Items per page (default 50, max 500) |
| `format` | `json`\|`csv`\|`xlsx` | Response format (default: json) |

---

## 4. Financial Reports

### 4.1 Profit & Loss Report

**Endpoint:** `GET /reports/profit-loss`

**Purpose:** Shows revenue, cost of goods, gross profit, expenses, and net profit for a period.

**Query Params:** `from_date`, `to_date`, `group_by` (daily | monthly | total)

**Response:**
```json
{
  "period": { "from": "2026-01-01", "to": "2026-03-31" },
  "revenue": {
    "total_sales": 2500000.00,
    "sales_returns": 50000.00,
    "net_sales": 2450000.00
  },
  "cost_of_goods": {
    "total_purchases": 1200000.00,
    "purchase_returns": 20000.00,
    "production_costs": 300000.00,
    "net_cogs": 1480000.00
  },
  "gross_profit": 970000.00,
  "gross_profit_margin_pct": 39.6,
  "expenses": {
    "salaries": 200000.00,
    "other_expenses": 50000.00,
    "total_expenses": 250000.00
  },
  "net_profit": 720000.00,
  "net_profit_margin_pct": 29.4,
  "by_period": [ ... ]   // if group_by != 'total'
}
```

**Query Logic:**
```sql
-- Net Sales
SELECT SUM(total_amount) FROM sale_invoices
WHERE status NOT IN ('draft', 'void') AND invoice_date BETWEEN :from AND :to

-- COGS = purchases + production costs
-- Gross Profit = Net Sales - COGS
-- Expenses = salaries + transactions WHERE reference_type='expense'
-- Net Profit = Gross Profit - Expenses
```

---

### 4.2 Income & Expenses Report

**Endpoint:** `GET /reports/income-expenses`

**Purpose:** Breakdown of all income sources and expense categories.

**Query Params:** `from_date`, `to_date`, `group_by` (monthly | total)

**Response:**
```json
{
  "income": [
    { "source": "Sales", "amount": 2450000.00 },
    { "source": "Other Income", "amount": 15000.00 }
  ],
  "total_income": 2465000.00,
  "expenses": [
    { "category": "Purchases", "amount": 1180000.00 },
    { "category": "Salaries", "amount": 200000.00 },
    { "category": "Electricity", "amount": 30000.00 },
    { "category": "Other Expenses", "amount": 20000.00 }
  ],
  "total_expenses": 1430000.00,
  "net": 1035000.00
}
```

---

## 5. Inventory Reports

### 5.1 Stock Report

**Endpoint:** `GET /reports/stock`

**Purpose:** Current stock levels and valuation for all items.

**Query Params:** `category_id`, `item_type`, `low_stock` (bool), `page`, `limit`

**Response per item:**
```json
{
  "item_id": 5,
  "name": "Basmati Rice 5kg",
  "category": "Rice",
  "unit": "kg",
  "item_type": "purchased",
  "current_stock": 1250.000,
  "reorder_level": 200.000,
  "purchase_price": 85.00,
  "sale_price": 120.00,
  "stock_value": 106250.00,
  "is_low_stock": false
}
```

**Summary footer:**
```json
{
  "total_items": 85,
  "total_stock_value": 4250000.00,
  "low_stock_count": 7
}
```

---

### 5.2 Stock Movement Report

**Endpoint:** `GET /reports/stock-movement`

**Purpose:** Complete history of all stock changes for one or all items.

**Query Params:** `item_id`, `movement_type`, `reference_type`, `from_date`, `to_date`, `page`, `limit`

**Response per row:**
```json
{
  "date": "2026-03-15",
  "item": "Basmati Rice 5kg",
  "movement_type": "purchase_in",
  "reference": "Purchase #42 / Ahmed Traders",
  "quantity_in": 500.000,
  "quantity_out": 0,
  "stock_after": 1250.000
}
```

---

## 6. Sales & Purchase Reports

### 6.1 Sales Report

**Endpoint:** `GET /reports/sales`

**Purpose:** Summary of all sales transactions in a date range.

**Query Params:** `from_date`, `to_date`, `customer_id`, `payment_type`, `status`, `group_by` (daily|monthly|customer), `page`, `limit`

**Response:**
```json
{
  "summary": {
    "total_invoices": 145,
    "total_sales": 2500000.00,
    "total_discount": 75000.00,
    "total_tax": 25000.00,
    "net_sales": 2450000.00,
    "total_collected": 2100000.00,
    "total_outstanding": 350000.00
  },
  "data": [
    {
      "invoice_no": "INV-2026-00045",
      "date": "2026-03-15",
      "customer": "Rehman Store",
      "payment_type": "credit",
      "total_amount": 45000.00,
      "paid_amount": 20000.00,
      "due_amount": 25000.00,
      "status": "partially_paid",
      "due_date": "2026-04-15",
      "is_overdue": false
    }
  ]
}
```

---

### 6.2 Purchases Report

**Endpoint:** `GET /reports/purchases`

**Purpose:** Summary of all purchase transactions.

**Query Params:** `from_date`, `to_date`, `supplier_id`, `payment_type`, `status`, `page`, `limit`

**Response:** Same structure as Sales Report but for purchases.

---

## 7. Account Ledger Reports

### 7.1 Customer Ledger

**Endpoint:** `GET /reports/ledger/customer/{customer_id}`

**Purpose:** Complete chronological ledger for a specific customer showing all invoices and payments.

**Query Params:** `from_date`, `to_date`, `page`, `limit`

**Response:**
```json
{
  "customer": { "id": 12, "name": "Rehman Store", "phone": "..." },
  "opening_balance": 50000.00,
  "closing_balance": 75000.00,
  "entries": [
    {
      "date": "2026-03-01",
      "description": "Invoice INV-2026-00032",
      "debit": 0,
      "credit": 45000.00,
      "balance": 95000.00,
      "reference_type": "sale",
      "reference_id": 32
    },
    {
      "date": "2026-03-10",
      "description": "Payment Received",
      "debit": 20000.00,
      "credit": 0,
      "balance": 75000.00,
      "reference_type": "payment",
      "reference_id": 8
    }
  ]
}
```

**Query Logic:**
Uses PostgreSQL window function for running balance:
```sql
SELECT
    date,
    description,
    debit,
    credit,
    SUM(credit - debit) OVER (ORDER BY date, id) + :opening_balance AS balance
FROM (
    SELECT invoice_date AS date, invoice_no AS description,
           0 AS debit, total_amount AS credit, id, 'sale' AS type
    FROM sale_invoices WHERE customer_id = :id AND status NOT IN ('draft','void')
    UNION ALL
    SELECT received_at::date, 'Payment Received', amount, 0, id, 'payment'
    FROM customer_payments WHERE customer_id = :id
) t
WHERE date BETWEEN :from AND :to
ORDER BY date, id
```

---

### 7.2 Supplier Ledger

**Endpoint:** `GET /reports/ledger/supplier/{supplier_id}`

**Purpose:** Same structure as customer ledger but for suppliers (purchases = credit, payments = debit).

---

### 7.3 General Ledger

**Endpoint:** `GET /reports/ledger/general`

**Purpose:** All financial transactions across all accounts in chronological order.

**Query Params:** `from_date`, `to_date`, `account_id`, `reference_type`, `page`, `limit`

**Response:**
```json
{
  "entries": [
    {
      "date": "2026-03-15",
      "account": "HBL Current Account",
      "description": "Payment to Ahmed Traders for Purchase #42",
      "reference_type": "purchase_payment",
      "debit": 50000.00,
      "credit": 0,
      "balance_after": 450000.00
    }
  ]
}
```

---

## 8. Party Balance Reports

### 8.1 Customer Balances

**Endpoint:** `GET /reports/balances/customers`

**Purpose:** Snapshot of all customer outstanding balances.

**Query Params:** `balance_type`, `min_balance`, `page`, `limit`

**Response per row:**
```json
{
  "customer_id": 12,
  "name": "Rehman Store",
  "phone": "0300-1234567",
  "credit_limit": 200000.00,
  "balance": 75000.00,
  "balance_type": "receivable",
  "credit_utilization_pct": 37.5,
  "last_transaction": "2026-03-10"
}
```

---

### 8.2 Supplier Balances

**Endpoint:** `GET /reports/balances/suppliers`

*(Same structure as customer balances)*

---

### 8.3 Customer Aging Report

**Endpoint:** `GET /reports/aging/customers`

**Purpose:** Shows how old outstanding customer balances are (for collections follow-up).

**Query Params:** `as_of_date`, `page`, `limit`

| Column | Description |
|--------|-------------|
| Customer | Name |
| Current | Not yet due |
| 1–30 Days | Overdue 1-30 days |
| 31–60 Days | Overdue 31-60 days |
| 61–90 Days | Overdue 61-90 days |
| 90+ Days | Overdue 90+ days |
| Total | Sum of all buckets |

---

### 8.4 Supplier Aging Report

**Endpoint:** `GET /reports/aging/suppliers`

*(Same structure — shows amounts owed to suppliers grouped by age)*

---

## 9. Cash & Bank Reports

### 9.1 Cash Book

**Endpoint:** `GET /reports/cash-book`

**Purpose:** Complete transaction history for cash accounts.

**Query Params:** `account_id` (filter to specific cash account), `from_date`, `to_date`, `page`, `limit`

**Response:**
```json
{
  "account": { "id": 1, "name": "Main Cash", "type": "cash" },
  "opening_balance": 250000.00,
  "closing_balance": 175000.00,
  "total_receipts": 125000.00,
  "total_payments": 200000.00,
  "entries": [
    {
      "date": "2026-03-01",
      "description": "Payment from Rehman Store — INV-2026-00032",
      "receipts": 20000.00,
      "payments": 0,
      "balance": 270000.00
    },
    {
      "date": "2026-03-02",
      "description": "Payment to Ahmed Traders — Purchase #42",
      "receipts": 0,
      "payments": 50000.00,
      "balance": 220000.00
    }
  ]
}
```

---

### 9.2 Bank Book

**Endpoint:** `GET /reports/bank-book`

*(Same structure as Cash Book but for bank/digital accounts)*

---

## 10. Staff & Production Reports

### 10.1 Staff Payments Report

**Endpoint:** `GET /reports/staff-payments`

**Purpose:** Summary of all salary disbursements.

**Query Params:** `staff_id`, `month`, `year`, `from_date`, `to_date`, `page`, `limit`

**Response:**
```json
{
  "summary": {
    "total_payments": 45,
    "total_gross": 1500000.00,
    "total_allowances": 225000.00,
    "total_deductions": 75000.00,
    "total_advances": 30000.00,
    "total_net_paid": 1620000.00
  },
  "data": [
    {
      "staff_name": "Muhammad Ali",
      "designation": "Supervisor",
      "month_year": "March 2026",
      "gross": 35000.00,
      "allowances": 5000.00,
      "deductions": 2000.00,
      "advance": 5000.00,
      "net_paid": 33000.00,
      "payment_mode": "bank",
      "paid_at": "2026-03-31"
    }
  ]
}
```

---

### 10.2 Production Report

**Endpoint:** `GET /reports/production`

**Purpose:** Summary of production orders with cost analysis.

**Query Params:** `from_date`, `to_date`, `status`, `product_item_id`, `page`, `limit`

**Response:**
```json
{
  "summary": {
    "total_orders": 12,
    "completed": 10,
    "in_progress": 1,
    "cancelled": 1,
    "total_material_cost": 800000.00,
    "total_labor_cost": 150000.00,
    "total_other_cost": 50000.00,
    "total_production_cost": 1000000.00
  },
  "data": [
    {
      "order_no": "PRD-2026-00010",
      "product": "Packaged Rice 5kg",
      "quantity_planned": 1000,
      "quantity_produced": 980,
      "status": "completed",
      "total_cost": 83000.00,
      "unit_cost": 84.69,
      "start_date": "2026-03-01",
      "end_date": "2026-03-05"
    }
  ]
}
```

---

## 11. Export Functionality

All reports support export:

**Request:**
```
GET /reports/profit-loss?from_date=2026-01-01&to_date=2026-03-31&format=xlsx
```

**Small reports (<1000 rows):** Direct streaming response
```python
return StreamingResponse(
    generate_excel(data),
    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    headers={"Content-Disposition": "attachment; filename=profit_loss_Q1_2026.xlsx"}
)
```

**Large reports (>1000 rows):** Async generation
```
POST /reports/profit-loss/export  → { "job_id": "abc123" }
GET  /reports/exports/abc123       → { "status": "processing" }
GET  /reports/exports/abc123       → { "status": "completed", "download_url": "..." }
GET  /reports/exports/abc123/download → file download
```

---

## 12. Performance Strategy & Data Freshness

> **Important:** Report endpoints do not all share the same data freshness. Two distinct read paths are in use. Frontend clients and consumers must understand which category each report falls into.

### 12.1 Live Queries (Real-Time — always current)

These reports query indexed operational tables directly. Data reflects the last committed transaction.

| Report | Query Target | Max Staleness |
|--------|-------------|---------------|
| Cash Book / Bank Book | `transactions` table (indexed: `account_id + date`) | None — real-time |
| Customer Ledger | `sale_invoices`, `customer_payments` (window function) | None — real-time |
| Supplier Ledger | `purchase_invoices`, `supplier_payments` (window function) | None — real-time |
| General Ledger | `transactions` table | None — real-time |
| Customer / Supplier Aging | `sale_invoices` with `CASE WHEN` due-date bucketing | None — real-time |
| Stock Movement | `stock_movements` (indexed: `item_id + moved_at`) | None — real-time |
| Sales Report | `sale_invoices` (indexed: `invoice_date`) | None — real-time |
| Purchases Report | `purchase_invoices` (indexed: `invoice_date`) | None — real-time |

### 12.2 Materialized View Queries (Nightly Cache — up to 24 hours stale)

These reports query pre-computed PostgreSQL materialized views refreshed daily by the ARQ worker at 02:00. They are intentionally stale to guarantee sub-300ms responses on aggregated datasets.

| Report | Materialized View | Refresh Schedule | Max Staleness |
|--------|------------------|-----------------|---------------|
| Profit & Loss | `mv_profit_loss` | Nightly 02:00 | 24 hours |
| Income & Expenses | `mv_profit_loss` | Nightly 02:00 | 24 hours |
| Stock Report (valuation) | `mv_stock_valuation` | Nightly 02:00 | 24 hours |
| Customer Balances | `mv_customer_balances` | Nightly 02:00 | 24 hours |
| Supplier Balances | `mv_supplier_balances` | Nightly 02:00 | 24 hours |

> **Note on stock availability vs. stock valuation:** `GET /inventory/items/{id}` (operational endpoint) reads `items.current_stock` directly — always real-time. `GET /reports/stock` (report endpoint) reads `mv_stock_valuation` — up to 24 hours stale. These are different endpoints serving different purposes.

**Pagination:** All reports paginate server-side. The default limit for reports is 50 rows; maximum 500. For exports, the limit is lifted.

---

## 13. Report Access Control

| Report | Min Role |
|--------|---------|
| All financial reports (P&L, Income/Expenses) | manager |
| Inventory reports | manager |
| Sales & Purchase reports | manager |
| Ledger reports | manager |
| Party Balance reports | manager |
| Cash & Bank reports | manager |
| Staff Payments | manager |
| Production report | manager |

`staff` role has NO access to any report endpoint. Reports are business intelligence for management only.

---

## 14. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Missing `from_date` or `to_date` | `ValidationException` | 422 |
| `from_date` > `to_date` | `ValidationException` | 422 |
| Customer/Supplier not found (ledger) | `NotFoundException` | 404 |
| Account not found (cash/bank book) | `NotFoundException` | 404 |
| Export job not found | `NotFoundException` | 404 |
| Date range > 366 days (for some reports) | `ValidationException` | 422 |
