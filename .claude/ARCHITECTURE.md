# SmartLedger — Architecture

## 1. Architectural Style

SmartLedger follows a **Layered Architecture** (also called N-Tier) with clean separation between concerns. Each layer can only communicate with the layer directly beneath it. This makes the codebase testable, maintainable, and easy to extend.

```
┌────────────────────────────────────────────┐
│              Client (Frontend)             │
└───────────────────┬────────────────────────┘
                    │  HTTP / JSON
┌───────────────────▼────────────────────────┐
│           API Layer (Routers)              │  FastAPI route handlers
│  - Request validation (Pydantic schemas)   │
│  - Auth dependency injection               │
│  - Response serialization                  │
└───────────────────┬────────────────────────┘
                    │
┌───────────────────▼────────────────────────┐
│         Service Layer (Business Logic)     │  Pure Python classes
│  - Business rules enforcement              │
│  - Cross-module coordination               │
│  - Workflow orchestration                  │
└───────────────────┬────────────────────────┘
                    │
┌───────────────────▼────────────────────────┐
│       Repository Layer (Data Access)       │  SQLAlchemy async queries
│  - All DB reads and writes                 │
│  - No business logic here                  │
│  - Returns domain model instances          │
└───────────────────┬────────────────────────┘
                    │
┌───────────────────▼────────────────────────┐
│          Database (PostgreSQL 16)          │
│  - Tables, constraints, indexes            │
│  - Sequences for invoice numbers           │
│  - Materialized views for reports          │
└────────────────────────────────────────────┘
```

---

## 2. Layer Responsibilities

### 2.1 API Layer (`app/api/v1/endpoints/`)

- One file per module (e.g., `purchases.py`, `sales.py`)
- Defines `APIRouter` with prefix and tags
- Handles HTTP method → function mapping
- Calls Pydantic schemas for request body parsing and response serialization
- Injects dependencies: `db: AsyncSession`, `current_user: User`
- **No business logic here** — delegates entirely to the service layer
- Returns standardized response envelope

```python
# Example structure
@router.post("/purchases/{id}/confirm", response_model=PurchaseOut)
async def confirm_purchase(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("purchases", "write")),
):
    return await purchase_service.confirm(db, id, current_user.id)
```

### 2.2 Service Layer (`app/services/`)

- One file per module (e.g., `purchase_service.py`)
- Contains all business rules, validations, and workflow steps
- Calls one or more repositories
- Manages DB transactions (`async with db.begin()`)
- Raises custom domain exceptions (`InsufficientStockError`, etc.)
- Calls other services when cross-module coordination is needed

```python
# Example: confirm_purchase calls stock_service and transaction_service
class PurchaseService:
    async def confirm(self, db, purchase_id, actor_id):
        async with db.begin():
            purchase = await purchase_repo.get_or_404(db, purchase_id)
            for item in purchase.items:
                await stock_service.add_stock(db, item.item_id, item.quantity, ...)
            await supplier_service.update_balance(db, purchase.supplier_id, ...)
            await transaction_service.record(db, ...)
            purchase.status = PurchaseStatus.CONFIRMED
```

### 2.3 Repository Layer (`app/repositories/`)

- One file per model/entity (e.g., `purchase_repo.py`)
- Only contains SQLAlchemy queries
- Methods: `get`, `get_or_404`, `list`, `create`, `update`, `delete`
- Returns ORM model instances or raises `HTTPException(404)`
- No business logic, no cross-table coordination

```python
class PurchaseRepository:
    async def get_or_404(self, db: AsyncSession, id: int) -> Purchase:
        result = await db.execute(select(Purchase).where(Purchase.id == id))
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail="Purchase not found")
        return obj
```

### 2.4 Model Layer (`app/models/`)

- SQLAlchemy declarative ORM models
- One file per module group (e.g., `purchase.py`, `inventory.py`)
- Defines table columns, relationships, and DB-level constraints
- All models inherit from `Base` (defined in `app/core/database.py`)

### 2.5 Schema Layer (`app/schemas/`)

- Pydantic v2 models for request validation and response serialization
- Naming convention: `{Entity}Create`, `{Entity}Update`, `{Entity}Out`, `{Entity}ListOut`
- Validators for business constraints (e.g., `quantity > 0`, valid date ranges)
- Separate input schemas from output schemas (never expose internal fields)

---

## 3. Dependency Flow

```
Router → Service → Repository → ORM Model → PostgreSQL

Router → Schema (Pydantic) for I/O validation
Router → Depends(get_db) for DB session
Router → Depends(require_permission) for RBAC
Service → Other Services (cross-module)
Service → Background Task Queue (ARQ/Redis)
```

**Rule**: Dependencies only flow downward. A repository never imports a service. A model never imports a schema.

---

## 4. Database Session Management

- Use `async_sessionmaker` from SQLAlchemy 2.0
- Session per request via FastAPI `Depends(get_db)`
- Sessions are automatically closed after the request completes
- Transactions managed explicitly in service layer for multi-step operations

```python
# app/core/database.py
#
# pool_size must be calculated — never left at the SQLAlchemy default.
# Formula: pool_size = floor((postgres_max_connections - reserved) / num_workers)
# Example: (100 - 10) / 4 workers = 22 → use pool_size=20, max_overflow=2
#
# Beyond 3 uvicorn workers, introduce PgBouncer (transaction-mode) between
# the app and PostgreSQL to avoid exhausting max_connections.
#
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,       # set per-worker via env var
    max_overflow=settings.DB_MAX_OVERFLOW,
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

---

## 5. Error Handling Strategy

### 5.1 Exception Hierarchy

```
Exception
└── AppException (base)
    ├── ValidationException (422)      — business rule violations
    │   ├── InsufficientStockError
    │   ├── CreditLimitExceededError
    │   └── DuplicateInvoiceError
    ├── NotFoundException (404)        — record not found
    ├── ForbiddenException (403)       — RBAC violation
    └── ConflictException (409)        — state conflict (e.g., edit confirmed purchase)
```

### 5.2 Global Exception Handler

Registered in `main.py`. Catches all `AppException` subclasses and converts them to the standard error response format:

```json
{
  "success": false,
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Item 'Rice 1kg' only has 5 units in stock, requested 20.",
    "field": "quantity"
  }
}
```

### 5.3 Unhandled Exceptions

All unhandled exceptions are caught, logged with full traceback via `structlog`, and return a generic `500` response without exposing internal details.

---

## 6. Authentication & Authorization Flow

```
Request
  │
  ▼
JWT Middleware (extracts token from Authorization: Bearer <token>)
  │
  ▼
Depends(get_current_user)  → decode JWT → load user from DB → attach to request
  │
  ▼
Depends(require_permission("module", "action"))  → check roles_permissions table
  │                                                → raise 403 if denied
  ▼
Route Handler
```

---

## 7. Background Task Architecture

Uses **ARQ** (Async Redis Queue) for background jobs.

```
FastAPI App                 Redis               ARQ Worker
    │                         │                     │
    │── enqueue_job() ───────►│                     │
    │                         │◄── poll ────────────│
    │                         │─── job data ───────►│
    │                         │                     │── execute job
    │                         │                     │── update result
    │                         │◄── result ──────────│
```

**Job Types:**
- `send_due_invoice_notifications` — daily at 08:00
- `check_low_stock` — daily at 07:00
- `refresh_materialized_views` — nightly at 02:00
- `generate_report_export` — on-demand (triggered by API, result fetched async)

---

## 8. Request Lifecycle

```
1. HTTP Request arrives at uvicorn
2. FastAPI middleware stack:
   a. RequestID middleware (injects X-Request-ID header)
   b. CORS middleware
   c. GZip compression middleware
   d. Structured logging middleware (logs method, path, status, duration)
3. Route matching
4. Dependency resolution (DB session, current user, RBAC check)
5. Pydantic request body validation → 422 if invalid
6. Route handler invoked → calls service
7. Service performs business logic → calls repositories
8. Repository executes DB query
9. Response serialized via Pydantic response_model
10. Logging middleware records response
11. DB session closed
12. HTTP Response returned
```

---

## 9. Configuration Management

Uses **pydantic-settings** with `.env` file support:

```python
# app/core/config.py
class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENVIRONMENT: str = "development"  # development | staging | production
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env")
```

**Never hardcode secrets.** All secrets come from environment variables.

---

## 10. API Versioning

All routes are prefixed with `/api/v1/`. When breaking changes are needed, a `/api/v2/` router is added alongside v1 (not replacing it) to maintain backward compatibility.

```python
# main.py
app.include_router(api_v1_router, prefix="/api/v1")
```

---

## 11. Observability

| Concern | Tool | Endpoint / Location |
|---------|------|---------------------|
| Structured logs | structlog | stdout (JSON) |
| Health check | FastAPI | `GET /health` |
| Metrics | prometheus-fastapi-instrumentator | `GET /metrics` |
| OpenAPI docs | FastAPI built-in | `GET /docs` (dev only) |
| Request tracing | X-Request-ID header | Every request/response |

In production, `/docs` and `/redoc` are disabled. OpenAPI schema is only accessible internally.

---

## 12. Testing Strategy

| Test Type | Location | Tools |
|-----------|----------|-------|
| Unit tests | `tests/unit/` | pytest, unittest.mock |
| Integration tests | `tests/integration/` | pytest-asyncio, real test DB |
| API tests | `tests/api/` | httpx (async test client) |
| Factory fixtures | `tests/factories/` | factory_boy |

**Test DB**: A separate PostgreSQL database (`smartledger_test`) is used for integration and API tests. It is created fresh before the test session and torn down after.

Every financial operation (purchase confirm, sale confirm, production complete) must have an integration test that verifies:
1. Stock changed correctly
2. Balance updated correctly
3. Transaction record created
4. Correct status set
