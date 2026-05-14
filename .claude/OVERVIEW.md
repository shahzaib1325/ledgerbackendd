# SmartLedger — Project Overview

## Document Information

| Field | Value |
|-------|-------|
| Document Type | Software Requirements Specification (SRS) — Overview |
| Application Name | SmartLedger Business Management System |
| Backend Framework | FastAPI (Python) |
| Database | PostgreSQL |
| Version | 1.0.0 |
| Status | In Development |
| Date | 2026-04-16 |

---

## 1. Purpose

SmartLedger is a comprehensive, centralized business management backend system designed to digitize and automate all core business operations of a small-to-medium enterprise. It replaces manual ledger books, disconnected spreadsheets, and fragmented record-keeping with a single unified REST API that serves any frontend client (web, mobile, desktop).

The system's primary goal is to give business owners and managers real-time visibility into:
- Who owes them money (customers) and who they owe money to (suppliers)
- How much stock is available and moving
- What the business earned, spent, and produced
- The complete financial health through ledgers and reports

---

## 2. Scope

The backend exposes a versioned REST API (`/api/v1/`) consumed by a separate frontend application. All business logic, data persistence, validation, and reporting are handled exclusively by this backend.

### 2.1 In Scope

| Module | Description |
|--------|-------------|
| Auth & Users | JWT authentication, role-based access control |
| Suppliers | Supplier records, payable balances, ledger |
| Customers | Customer records, credit limits, receivable balances, aging |
| Inventory | Items, categories, units, stock tracking |
| Purchases | Incoming materials, supplier linkage, payment types, returns |
| Sales | Invoices, payments, customer notifications, returns |
| Staff | Permanent/temporary staff, salary structures, attendance, payroll |
| Transactions | Central financial ledger — cash, bank, digital accounts |
| Production | Manufacturing orders, raw material consumption, labor costs |
| Reports | P&L, ledgers, aging, stock, cash book, bank book, and more |

### 2.2 Out of Scope (v1.0)

- Frontend / UI rendering
- Multi-branch / multi-company support
- E-commerce integrations (Shopify, WooCommerce)
- Automated bank statement import
- Mobile push notifications (only in-app notifications in v1)
- Payroll tax filing / government compliance forms

---

## 3. Stakeholders

| Role | Responsibility |
|------|---------------|
| Business Owner / Admin | Full system access; user management; final reports |
| Manager | Access to all operational modules; cannot manage users |
| Staff / Operator | Limited access; can record sales, purchases, attendance |
| Developer | Implements and maintains this backend |

---

## 4. System Characteristics

### 4.1 Functional Requirements (Summary)

- **FR-01**: The system shall allow recording and tracking of all purchase transactions linked to suppliers.
- **FR-02**: The system shall manage sales invoices, credit limits, and customer payment tracking.
- **FR-03**: The system shall maintain real-time inventory levels updated automatically by purchases, sales, and production.
- **FR-04**: The system shall support cash, credit, and partial payment types for both purchases and sales.
- **FR-05**: The system shall track supplier and customer balances as running totals derived from all transactions.
- **FR-06**: The system shall support production orders that consume raw materials and produce finished goods.
- **FR-07**: The system shall manage permanent and temporary staff payroll, including advances and deductions.
- **FR-08**: The system shall maintain a central transaction ledger across multiple account types (cash, bank, digital).
- **FR-09**: The system shall generate reports covering financial, inventory, sales, purchase, ledger, and party data.
- **FR-10**: The system shall notify users of overdue invoices and low stock levels.

### 4.2 Non-Functional Requirements (Summary)

- **NFR-01 Performance**: API responses under 300ms for all non-report endpoints under normal load.
- **NFR-02 Performance**: Report endpoints may take up to 2s; heavy reports use async generation.
- **NFR-03 Reliability**: 99.5% uptime SLA; all financial mutations are ACID-compliant DB transactions.
- **NFR-04 Security**: All endpoints require JWT authentication except `/auth/login`.
- **NFR-05 Security**: Role-based access control enforced at the route level via dependency injection.
- **NFR-06 Scalability**: Stateless API design; horizontal scaling via multiple uvicorn workers.
- **NFR-07 Maintainability**: Code organized in layers (router → service → repository); each module is self-contained.
- **NFR-08 Data Integrity**: No hard deletes on any business record; soft-delete pattern enforced everywhere.
- **NFR-09 Auditability**: Every write operation is logged in an audit table (who, what, when, before/after).
- **NFR-10 Observability**: Structured JSON logging with request IDs; metrics exposed via `/metrics` (Prometheus-compatible).

---

## 5. Technology Stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| Language | Python 3.12+ | Mature ecosystem, async support |
| Web Framework | FastAPI 0.110+ | Async-native, auto OpenAPI docs, Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async) | Powerful, async-native with asyncpg |
| DB Driver | asyncpg | Fastest async PostgreSQL driver |
| Database | PostgreSQL 16 | ACID, JSON support, window functions, sequences |
| Migrations | Alembic | SQLAlchemy-native schema versioning |
| Auth | python-jose + passlib | JWT tokens, bcrypt hashing |
| Background Jobs | ARQ (async Redis Queue) | Lightweight async job queue |
| Cache / Queue | Redis 7 | Session blacklist, job queue, rate limit counters |
| Validation | Pydantic v2 | Request/response schema validation |
| Testing | pytest + pytest-asyncio | Async test support |
| Logging | structlog | Structured JSON logs |
| Rate Limiting | slowapi | FastAPI-native rate limiting |

---

## 6. High-Level Module Interaction

```
┌────────────────────────────────────────────────────────┐
│                   REST API (FastAPI)                   │
│              /api/v1/<module>/<endpoint>               │
└────────────────────────────────────────────────────────┘
         │           │           │           │
    ┌────▼───┐  ┌────▼───┐  ┌───▼────┐  ┌──▼──────┐
    │Purchases│  │ Sales  │  │ Staff  │  │Production│
    └────┬────┘  └────┬───┘  └───┬────┘  └──┬───────┘
         │            │          │           │
         └────────────┴──────────┴───────────┘
                            │
                    ┌───────▼────────┐
                    │  Transactions  │  ← central financial ledger
                    └───────┬────────┘
                            │
              ┌─────────────┼─────────────┐
         ┌────▼────┐  ┌─────▼────┐  ┌────▼──────┐
         │Suppliers│  │Customers │  │ Inventory │
         └─────────┘  └──────────┘  └───────────┘
                            │
                       ┌────▼─────┐
                       │ Reports  │  ← read-only aggregations
                       └──────────┘
```

---

## 7. Key Design Decisions

### 7.1 Soft Deletes
No business record is ever permanently deleted. Every main entity table has `is_active BOOLEAN DEFAULT TRUE`. Deletion sets `is_active = false`. This preserves historical integrity for ledgers and reports.

### 7.2 Centralized Transaction Ledger
All financial movements (purchase payments, sale receipts, salary disbursements, transfers) go through a single `transactions` table linked to `accounts`. This is the single source of truth for all cash/bank/digital movements, and directly powers the Cash Book, Bank Book, and General Ledger reports.

### 7.3 Immutable Stock via Movements
`items.current_stock` is never updated directly. It is always changed by inserting a `stock_movements` record. This provides a complete audit trail and enables the Stock Movement report.

### 7.4 Atomic Business Operations
All multi-step operations (confirm purchase, confirm sale, complete production) are wrapped in a single DB transaction. If any step fails, the entire operation rolls back to prevent partial state.

### 7.5 Computed Balances
Supplier and customer balances are computed values maintained as running aggregates. The `balance` column is updated on every relevant transaction using `SELECT ... FOR UPDATE` to prevent race conditions.

---

## 8. Development Phases

| Phase | Modules | Goal |
|-------|---------|------|
| 1 — Foundation | Core/Auth, Inventory (units/categories/items), Suppliers, Customers | All master data, auth working |
| 2 — Transactions | Accounts, Transactions, Purchases, Sales | Core money flow operational |
| 3 — Operations | Staff & Payroll, Production | Operational completeness |
| 4 — Intelligence | All Reports, Background Tasks, Notifications | Full business visibility |

---

## 9. Document Index

| File | Contents |
|------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | App layers, patterns, dependency flow |
| [FOLDER_STRUCTURE.md](FOLDER_STRUCTURE.md) | Complete file and directory layout |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | All tables, columns, types, constraints, indexes |
| [API_CONVENTIONS.md](API_CONVENTIONS.md) | Request/response format, pagination, error codes |
| [SECURITY.md](SECURITY.md) | Auth, RBAC, validation rules, audit logging |
| [BACKGROUND_TASKS.md](BACKGROUND_TASKS.md) | Scheduled jobs, async workers, retry logic |
| [modules/01_AUTH.md](modules/01_AUTH.md) | Auth & Users — detailed SRS |
| [modules/02_SUPPLIERS.md](modules/02_SUPPLIERS.md) | Suppliers — detailed SRS |
| [modules/03_CUSTOMERS.md](modules/03_CUSTOMERS.md) | Customers — detailed SRS |
| [modules/04_INVENTORY.md](modules/04_INVENTORY.md) | Inventory — detailed SRS |
| [modules/05_PURCHASES.md](modules/05_PURCHASES.md) | Purchases — detailed SRS |
| [modules/06_SALES.md](modules/06_SALES.md) | Sales — detailed SRS |
| [modules/07_STAFF.md](modules/07_STAFF.md) | Staff & Payroll — detailed SRS |
| [modules/08_TRANSACTIONS.md](modules/08_TRANSACTIONS.md) | Transactions — detailed SRS |
| [modules/09_PRODUCTION.md](modules/09_PRODUCTION.md) | Production — detailed SRS |
| [modules/10_REPORTS.md](modules/10_REPORTS.md) | Reports — detailed SRS |
