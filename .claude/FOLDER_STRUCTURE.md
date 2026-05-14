# SmartLedger — Folder & File Structure

## Complete Directory Layout

```
ledgerbackend/
│
├── .claude/                          # Project documentation (SRS)
│   ├── OVERVIEW.md
│   ├── ARCHITECTURE.md
│   ├── FOLDER_STRUCTURE.md           # This file
│   ├── DATABASE_SCHEMA.md
│   ├── API_CONVENTIONS.md
│   ├── SECURITY.md
│   ├── BACKGROUND_TASKS.md
│   └── modules/
│       ├── 01_AUTH.md
│       ├── 02_SUPPLIERS.md
│       ├── 03_CUSTOMERS.md
│       ├── 04_INVENTORY.md
│       ├── 05_PURCHASES.md
│       ├── 06_SALES.md
│       ├── 07_STAFF.md
│       ├── 08_TRANSACTIONS.md
│       ├── 09_PRODUCTION.md
│       └── 10_REPORTS.md
│
├── app/                              # Main application package
│   │
│   ├── main.py                       # FastAPI app factory, middleware, routers
│   │
│   ├── core/                         # Cross-cutting infrastructure
│   │   ├── __init__.py
│   │   ├── config.py                 # pydantic-settings (env vars, secrets)
│   │   ├── database.py               # async engine, session factory, get_db()
│   │   ├── security.py               # JWT encode/decode, password hashing
│   │   ├── dependencies.py           # Shared FastAPI Depends (get_current_user, etc.)
│   │   ├── exceptions.py             # Custom exception classes hierarchy
│   │   ├── logging.py                # structlog configuration
│   │   └── middleware.py             # RequestID, timing, CORS middleware
│   │
│   ├── models/                       # SQLAlchemy ORM models
│   │   ├── __init__.py               # Re-exports all models (for Alembic autodiscovery)
│   │   ├── base.py                   # Base declarative class + TimestampMixin
│   │   ├── auth.py                   # User, RolePermission, TokenBlacklist
│   │   ├── supplier.py               # Supplier, SupplierPayment
│   │   ├── customer.py               # Customer, CustomerPayment
│   │   ├── inventory.py              # Unit, Category, Item, StockMovement
│   │   ├── purchase.py               # Purchase, PurchaseItem, PurchasePayment,
│   │   │                             #   PurchaseReturn, PurchaseReturnItem
│   │   ├── sale.py                   # SaleInvoice, SaleItem, SalePayment,
│   │   │                             #   SaleReturn, SaleReturnItem, Notification
│   │   ├── staff.py                  # Staff, SalaryStructure, Attendance,
│   │   │                             #   StaffPayment, Advance
│   │   ├── transaction.py            # Account, Transaction, Transfer
│   │   ├── production.py             # ProductionOrder, ProductionRawMaterial,
│   │   │                             #   ProductionLabor, ProductionCost, ProductionOutput
│   │   └── audit.py                  # AuditLog
│   │
│   ├── schemas/                      # Pydantic v2 schemas
│   │   ├── __init__.py
│   │   ├── common.py                 # Shared types: PaginatedResponse, DateRange, etc.
│   │   ├── auth.py                   # LoginRequest, TokenResponse, UserCreate, UserOut
│   │   ├── supplier.py               # SupplierCreate, SupplierUpdate, SupplierOut, etc.
│   │   ├── customer.py
│   │   ├── inventory.py
│   │   ├── purchase.py
│   │   ├── sale.py
│   │   ├── staff.py
│   │   ├── transaction.py
│   │   ├── production.py
│   │   └── report.py                 # Report filter params and response schemas
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py             # Aggregates all module routers into api_v1_router
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── auth.py           # /auth/login, /auth/refresh, /auth/logout
│   │           ├── users.py          # /users CRUD
│   │           ├── suppliers.py      # /suppliers CRUD + payments + ledger
│   │           ├── customers.py      # /customers CRUD + payments + ledger + aging
│   │           ├── inventory.py      # /inventory/items, /units, /categories
│   │           ├── purchases.py      # /purchases CRUD + confirm + payments + returns
│   │           ├── sales.py          # /sales CRUD + confirm + payments + returns + notifs
│   │           ├── staff.py          # /staff CRUD + salary + attendance + payments
│   │           ├── transactions.py   # /accounts + /transactions + /transfers
│   │           ├── production.py     # /production CRUD + start + complete
│   │           └── reports.py        # All /reports/* endpoints
│   │
│   ├── services/                     # Business logic layer
│   │   ├── __init__.py
│   │   ├── auth_service.py           # Login, token management, user management
│   │   ├── supplier_service.py       # Supplier CRUD, balance management
│   │   ├── customer_service.py       # Customer CRUD, credit limit checks
│   │   ├── inventory_service.py      # Item CRUD, stock add/deduct, movement logging
│   │   ├── purchase_service.py       # Purchase workflow, confirm, return approval
│   │   ├── sale_service.py           # Sale workflow, invoice numbering, notifications
│   │   ├── staff_service.py          # Staff CRUD, payroll calculation, attendance
│   │   ├── transaction_service.py    # Account management, transaction recording
│   │   ├── production_service.py     # Production order lifecycle
│   │   └── report_service.py         # All report query orchestration
│   │
│   ├── repositories/                 # Data access layer
│   │   ├── __init__.py
│   │   ├── base_repo.py              # Generic CRUD base class
│   │   ├── auth_repo.py
│   │   ├── supplier_repo.py
│   │   ├── customer_repo.py
│   │   ├── inventory_repo.py
│   │   ├── purchase_repo.py
│   │   ├── sale_repo.py
│   │   ├── staff_repo.py
│   │   ├── transaction_repo.py
│   │   ├── production_repo.py
│   │   └── report_repo.py            # Complex report queries (window functions, etc.)
│   │
│   ├── tasks/                        # ARQ background workers
│   │   ├── __init__.py
│   │   ├── worker.py                 # ARQ WorkerSettings, job registry
│   │   ├── notifications.py          # send_due_invoice_notifications()
│   │   ├── stock_alerts.py           # check_low_stock()
│   │   ├── report_refresh.py         # refresh_materialized_views()
│   │   └── report_export.py          # generate_report_export() (CSV/Excel)
│   │
│   └── utils/                        # Pure utility functions
│       ├── __init__.py
│       ├── invoice_number.py         # Invoice/PO number generator (INV-2026-00001)
│       ├── date_helpers.py           # Date range parsing, fiscal period helpers
│       ├── pagination.py             # Pagination parameter helpers
│       └── currency.py               # Rounding, formatting helpers
│
├── alembic/                          # Database migrations
│   ├── env.py                        # Alembic environment config (async)
│   ├── script.py.mako                # Migration template
│   └── versions/                     # Auto-generated migration files
│       ├── 0001_initial_schema.py
│       ├── 0002_add_audit_log.py
│       └── ...
│
├── tests/                            # Test suite
│   ├── conftest.py                   # Shared fixtures (test DB, test client, factories)
│   ├── factories/                    # factory_boy model factories
│   │   ├── __init__.py
│   │   ├── auth_factory.py
│   │   ├── supplier_factory.py
│   │   ├── customer_factory.py
│   │   ├── inventory_factory.py
│   │   ├── purchase_factory.py
│   │   └── sale_factory.py
│   ├── unit/                         # Unit tests (services, utils)
│   │   ├── test_invoice_numbering.py
│   │   ├── test_salary_calculation.py
│   │   └── test_aging_calculation.py
│   ├── integration/                  # Integration tests (service + real DB)
│   │   ├── test_purchase_confirm.py
│   │   ├── test_sale_confirm.py
│   │   ├── test_production_complete.py
│   │   └── test_stock_movements.py
│   └── api/                          # End-to-end API tests
│       ├── test_auth_endpoints.py
│       ├── test_supplier_endpoints.py
│       ├── test_customer_endpoints.py
│       ├── test_inventory_endpoints.py
│       ├── test_purchase_endpoints.py
│       ├── test_sale_endpoints.py
│       ├── test_staff_endpoints.py
│       ├── test_transaction_endpoints.py
│       ├── test_production_endpoints.py
│       └── test_report_endpoints.py
│
├── .env                              # Local environment variables (never commit)
├── .env.example                      # Template for environment variables
├── .gitignore
├── alembic.ini                       # Alembic configuration file
├── pyproject.toml                    # Project metadata + dependencies (Poetry/uv)
├── Dockerfile                        # Production container image
├── docker-compose.yml                # Local dev: app + postgres + redis
└── README.md                         # Setup & run instructions
```

---

## Key File Descriptions

### `app/main.py`

The application entry point. Responsibilities:
- Creates the `FastAPI()` instance with metadata
- Registers all middleware (CORS, RequestID, GZip, logging)
- Registers global exception handlers
- Includes the `api_v1_router`
- Defines `/health` and `/metrics` endpoints
- On startup: verifies DB connection, initializes ARQ worker

### `app/core/config.py`

Single source of truth for all configuration. All values read from environment variables. Example:
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/smartledger
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<random-256-bit-key>
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

### `app/core/database.py`

- Creates async SQLAlchemy engine
- Provides `get_db()` async generator (FastAPI dependency)
- Connection pool: `pool_size=20`, `max_overflow=10`

### `app/models/base.py`

Defines two reusable base classes:
- `Base`: SQLAlchemy `DeclarativeBase`
- `TimestampMixin`: adds `created_at`, `updated_at` (auto-set via SQLAlchemy events)
- `AuditMixin`: adds `created_by` (FK to users)

### `app/api/v1/router.py`

Imports and includes all endpoint routers:
```python
api_v1_router = APIRouter()
api_v1_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_v1_router.include_router(suppliers_router, prefix="/suppliers", tags=["Suppliers"])
# ... all modules
```

### `app/repositories/base_repo.py`

Generic async CRUD:
```python
class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    async def get(self, db, id) -> ModelT | None
    async def get_or_404(self, db, id) -> ModelT
    async def list(self, db, *, skip, limit, filters) -> list[ModelT]
    async def create(self, db, obj_in) -> ModelT
    async def update(self, db, db_obj, obj_in) -> ModelT
    async def soft_delete(self, db, id) -> None
```

### `app/tasks/worker.py`

ARQ worker configuration:
```python
class WorkerSettings:
    functions = [
        send_due_invoice_notifications,
        check_low_stock,
        refresh_materialized_views,
        generate_report_export,
    ]
    cron_jobs = [
        cron(check_low_stock, hour=7),
        cron(send_due_invoice_notifications, hour=8),
        cron(refresh_materialized_views, hour=2),
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | Async PostgreSQL DSN |
| `REDIS_URL` | Yes | — | Redis DSN for ARQ + rate limiting |
| `SECRET_KEY` | Yes | — | JWT signing key (min 32 chars) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | 15 | JWT access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | 7 | JWT refresh token lifetime |
| `ENVIRONMENT` | No | development | development \| staging \| production |
| `LOG_LEVEL` | No | INFO | DEBUG \| INFO \| WARNING \| ERROR |
| `ALLOWED_ORIGINS` | No | * | CORS allowed origins (comma-separated) |
| `DB_POOL_SIZE` | No | 20 | SQLAlchemy connection pool size |

---

## Naming Conventions

| Artifact | Convention | Example |
|----------|-----------|---------|
| Python files | `snake_case.py` | `purchase_service.py` |
| Python classes | `PascalCase` | `PurchaseService` |
| Python functions | `snake_case` | `confirm_purchase` |
| DB tables | `snake_case`, plural | `purchase_items` |
| DB columns | `snake_case` | `created_at`, `supplier_id` |
| API endpoints | `kebab-case` (path) | `/sales/{id}/confirm` |
| Pydantic schemas | `PascalCase` + suffix | `PurchaseCreate`, `PurchaseOut` |
| Enum values | `UPPER_SNAKE_CASE` | `PaymentType.CASH` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_CREDIT_LIMIT = 1_000_000` |
