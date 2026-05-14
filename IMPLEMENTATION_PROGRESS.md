# SmartLedger Backend — Implementation Progress Report

**Project:** SmartLedger ERP Backend  
**Stack:** FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL · ARQ (Redis) · Pydantic v2  
**Architecture:** Router → Service → Repository → Model (strict layering, no business logic in routers)  
**Status:** All planned modules complete ✅

---

## Table of Contents

1. [Project Structure Overview](#1-project-structure-overview)
2. [Core Infrastructure](#2-core-infrastructure)
3. [Module Implementations](#3-module-implementations)
   - 3.1 Authentication & RBAC
   - 3.2 Customers
   - 3.3 Suppliers
   - 3.4 Inventory
   - 3.5 Purchases
   - 3.6 Sales
   - 3.7 Transactions & Accounts
   - 3.8 Staff & Payroll
   - 3.9 Production
   - 3.10 Reports
4. [Background Jobs (Phase 1)](#4-background-jobs-phase-1)
5. [Report Export (Phase 2)](#5-report-export-phase-2)
6. [Audit Logging (Phase 3)](#6-audit-logging-phase-3)
7. [Cross-Cutting Concerns](#7-cross-cutting-concerns)
8. [File Index](#8-file-index)

---

## 1. Project Structure Overview

```
app/
├── api/v1/endpoints/     — FastAPI route handlers (thin, no business logic)
├── core/                 — Config, DB engine, security, middleware, exceptions
├── models/               — SQLAlchemy ORM models + enums
├── repositories/         — DB query layer (all SQL lives here)
├── schemas/              — Pydantic v2 request/response schemas
├── services/             — Business logic layer (single source of truth)
├── tasks/                — ARQ background job functions + worker config
└── utils/                — Shared helpers (pagination, currency, dates)
```

---

## 2. Core Infrastructure

### `app/core/config.py`
Centralised settings loaded from `.env` via `pydantic-settings`.

| Setting | Purpose |
|---|---|
| `DATABASE_URL` | Async PostgreSQL connection string |
| `REDIS_URL` | Redis connection for ARQ job queue |
| `SECRET_KEY` | JWT signing key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Short-lived access token TTL (default 15 min) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL (default 7 days) |
| `EXPORT_STORAGE_PATH` | Filesystem path where export files are written |
| `EXPORT_MAX_ROWS_SYNC` | Row threshold above which export is forced async |

### `app/core/database.py`
- Async SQLAlchemy engine with connection pool (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`)
- `AsyncSessionLocal` session factory
- `get_db()` FastAPI dependency — yields a session per request, auto-closes

### `app/core/security.py`
- JWT creation and verification (HS256)
- `bcrypt` password hashing and verification

### `app/core/dependencies.py`
- `get_current_user()` — decodes JWT, loads user from DB
- `require_permission(resource, action)` — RBAC guard, returns the current user or raises 403
- Permission matrix covers all 11 resources × 3 actions (read/write/delete) for 3 roles (admin/manager/staff)

### `app/core/exceptions.py`
Custom exception classes with FastAPI exception handlers:

| Exception | HTTP Status |
|---|---|
| `NotFoundException` | 404 |
| `ConflictException` | 409 |
| `ValidationException` | 422 |
| `CreditLimitExceededError` | 422 |
| `UnauthorizedException` | 401 |

### `app/core/middleware.py`
- Request ID injection (`X-Request-ID` header)
- Structured access logging via `structlog`

### `app/core/logging.py`
- `structlog` configured for JSON output in production, pretty-print in development

### `app/core/arq_pool.py`
- Singleton ARQ Redis pool (`get_arq_pool()`)
- Used by API routes to enqueue background jobs without creating a new connection per request
- `close_arq_pool()` called in FastAPI shutdown lifecycle hook

### `app/models/base.py`
- `Base` — SQLAlchemy `DeclarativeBase` root
- `TimestampMixin` — `created_at`, `updated_at` (server-side, auto-managed)
- `AuditMixin` — extends TimestampMixin with `created_by` FK to users

### `app/models/enums.py`
All PostgreSQL native ENUM types: `UserRole`, `PaymentMode`, `PaymentType`, `BalanceType`, `ItemType`, `MovementType`, `PurchaseStatus`, `SaleStatus`, `ReturnStatus`, `StaffType`, `AttendanceStatus`, `AccountType`, `TransactionType`, `ReferenceType`, `ProductionStatus`, `NotificationType`, `AuditAction`

### `app/repositories/base_repo.py`
Generic async CRUD base: `get`, `get_or_404`, `create`, `update`, `soft_delete`, `count`

### `app/schemas/common.py`
- `SuccessResponse[T]` — standard JSON envelope `{success, data}`
- `PaginatedResponse[T]` — adds `total`, `page`, `limit`, `pages`

### `app/main.py`
- FastAPI app factory with lifespan context (startup/shutdown)
- CORS middleware, exception handlers, router registration
- Health check endpoint: `GET /health`

---

## 3. Module Implementations

### 3.1 Authentication & RBAC

**Purpose:** Control who can access the system and what they can do.

**Files:** `models/auth.py` · `schemas/auth.py` · `services/auth_service.py` · `api/v1/endpoints/auth.py`

**What it does:**
- User registration and login with JWT (access + refresh token pair)
- Token refresh — issues new access token from valid refresh token
- Password change (requires current password)
- `UserRole` enum: `admin` / `manager` / `staff`
- All protected endpoints use `require_permission(resource, action)` — no role checks scattered in route handlers

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Login, receive token pair |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/change-password` | Change own password |

---

### 3.2 Customers

**Purpose:** Manage customer master data and track receivable/payable balances with full ledger history.

**Files:** `models/customer.py` · `schemas/customer.py` · `repositories/customer_repo.py` · `services/customer_service.py` · `api/v1/endpoints/customers.py`

**What it does:**
- Full CRUD with soft-delete
- **Balance model:** non-negative `balance` + `balance_type` (receivable/payable). All arithmetic in `_compute_new_balance()` using signed space — no math in the repository
- **Credit limit enforcement:** `credit_limit > 0` blocks sales that would exceed it (`CreditLimitExceededError`)
- `opening_balance` seeds both the balance cache and the ledger running total
- Payment recording reduces receivable balance with concurrency safety (`SELECT FOR UPDATE`)
- Full ledger view: synthetic opening row + chronological sales (debit) and payments (credit)

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/customers` | Create customer |
| GET | `/customers` | List with search, balance filter, sort, pagination |
| GET | `/customers/{id}` | Get single customer |
| PATCH | `/customers/{id}` | Update customer |
| DELETE | `/customers/{id}` | Soft-delete |
| GET | `/customers/{id}/balance` | Balance summary |
| POST | `/customers/{id}/payments` | Record customer payment |
| GET | `/customers/{id}/payments` | List payments |
| GET | `/customers/{id}/ledger` | Full AR ledger |

---

### 3.3 Suppliers

**Purpose:** Manage supplier master data and track payable/receivable balances with full ledger history.

**Files:** `models/supplier.py` · `schemas/supplier.py` · `repositories/supplier_repo.py` · `services/supplier_service.py` · `api/v1/endpoints/suppliers.py`

**What it does:**
- Mirror of customer module with AP convention: purchases increase payable, payments decrease payable
- `_compute_new_balance()` uses payable-positive signed space (opposite convention to customers)
- `apply_purchase_to_balance()` — internal hook called by `purchase_service` on confirmation
- Full ledger view: purchases (credit) and payments (debit)

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/suppliers` | Create supplier |
| GET | `/suppliers` | List with filters |
| GET | `/suppliers/{id}` | Get single supplier |
| PATCH | `/suppliers/{id}` | Update supplier |
| DELETE | `/suppliers/{id}` | Soft-delete |
| GET | `/suppliers/{id}/balance` | Balance summary |
| POST | `/suppliers/{id}/payments` | Record payment to supplier |
| GET | `/suppliers/{id}/payments` | List payments |
| GET | `/suppliers/{id}/ledger` | Full AP ledger |

---

### 3.4 Inventory

**Purpose:** Manage items, units of measure, and categories. Track all stock movements with full history.

**Files:** `models/inventory.py` · `schemas/inventory.py` · `repositories/inventory_repo.py` · `services/inventory_service.py` · `api/v1/endpoints/inventory.py`

**What it does:**
- Units and categories with soft-delete and uniqueness constraints
- Items with SKU uniqueness, item type (`purchased` / `produced`), reorder level, sale/purchase prices
- **Stock mutation pattern** — all changes go through `_apply_stock_change()`:
  1. `SELECT FOR UPDATE` on the item row
  2. Compute `new_stock = current_stock + delta` in Python
  3. Write back via `apply_stock_update()`
  4. Append `StockMovement` record
- Public hooks used by other services: `record_purchase_in`, `record_sale_out`, `record_return_in`, `record_return_out`, `record_production_in`, `record_production_out`
- Manual stock adjustment by operators (type: `adjustment`)

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST/GET/PATCH/DELETE | `/inventory/units/{id}` | Unit CRUD |
| POST/GET/PATCH/DELETE | `/inventory/categories/{id}` | Category CRUD |
| POST | `/inventory/items` | Create item |
| GET | `/inventory/items` | List with search, category, type, low-stock filter |
| GET/PATCH/DELETE | `/inventory/items/{id}` | Item detail / update / soft-delete |
| POST | `/inventory/items/{id}/adjust` | Manual stock adjustment |
| GET | `/inventory/items/{id}/stock` | Stock movement history |

---

### 3.5 Purchases

**Purpose:** Manage purchase orders from suppliers — draft to confirmed, with payments and returns.

**Files:** `models/purchase.py` · `schemas/purchase.py` · `repositories/purchase_repo.py` · `services/purchase_service.py` · `api/v1/endpoints/purchases.py`

**What it does:**
- Lifecycle: `draft → confirmed → void` / `confirmed → returned`
- **Draft creation:** line totals computed in Python; no stock or balance changes yet
- **Confirmation:** triggers `record_purchase_in()` per line item; updates supplier balance for credit/partial payment types
- **Payments:** validates amount ≤ due amount; auto-updates paid/due amounts; inserts `PurchasePayment` row
- **Returns:** validates return quantities against originals; `approve_return()` reverses stock and supplier balance
- Cash purchases: `paid_amount = total_amount` at creation (fully settled)
- `due_amount` is a PostgreSQL `Computed` column — re-fetched via raw SQL after commit to avoid `MissingGreenlet` error

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/purchases` | Create purchase (draft) |
| GET | `/purchases` | List with supplier, status, date filters |
| GET/PATCH | `/purchases/{id}` | Get / update draft |
| POST | `/purchases/{id}/confirm` | Confirm — triggers stock + supplier balance |
| POST | `/purchases/{id}/void` | Void draft |
| POST | `/purchases/{id}/payments` | Record payment |
| GET | `/purchases/{id}/payments` | List payments |
| POST | `/purchases/{id}/returns` | Create return |
| POST | `/purchases/{id}/returns/{rid}/approve` | Approve return |
| GET | `/purchases/{id}/returns` | List returns |

---

### 3.6 Sales

**Purpose:** Manage sale invoices to customers — draft to confirmed, with payments and returns.

**Files:** `models/sale.py` · `schemas/sale.py` · `repositories/sale_repo.py` · `services/sale_service.py` · `api/v1/endpoints/sales.py`

**What it does:**
- Lifecycle: `draft → confirmed → partially_paid / paid` / `confirmed → void / returned`
- **Draft creation:** credit limit check for credit/partial payment types
- **Confirmation:** `record_sale_out()` per line item; updates customer balance via `apply_sale_to_balance()`
- **Payments:** status auto-transitions `confirmed → partially_paid → paid`; reduces customer receivable
- **Returns:** `approve_return()` reverses stock in and customer balance
- `Notification` model used for due/overdue notifications (also used by background job)
- `due_amount` is a `Computed` column — re-fetched via raw SQL after commit

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/sales` | Create sale invoice (draft) |
| GET | `/sales` | List with customer, status, overdue filter |
| GET/PATCH | `/sales/{id}` | Get / update draft |
| POST | `/sales/{id}/confirm` | Confirm — triggers stock + customer balance |
| POST | `/sales/{id}/void` | Void draft |
| POST | `/sales/{id}/payments` | Record payment |
| GET | `/sales/{id}/payments` | List payments |
| POST | `/sales/{id}/returns` | Create return |
| POST | `/sales/{id}/returns/{rid}/approve` | Approve return |
| GET | `/sales/{id}/returns` | List returns |
| GET | `/sales/notifications` | List due/overdue notifications |

---

### 3.7 Transactions & Accounts

**Purpose:** Manage cash/bank/digital accounts and record every financial movement as an immutable ledger.

**Files:** `models/transaction.py` · `schemas/transaction.py` · `repositories/transaction_repo.py` · `services/transaction_service.py` · `api/v1/endpoints/transactions.py`

**What it does:**
- Account types: `cash`, `bank`, `digital`. Bank accounts require `bank_name`
- `opening_balance` seeds `current_balance` at creation
- **Transactions are immutable** — no update or delete endpoints exist
- Every balance mutation writes a `Transaction` row (debit or credit) and updates `current_balance`
- **Transfers:** atomic debit from source + credit to destination; writes 2 Transaction rows + 1 Transfer row; source and destination must differ; no overdraft
- `deactivate_account()` blocks deactivation if `current_balance ≠ 0`
- `record_account_transaction()` — internal hook called by salary disbursement

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/transactions/accounts` | Create account |
| GET | `/transactions/accounts` | List accounts |
| GET/PATCH | `/transactions/accounts/{id}` | Get / update account |
| DELETE | `/transactions/accounts/{id}` | Deactivate account |
| GET | `/transactions/accounts/{id}/transactions` | Account transaction history |
| POST | `/transactions/transfers` | Create transfer between accounts |
| GET | `/transactions/transfers` | List transfers |

---

### 3.8 Staff & Payroll

**Purpose:** Manage staff records, salary structures, attendance, advances, and monthly salary disbursement.

**Files:** `models/staff.py` · `schemas/staff.py` · `repositories/staff_repo.py` · `services/staff_service.py` · `api/v1/endpoints/staff.py`

**What it does:**
- Staff with unique CNIC, type (permanent/temporary), soft-delete
- **Salary structures:** date-ranged; creating a new one auto-closes the current open one (`effective_to = new.effective_from - 1 day`)
- **Attendance:** one record per staff per date; bulk recording for a single date across many staff; re-recording overwrites (upsert/idempotent)
- **Advances:** cash advances given to staff; automatically deducted from next salary
- **Salary disbursement:**
  - One payment per staff per month/year (DB unique constraint)
  - `net = gross + allowances − deductions − advance_deduction`
  - Pending advances for the month auto-marked as deducted
  - Posts a debit transaction to the specified account via `transaction_service`

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST/GET | `/staff` | Create / list staff |
| GET/PATCH/DELETE | `/staff/{id}` | Get / update / soft-delete |
| POST/GET | `/staff/{id}/salary-structures` | Add / list salary structures |
| POST | `/staff/attendance/bulk` | Bulk attendance recording |
| PATCH | `/staff/{id}/attendance/{date}` | Update single attendance |
| GET | `/staff/{id}/attendance` | List attendance |
| POST/GET | `/staff/{id}/advances` | Record / list advances |
| POST/GET | `/staff/{id}/payments` | Disburse / list salary payments |

---

### 3.9 Production

**Purpose:** Manage manufacturing orders — plan, start, complete, tracking raw material consumption and output.

**Files:** `models/production.py` · `schemas/production.py` · `repositories/production_repo.py` · `services/production_service.py` · `api/v1/endpoints/production.py`

**What it does:**
- Lifecycle: `planned → in_progress → completed / cancelled`
- **Create (planned):** validates product item (type=`produced`) and each raw material; computes line-level and header costs; no stock movement yet
- **Complete:** `record_production_out()` per raw material line (stock consumed); `record_production_in()` for finished good (stock added); `used_quantity` set on each material line; header costs recomputed
- Supports adding labor and other-cost lines while order is in progress
- `total_cost` is a `Computed` column — re-fetched via raw SQL after commit

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| POST | `/production/orders` | Create production order |
| GET | `/production/orders` | List orders with status, date filters |
| GET/PATCH | `/production/orders/{id}` | Get / update order |
| POST | `/production/orders/{id}/start` | Transition to in_progress |
| POST | `/production/orders/{id}/complete` | Complete — triggers stock movements |
| POST | `/production/orders/{id}/cancel` | Cancel order |
| POST | `/production/orders/{id}/labor` | Add labor line |
| POST | `/production/orders/{id}/costs` | Add other cost line |
| POST | `/production/orders/{id}/outputs` | Record actual output quantity |

---

### 3.10 Reports

**Purpose:** Provide financial and operational summaries for management decision-making.

**Files:** `schemas/reports.py` · `services/report_service.py` · `api/v1/endpoints/reports.py`

**What it does:**
- All reports are read-only aggregations; no ORM — uses raw SQL (`text()`) for single-round-trip queries
- Access restricted to manager and admin roles
- Supports inline sync export via `format=csv` or `format=xlsx` query parameter on every GET endpoint

**Reports available:**

| Report | Path | What it shows |
|---|---|---|
| Profit & Loss | `/reports/profit-loss` | Revenue, COGS, gross profit, salary/advance/other expenses, net profit for a date range |
| Sales Summary | `/reports/sales-summary` | Total invoiced/collected/outstanding + per-customer breakdown |
| Purchase Summary | `/reports/purchase-summary` | Total purchased/paid/outstanding + per-supplier breakdown |
| Stock Summary | `/reports/stock-summary` | Current stock levels per item, below-reorder flags |
| Stock Movements | `/reports/stock-movements` | Movement log filtered by date, item, movement type |
| Customer Balances | `/reports/customer-balances` | All customers with outstanding balances |
| Supplier Balances | `/reports/supplier-balances` | All suppliers with outstanding balances |
| Cash Flow | `/reports/cash-flow` | Account-level inflows/outflows and net position |
| Payroll Summary | `/reports/payroll-summary` | Monthly salary disbursement per staff member |
| Production Summary | `/reports/production-summary` | Orders, quantities produced, and costs for a date range |

---

## 4. Background Jobs (Phase 1)

**Purpose:** Run scheduled operations automatically without blocking API requests.

**Technology:** ARQ (Async Redis Queue) — jobs survive server restarts, retry on failure (max 3 attempts).

### `app/core/arq_pool.py`
Singleton Redis connection pool for enqueueing jobs from API routes. Lazy-initialised on first use; closed on app shutdown.

### `app/tasks/worker.py`
ARQ `WorkerSettings` — registers all job functions, cron schedule, and lifecycle hooks.

| Setting | Value | Purpose |
|---|---|---|
| `max_jobs` | 20 | Max concurrent jobs per worker process |
| `job_timeout` | 300s | Max runtime per job before timeout |
| `keep_result` | 3600s | How long job results stay in Redis |
| `retry_jobs` | True | Auto-retry on failure |
| `max_tries` | 3 | Max attempts before marking failed |

### `app/tasks/stock_alerts.py` — `check_low_stock`
**Schedule:** Daily at 07:00 UTC

What it does:
- Queries all active items where `current_stock ≤ reorder_level` and `reorder_level > 0`
- Skips items that already have a `low_stock` notification today (idempotent — safe to re-run)
- Bulk-inserts `Notification` rows for new alerts

### `app/tasks/notifications.py` — `send_due_invoice_notifications`
**Schedule:** Daily at 08:00 UTC

What it does:
- Queries confirmed/partially-paid sale invoices with `due_date ≤ today + 3 days` and `due_amount > 0`
- Classifies each as `overdue` (due_date < today) or `due` (due_date ≤ today+3)
- Skips invoices already notified with the same type today (idempotent)
- Bulk-inserts `Notification` rows in batches of 100; per-batch error isolation

### `app/tasks/report_refresh.py` — `refresh_materialized_views`
**Schedule:** Daily at 02:00 UTC

What it does:
- Refreshes PostgreSQL materialized views used by the Reports module in dependency order:
  1. `mv_stock_valuation`
  2. `mv_supplier_balances`
  3. `mv_customer_balances`
  4. `mv_profit_loss`
- Uses `REFRESH MATERIALIZED VIEW CONCURRENTLY` — reads continue during refresh (no exclusive lock)
- Each view is attempted independently; partial success is acceptable and reported

---

## 5. Report Export (Phase 2)

**Purpose:** Allow users to download report data as CSV or XLSX files, with async handling for large datasets.

**Files:** `services/export_service.py` · `tasks/report_export.py`

### Two export paths

**Sync (inline):** `format=csv` or `format=xlsx` query param on any existing report GET endpoint. Runs the report query and streams the file directly in the response. Best for small/quick reports.

**Async (background job):** Three dedicated routes for large or long-running exports.

### Async export flow

```
POST /reports/{report_name}/export
  → validates report name against whitelist
  → serialises params (dates → ISO strings, JSON-safe)
  → enqueues ARQ job with deterministic job_id
  → returns {job_id, status, already_running}

GET /reports/exports/{job_id}
  → polls job info from Redis
  → returns {status: queued|in_progress|complete|failed}

GET /reports/exports/{job_id}/download
  → checks filesystem for {job_id}.csv or {job_id}.xlsx
  → streams file via FileResponse
```

### Deduplication
Job ID is derived from `SHA256(user_id + report_name + params + format)`. ARQ reuses an existing job if the same ID is already queued or running — rapid repeated clicks do not spawn duplicate jobs. When a duplicate is detected, the response includes `already_running: true` so the frontend can display this clearly rather than silently reusing.

### Cleanup
`cleanup_old_exports` cron runs at 03:00 UTC daily — deletes export files older than 24 hours from `EXPORT_STORAGE_PATH`.

### Report whitelist
`export_service._REPORT_REGISTRY` maps allowed report names to their service functions. Unknown names return 404, preventing arbitrary function execution.

---

## 6. Audit Logging (Phase 3)

**Purpose:** Maintain an append-only trail of every CREATE, UPDATE, and DELETE on critical business entities for compliance, debugging, and accountability.

**Files:** `models/audit.py` · `schemas/audit.py` · `services/audit_service.py` · `api/v1/endpoints/audit.py`

### Design principles
- Audit rows written **inside the same DB transaction** as the mutation — rolls back together, no orphaned entries
- **Append-only** — no update or delete endpoints on the audit table
- `old_values` captured before mutation; `new_values` captured after flush (ORM object state, not re-queried)
- `snapshot()` uses SQLAlchemy column introspection to extract only column-mapped attributes, stripping internal ORM state. Serialises `Decimal` → `str`, `datetime` → ISO string, enums → `.value`

### `AuditLog` model columns

| Column | Type | Purpose |
|---|---|---|
| `id` | BigInteger | Primary key |
| `user_id` | FK → users | Who performed the action (nullable — system actions) |
| `action` | AuditAction enum | CREATE / UPDATE / DELETE |
| `table_name` | String | Which table was affected |
| `record_id` | Integer | PK of the affected row |
| `old_values` | JSONB | State before mutation (null for CREATE) |
| `new_values` | JSONB | State after mutation (null for DELETE) |
| `request_id` | String | Correlation ID from `X-Request-ID` header |
| `ip_address` | INET | Client IP |
| `created_at` | Timestamp | When the audit row was written |

Indexed on: `(table_name, record_id)`, `user_id`, `created_at`

### Instrumented entities

| Service | Operations audited |
|---|---|
| `customer_service` | create, update, delete |
| `supplier_service` | create, update, delete |
| `inventory_service` | item create, item update, item delete |
| `purchase_service` | create, confirm, void, payment, return create, return approve |
| `sale_service` | create, confirm, void, payment, return create, return approve |
| `staff_service` | staff create, update, delete; salary structure; attendance; advance; salary payment |
| `production_service` | order create, start, complete, cancel; labor/cost add |
| `transaction_service` | account create, update, deactivate; transfer |

### `GET /audit-logs` endpoint
Admin-only. Filterable by `table_name`, `record_id`, `user_id`, `action`, `date_from`, `date_to`. Paginated (default 50, max 200 per page). Ordered newest-first.

---

## 7. Cross-Cutting Concerns

### Concurrency safety
All balance-mutating operations use `SELECT FOR UPDATE` to lock the target row before reading and writing. No balance arithmetic happens in the database — all computed in Python in the service layer.

### Computed columns
`due_amount` (purchases, sales) and `total_cost` (production) are PostgreSQL `Computed` columns. After any commit, these are re-fetched using raw `text()` SQL to avoid the SQLAlchemy `MissingGreenlet` error that occurs when accessing server-computed attributes through the ORM after a flush.

### Soft deletes
All master data (customers, suppliers, items, staff, accounts) uses `is_active=False` rather than hard deletes. Deleted records remain in historical data (ledger, stock movements, audit logs).

### Structured logging
All services and background tasks use `structlog` for JSON-structured logs with key=value context (`user_id`, `record_id`, `action`, etc.).

### RBAC
Three roles with a per-resource permission matrix:
- **admin** — full access to everything including audit logs and user management
- **manager** — read/write on all business modules, no delete, no audit
- **staff** — read-only on most modules; write on attendance

---

## 8. File Index

### Models
| File | Tables |
|---|---|
| `models/auth.py` | `users`, `refresh_tokens` |
| `models/customer.py` | `customers`, `customer_payments` |
| `models/supplier.py` | `suppliers`, `supplier_payments` |
| `models/inventory.py` | `units`, `categories`, `items`, `stock_movements` |
| `models/purchase.py` | `purchases`, `purchase_items`, `purchase_payments`, `purchase_returns`, `purchase_return_items` |
| `models/sale.py` | `sale_invoices`, `sale_items`, `sale_payments`, `sale_returns`, `sale_return_items`, `notifications` |
| `models/transaction.py` | `accounts`, `transactions`, `transfers` |
| `models/staff.py` | `staff`, `salary_structures`, `attendance`, `advances`, `staff_payments` |
| `models/production.py` | `production_orders`, `production_raw_materials`, `production_labor`, `production_costs`, `production_output` |
| `models/audit.py` | `audit_logs` |

### API Endpoints summary

| Prefix | Module | Roles |
|---|---|---|
| `/api/v1/auth` | Authentication | Public (login), authenticated (change-password) |
| `/api/v1/customers` | Customers | read: all · write: manager/admin · delete: admin |
| `/api/v1/suppliers` | Suppliers | read: all · write: manager/admin · delete: admin |
| `/api/v1/inventory` | Inventory | read: all · write: manager/admin · delete: admin |
| `/api/v1/purchases` | Purchases | read: all · write: manager/admin |
| `/api/v1/sales` | Sales | read: all · write: manager/admin |
| `/api/v1/transactions` | Accounts & Transactions | read: all · write: manager/admin · delete: admin |
| `/api/v1/staff` | Staff & Payroll | read: all · write: manager/admin · delete: admin |
| `/api/v1/production` | Production | read: all · write: manager/admin |
| `/api/v1/reports` | Reports & Export | read: manager/admin only |
| `/api/v1/audit-logs` | Audit Trail | read: admin only |

---

*Generated: 2026-04-28*
