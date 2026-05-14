# SmartLedger: High-Level Architecture Overview

## 1. Executive Summary
SmartLedger is a centralized business management backend system designed to digitize and automate core operations for small-to-medium enterprises (SMEs). Moving beyond traditional manual ledgers and disconnected spreadsheets, the platform provides a unified RESTful API to manage the entire financial health, stock tracking, and workflow of an organization. 

**Target Audience for this Document:** Senior Engineers, Product Managers, and Business Stakeholders who require a conceptual "bird's-eye view" of how the system operates, its boundary constraints, and architectural pillars without diving into granular code.

---

## 2. System Scope & Domain
SmartLedger is built as a highly performant, API-first "headless" application. All business logic, validations, and logic reside securely on the backend.

**Key Functional Domains:**
*   **Parties:** Tracking Supplier (payable) and Customer (receivable) balances and credit boundaries.
*   **Inventory & Production:** Real-time on-hand stock counts (served directly from the `items` table) tracked across raw materials and finished goods, including labor/material tracking via manufacturing orders. Note: inventory *reports* (stock valuation, aging) are served from nightly-refreshed materialized views and may be up to 24 hours stale — see Section 5.
*   **Purchases & Sales:** End-to-end lifecycle tracking for invoices, partial payments, and returns.
*   **Staff & Payroll:** Handling temporary/permanent employee attendance, dynamic salary structures, and advances.
*   **Central Transactions Ledger:** A unified record of all financial movements across physical (cash) and digital (bank) accounts.

**Out of Scope (v1.0 Baseline):** User Interface rendering (fully delegated to frontend apps), multi-tenancy/multi-branch setups, e-commerce third-party integrations, and automated ingestion of external bank statements.

---

## 3. The Layered (N-Tier) Architecture Pattern
To ensure the system remains testable, resilient, and easy to maintain as it grows, it follows a strict **Layered Architecture**. Data and requests only flow downwards; components are highly decoupled.

```text
[ Client Applications (Web / Mobile) ]
                 │
                 ▼       (HTTP / JSON via API)
[ API Layer (Routers) ]            <-- Handles auth, parses requests, routes traffic
                 │
                 ▼
[ Service Layer (Business Logic) ] <-- Coordinates modules, enforces business rules
                 │
                 ▼
[ Repository Layer (Data Access) ] <-- Standardized database interactions (queries)
                 │
                 ▼
[ Database (PostgreSQL 16) ]       <-- ACID compliance, materializing reports
                 │
                 ▼
[ Async Workers (Redis / ARQ) ]    <-- Scheduled tasks, automated background jobs
```

---

## 4. Primary Technology Stack
*   **Language & Framework:** **Python 3.12+** driven by **FastAPI** (ensuring high-speed asynchronous processing, automatic data validation via Pydantic, and self-generating API documentation).
*   **Data Persistence:** **PostgreSQL 16** serves as the primary data store, equipped with advanced types (e.g. Enums, JSONB) and materialized views (pre-calculated tables) for high-performance reporting.
*   **ORM Layer:** **SQLAlchemy 2.0 (asyncpg)** acts as the communication mechanism between the Python code and the Database, prioritizing non-blocking queries. The async engine's `pool_size` must be set as `floor((postgres_max_connections - reserved_connections) / num_uvicorn_workers)` — never left at the SQLAlchemy default of 20 across multiple workers. With PostgreSQL's default `max_connections=100` and 4 workers, a safe formula is `pool_size=20, max_overflow=5` per worker (capped at 100 total). Beyond 3 workers, **PgBouncer** (transaction-mode pooling) must be introduced between the application and PostgreSQL to prevent connection exhaustion.
*   **Cache & Task Queue:** **Redis 7** functioning seamlessly with **ARQ** for fast execution of off-loaded or scheduled background tasks.

---

## 5. Key Design Principles
SmartLedger borrows strictly from standardized accounting principles. The architecture prioritizes data immutability and exact historical records.

1.  **The Central Financial Ledger:** All monetary exchanges—whether receiving a customer payment, paying a supplier, or doing payroll—ultimately flow into a singular `transactions` table. This creates a mathematically sound, single-source-of-truth for cash/bank books.
2.  **Immutable Inventory Lifecycle with Cached Stock Column:** `items.current_stock` is a *performance-cache* column — it is never edited directly by application code. It is updated exclusively inside `InventoryService.add_stock()` / `deduct_stock()`, within the same atomic database transaction that inserts the corresponding `stock_movements` row. The `stock_movements` log remains the auditable source of truth from which current stock is always reconstructable; the cached column exists so that reads do not require a full `SUM(quantity)` scan on every request.
3.  **Atomic Database Transactions:** Large-scale workflows, such as finalizing a production order (which utilizes raw materials, accrues labor, updates stock, and calculates financial costs), happen atomically. If any micro-step fails, the entire process is rolled back completely.
4.  **Soft Deletion Strategy:** Business records (users, suppliers, sales) are never deleted from the system entirely. They are toggled via an `is_active` flag, guaranteeing historic reports and attached ledgers never face orphan data exceptions.
5.  **Data Freshness — Two Distinct Read Paths:** The system exposes two fundamentally different read strategies that must never be conflated:
    *   **Operational reads** (`GET /inventory/items/{id}`, stock availability checks during sales/purchases) → query live tables in real time. Always current to the last committed transaction.
    *   **Reporting reads** (P&L, stock valuation, customer/supplier balances, aging) → query pre-computed PostgreSQL materialized views refreshed nightly at 02:00. Data may be up to 24 hours stale. This is acceptable for management reporting but not for transactional stock checks.

---

## 6. Background Tasks & Async Processing
Given the application tracks real-time data, complex operations that risk slowing down immediate API responses run as isolated background processes.

*   **Scheduled Maintenance (Cron):** Automated jobs check for low-stock items daily, analyze overdue invoices, and perform nightly database sweeps to refresh "Materialized Views" (ensuring tomorrow's intensive profit-and-loss reports load instantly).
*   **On-Demand Processing:** Requests for exhaustive multi-year data exports (CSV/Excel) and communication dispatching (e.g., outbound email notifications) execute transparently behind-the-scenes.

---

## 7. Security, Observability, & Compliance
The backend adopts a highly defensive posture, restricting visibility implicitly context depending.

*   **Dual-Token Authentication:** Users log in securely with JWT access tokens (15-min expiry) buffered by Refresh Tokens (7-day lifecycle, safely monitored and blacklisted via Redis when necessary). 
*   **Role-Based Access Control (RBAC) — Static Enum Model:** Three roles exist (`admin`, `manager`, `staff`). The permission matrix (which role can read/write/delete which module) is hardcoded in the `require_permission()` FastAPI dependency in `app/core/dependencies.py`. There is no `roles_permissions` database table and no runtime permission editing. This is a deliberate v1 decision: the permission matrix for an SME is stable and does not justify the added complexity of a dynamic RBAC system. If runtime configurability is needed in v2, the static model can be migrated without breaking the API contract.
*   **Comprehensive Audit Trail:** Every structural change made to the system's core records logs automatically to an `audit_logs` table (tracking the acting user, the exact record changed, their IP, and the raw `before & after` values).
*   **Redis Failure Behavior — Fail-Open:** If Redis becomes unavailable, the system fails open: JWT blacklist checks are skipped and rate limiting is suspended rather than rejecting all requests. This is a deliberate availability-over-security trade-off justified by the short access token lifetime (15 minutes). An attacker holding a legitimately-logged-out token can only exploit it within its remaining TTL. In exchange, a Redis outage does not cause a total API outage. This behavior must be implemented explicitly in `get_current_user()` — catch Redis connection errors and proceed rather than raising 503.
*   **Defensive API Structure:** Explicit schema definitions (Pydantic) stop mass assignment vulnerabilities. The API features active rate limiters to curb endpoint spam and parameterized queries preventing SQL injection system-wide.
