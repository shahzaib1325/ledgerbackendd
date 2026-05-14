# SmartLedger — API Conventions & Standards

## 1. Base URL

```
Production:   https://api.smartledger.com/api/v1
Development:  http://localhost:8000/api/v1
```

---

## 2. Authentication

All endpoints (except `/auth/login`) require a valid JWT Bearer token:

```
Authorization: Bearer <access_token>
```

### Token Flow

```
POST /auth/login
  → returns: { access_token, refresh_token, token_type: "bearer" }

POST /auth/refresh
  body: { refresh_token: "..." }
  → returns: { access_token, refresh_token }   (rotated)

POST /auth/logout
  → blacklists current refresh token JTI in Redis
```

Access tokens expire in **15 minutes**. Refresh tokens expire in **7 days**.

---

## 3. Standard Response Envelope

Every API response (success or error) uses this wrapper:

### Success Response
```json
{
  "success": true,
  "data": { ... },
  "meta": null
}
```

### Paginated List Response
```json
{
  "success": true,
  "data": [ ... ],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 154,
    "pages": 8
  }
}
```

### Error Response
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Item 'Rice 1kg' only has 5 units in stock, requested 20.",
    "field": "items[2].quantity"
  }
}
```

**Rules:**
- `data` is always present (null on error)
- `error` is always present (null on success)
- `meta` is always present (null for non-list responses)

---

## 4. HTTP Status Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| 200 | OK | Successful GET, PUT |
| 201 | Created | Successful POST (resource created) |
| 204 | No Content | Successful DELETE |
| 400 | Bad Request | Malformed request body (JSON parse error) |
| 401 | Unauthorized | Missing or expired token |
| 403 | Forbidden | Valid token but insufficient permission (RBAC) |
| 404 | Not Found | Resource does not exist |
| 409 | Conflict | Business rule violation (duplicate, wrong state) |
| 422 | Unprocessable Entity | Pydantic validation failure |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unhandled exception |

---

## 5. Error Codes Reference

| Code | HTTP | Description |
|------|------|-------------|
| `INVALID_CREDENTIALS` | 401 | Wrong username or password |
| `TOKEN_EXPIRED` | 401 | JWT access token has expired |
| `TOKEN_INVALID` | 401 | Malformed or blacklisted token |
| `PERMISSION_DENIED` | 403 | User role lacks required permission |
| `NOT_FOUND` | 404 | Record not found |
| `DUPLICATE_INVOICE_NO` | 409 | Invoice number already exists |
| `INSUFFICIENT_STOCK` | 409 | Stock too low to complete sale/production |
| `CREDIT_LIMIT_EXCEEDED` | 409 | Sale would exceed customer credit limit |
| `INVALID_STATUS_TRANSITION` | 409 | Cannot perform action in current status |
| `ENTITY_IN_USE` | 409 | Cannot delete — referenced by other records |
| `DUPLICATE_SALARY_PAYMENT` | 409 | Salary already paid for this month/year |
| `VALIDATION_ERROR` | 422 | Field-level Pydantic validation failure |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## 6. Pagination

All list endpoints support cursor-free **page/limit** pagination:

### Query Parameters
| Parameter | Type | Default | Max | Description |
|-----------|------|---------|-----|-------------|
| `page` | int | 1 | — | Page number (1-indexed) |
| `limit` | int | 20 | 100 | Items per page |

### Example
```
GET /api/v1/suppliers?page=2&limit=10
```

### Response Meta
```json
"meta": {
  "page": 2,
  "limit": 10,
  "total": 87,
  "pages": 9
}
```

---

## 7. Filtering & Sorting

### Common Query Parameters (on list endpoints)

| Parameter | Type | Description |
|-----------|------|-------------|
| `search` | string | Full-text search on name/invoice_no |
| `from_date` | date (YYYY-MM-DD) | Filter from date (inclusive) |
| `to_date` | date (YYYY-MM-DD) | Filter to date (inclusive) |
| `status` | string | Filter by status enum value |
| `is_active` | bool | Filter active/inactive (default: true) |
| `sort_by` | string | Column to sort by |
| `sort_order` | `asc` \| `desc` | Sort direction (default: desc) |

### Module-Specific Filters

**Purchases / Sales:**
- `supplier_id` / `customer_id` — filter by party
- `payment_type` — `cash` / `credit` / `partial`

**Inventory:**
- `category_id` — filter by category
- `item_type` — `purchased` / `produced`
- `low_stock` — `true` to show only items below reorder level

**Staff:**
- `staff_type` — `permanent` / `temporary`
- `department` — filter by department name

**Transactions:**
- `account_id` — filter by account
- `transaction_type` — `debit` / `credit`
- `reference_type` — e.g., `sale`, `purchase`

**Reports:**
- `from_date` + `to_date` required for all financial reports
- `customer_id` / `supplier_id` for ledger reports

---

## 8. Request Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | Yes (all except login) | `Bearer <token>` |
| `Content-Type` | Yes (POST/PUT) | `application/json` |
| `Accept` | No | `application/json` (default) |
| `X-Request-ID` | No | Client-provided request ID for tracing |

The server always returns `X-Request-ID` in the response (generates one if not provided).

---

## 9. Endpoint Naming Conventions

| Pattern | Method | Description |
|---------|--------|-------------|
| `/resources` | GET | List all |
| `/resources` | POST | Create new |
| `/resources/{id}` | GET | Get by ID |
| `/resources/{id}` | PUT | Full update |
| `/resources/{id}` | PATCH | Partial update (if needed) |
| `/resources/{id}` | DELETE | Soft delete |
| `/resources/{id}/action` | POST | State-changing action (confirm, approve) |
| `/resources/{id}/sub-resource` | GET/POST | Nested resource |
| `/reports/report-name` | GET | Report query |

### Examples
```
GET    /suppliers                         List suppliers
POST   /suppliers                         Create supplier
GET    /suppliers/42                      Get supplier #42
PUT    /suppliers/42                      Update supplier #42
DELETE /suppliers/42                      Deactivate supplier #42
GET    /suppliers/42/ledger               Supplier #42 ledger
POST   /suppliers/42/payments             Record payment to supplier #42
POST   /purchases/17/confirm              Confirm purchase #17
POST   /purchases/17/returns              Create return for purchase #17
PUT    /purchases/returns/5/approve       Approve return #5
GET    /reports/profit-loss?from_date=... Profit & loss report
```

---

## 10. Request Body Standards

### Create Request
Only include fields the client can set. Never expose `id`, `created_at`, computed fields.

```json
POST /suppliers
{
  "name": "Ahmed Traders",
  "phone": "0300-1234567",
  "email": "ahmed@traders.com",
  "address": "Karachi, Pakistan",
  "opening_balance": 50000.00,
  "balance_type": "payable",
  "notes": "Primary rice supplier"
}
```

### Update Request
All fields optional (partial update accepted even on PUT):
```json
PUT /suppliers/42
{
  "phone": "0311-9876543",
  "notes": "Updated contact number"
}
```

### Action Request
State-transition endpoints may accept an optional body:
```json
POST /purchases/17/confirm
{
  "notes": "Verified and signed off by manager"
}
```

---

## 11. Response Body Standards

### Single Resource
```json
{
  "success": true,
  "data": {
    "id": 42,
    "name": "Ahmed Traders",
    "phone": "0300-1234567",
    "email": "ahmed@traders.com",
    "address": "Karachi, Pakistan",
    "balance": 125000.00,
    "balance_type": "payable",
    "is_active": true,
    "created_at": "2026-01-15T09:30:00Z",
    "updated_at": "2026-04-10T14:22:00Z"
  },
  "meta": null
}
```

### List Resource
```json
{
  "success": true,
  "data": [
    { "id": 42, "name": "Ahmed Traders", "balance": 125000.00, ... },
    { "id": 43, "name": "Karachi Wholesale", "balance": 30000.00, ... }
  ],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 87,
    "pages": 5
  }
}
```

---

## 12. Date & Time Format

| Type | Format | Example |
|------|--------|---------|
| Date | `YYYY-MM-DD` | `2026-04-16` |
| DateTime | ISO 8601 UTC | `2026-04-16T09:30:00Z` |
| Month/Year | `YYYY-MM` | `2026-04` |

All timestamps stored and returned in **UTC**. Frontend handles timezone conversion.

---

## 13. Numeric Fields

- All monetary amounts: `NUMERIC(15,2)` → represented as JSON number with 2 decimal places
- All quantity fields: `NUMERIC(15,3)` → 3 decimal places (for fractional units like kg)
- Never return monetary values as strings
- Example: `"total_amount": 15000.50`

---

## 14. Enum Fields

Enums are returned as lowercase strings matching the PostgreSQL enum values:

```json
{
  "payment_type": "credit",
  "status": "confirmed",
  "payment_mode": "bank"
}
```

---

## 15. Soft Delete Behavior

`DELETE /resources/{id}` does not remove the record. It sets `is_active = false`.

- List endpoints return only `is_active = true` records by default
- Pass `?is_active=false` to see deleted records (admin only)
- A deleted record's ID can still be referenced in historical records (purchases, sales, etc.)
- Re-activation: `PUT /resources/{id}` with `{ "is_active": true }` (admin only)

---

## 16. Validation Rules (Pydantic)

### Common Field Rules
| Field | Rule |
|-------|------|
| `name` | min 1 char, max 200 chars, stripped of whitespace |
| `phone` | optional, max 20 chars |
| `email` | valid email format if provided |
| `amount` | positive decimal, max 2 decimal places |
| `quantity` | positive decimal, max 3 decimal places |
| `date` | not in the future (for past transactions) |
| `from_date` | must be ≤ `to_date` |
| `items` | non-empty list for purchase/sale create |

---

## 17. Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `POST /auth/login` | 10 requests / minute per IP |
| `POST /auth/refresh` | 30 requests / minute per IP |
| All other endpoints | 200 requests / minute per authenticated user |

Rate limit headers returned on every response:
```
X-RateLimit-Limit: 200
X-RateLimit-Remaining: 187
X-RateLimit-Reset: 1713261600
```

---

## 18. OpenAPI Documentation

Available at:
- `/docs` — Swagger UI (disabled in production)
- `/redoc` — ReDoc (disabled in production)
- `/openapi.json` — Raw schema (always available, used by internal tools)

All endpoints are tagged by module for easy navigation in Swagger UI.
