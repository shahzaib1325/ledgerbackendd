# SmartLedger — Frontend Developer Overview

> **Scope:** This document covers everything a frontend developer needs to build the SmartLedger admin interface. For now, the frontend targets the **admin role only**. Role-based UI differences are intentionally excluded to keep the initial build simple.

---

## 1. What Is SmartLedger?

SmartLedger is a business ERP (Enterprise Resource Planning) web application for small-to-medium businesses. It covers the full operational cycle of a product-based business:

- Buy raw materials from suppliers
- Manage inventory
- Produce finished goods
- Sell to customers
- Pay staff
- Track all money movement
- Generate financial reports

The admin user has full access to every part of the system.

---

## 2. Tech Stack (Backend)

| Concern | Technology |
|---|---|
| Framework | FastAPI (Python) |
| Database | PostgreSQL 18 |
| Auth | JWT (access + refresh tokens) |
| Cache / Queue | Redis |
| API style | REST, JSON |
| Base URL | `http://localhost:8000/api/v1` |

---

## 3. Authentication

### How It Works

1. The admin logs in with username + password → the server returns two tokens.
2. The **access token** is short-lived (15 minutes). Send it in every API request.
3. The **refresh token** is long-lived (7 days). Use it to get a new access token when the current one expires.
4. On logout the access token is invalidated server-side.

### Login

```
POST /auth/login
Body: { "email": "admin@smartledger.com", "password": "AdminPass1!" }
```

**Response:**
```json
{
  "success": true,
  "data": {
    "tokens": {
      "access_token": "eyJ...",
      "refresh_token": "eyJ...",
      "token_type": "bearer",
      "expires_in": 900
    },
    "user": {
      "id": 18,
      "username": "admin",
      "email": "admin@smartledger.com",
      "full_name": "System Admin",
      "role": "admin",
      "is_active": true,
      "last_login": null,
      "created_at": "2026-04-29T09:52:41Z"
    }
  }
}
```

### Sending the Token

Every authenticated request must include the header:
```
Authorization: Bearer <access_token>
```

### Refresh Tokens

```
POST /auth/refresh
Body: { "refresh_token": "<refresh_token>" }
```

Returns a brand new access + refresh token pair. The old refresh token is immediately invalidated (token rotation — it cannot be reused). Call this when a request returns `TOKEN_EXPIRED`.

### Logout

```
POST /auth/logout
Headers: Authorization: Bearer <access_token>
```

### Register (Create a new non-admin user)

```
POST /auth/register
Body: { "username": "john", "email": "john@example.com", "password": "Pass1234!", "full_name": "John Doe" }
```
New users are created with the `staff` role by default.

---

## 4. API Response Envelope

**Every** API response — success or error — is wrapped in the same envelope. Never read raw response bodies; always read `.data` for success and `.error` for failures.

### Success
```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": null
}
```

### Success with Pagination
```json
{
  "success": true,
  "data": [ ... ],
  "error": null,
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 150,
    "total_pages": 8
  }
}
```

### Error
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable message",
    "field": "username"
  },
  "meta": null
}
```

### Common Error Codes

| Code | HTTP | Meaning |
|---|---|---|
| `INVALID_CREDENTIALS` | 401 | Wrong username or password |
| `TOKEN_EXPIRED` | 401 | Access token has expired — refresh it |
| `TOKEN_INVALID` | 401 | Token is malformed or blacklisted |
| `UNAUTHORIZED` | 401 | No token sent |
| `PERMISSION_DENIED` | 403 | Token valid but role lacks access |
| `NOT_FOUND` | 404 | Resource does not exist |
| `CONFLICT` | 409 | Duplicate (username, email, etc.) |
| `VALIDATION_ERROR` | 422 | Request body failed validation |
| `INTERNAL_ERROR` | 500 | Server-side bug |

---

## 5. Pagination & Filtering

List endpoints support these query parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Items per page (max 100) |
| `sort_by` | string | varies | Field to sort by |
| `sort_order` | `asc` / `desc` | `desc` | Sort direction |

Most list endpoints also accept entity-specific filters (e.g. `search`, `status`, `date_from`, `date_to`).

---

## 6. Modules & API Reference

Base path for all endpoints: `/api/v1`

---

### 6.1 Suppliers

Businesses or individuals you purchase goods from.

| Method | Path | Description |
|---|---|---|
| `POST` | `/suppliers` | Create a supplier |
| `GET` | `/suppliers` | List suppliers (paginated, search by name/phone) |
| `GET` | `/suppliers/{id}` | Get supplier detail |
| `PATCH` | `/suppliers/{id}` | Update supplier |
| `DELETE` | `/suppliers/{id}` | Delete supplier |
| `GET` | `/suppliers/{id}/balance` | Current outstanding balance |
| `POST` | `/suppliers/{id}/payments` | Record a payment to supplier |
| `GET` | `/suppliers/{id}/ledger` | Full transaction history with supplier |

**Key fields:** `name`, `phone`, `email`, `address`, `opening_balance`, `balance_type` (`debit`/`credit`)

---

### 6.2 Customers

Businesses or individuals you sell goods to.

| Method | Path | Description |
|---|---|---|
| `POST` | `/customers` | Create a customer |
| `GET` | `/customers` | List customers (paginated, search) |
| `GET` | `/customers/{id}` | Get customer detail |
| `PATCH` | `/customers/{id}` | Update customer |
| `DELETE` | `/customers/{id}` | Delete customer |
| `GET` | `/customers/{id}/balance` | Current outstanding balance |
| `POST` | `/customers/{id}/payments` | Record a payment received from customer |
| `GET` | `/customers/{id}/ledger` | Full transaction history with customer |

**Key fields:** `name`, `phone`, `email`, `address`, `credit_limit`, `opening_balance`, `balance_type`

---

### 6.3 Inventory

Stock items, categories, and units of measure.

#### Units of Measure
| Method | Path | Description |
|---|---|---|
| `POST` | `/inventory/units` | Create a unit (e.g. kg, litre, piece) |
| `GET` | `/inventory/units` | List all units |
| `GET` | `/inventory/units/{id}` | Get unit |
| `PATCH` | `/inventory/units/{id}` | Update unit |
| `DELETE` | `/inventory/units/{id}` | Delete unit |

#### Categories
| Method | Path | Description |
|---|---|---|
| `POST` | `/inventory/categories` | Create a category |
| `GET` | `/inventory/categories` | List categories |
| `GET` | `/inventory/categories/{id}` | Get category |
| `PATCH` | `/inventory/categories/{id}` | Update category |
| `DELETE` | `/inventory/categories/{id}` | Delete category |

#### Items
| Method | Path | Description |
|---|---|---|
| `POST` | `/inventory/items` | Create an item |
| `GET` | `/inventory/items` | List items (filter by category, type, low stock) |
| `GET` | `/inventory/items/{id}` | Get item detail |
| `PATCH` | `/inventory/items/{id}` | Update item |
| `DELETE` | `/inventory/items/{id}` | Delete item |
| `POST` | `/inventory/items/{id}/adjust` | Manual stock adjustment |
| `GET` | `/inventory/items/{id}/movements` | Stock movement history |

**Item types:** `raw_material`, `finished_good`, `consumable`

**Key fields:** `name`, `sku`, `item_type`, `category_id`, `unit_id`, `current_stock`, `reorder_level`, `cost_price`, `sale_price`

---

### 6.4 Purchases

Buying goods from suppliers.

| Method | Path | Description |
|---|---|---|
| `POST` | `/purchases` | Create a purchase order |
| `GET` | `/purchases` | List purchases (filter by supplier, status, dates) |
| `GET` | `/purchases/{id}` | Get purchase detail with line items |
| `PATCH` | `/purchases/{id}` | Update a draft purchase |
| `POST` | `/purchases/{id}/confirm` | Confirm a draft → receives stock |
| `POST` | `/purchases/{id}/receive` | Mark goods as received |
| `POST` | `/purchases/{id}/void` | Void a purchase |
| `GET` | `/purchases/{id}/payments` | List payments made for this purchase |
| `POST` | `/purchases/{id}/payments` | Record a payment for this purchase |
| `GET` | `/purchases/{id}/returns` | List returns for this purchase |
| `POST` | `/purchases/{id}/returns` | Record a return to supplier |

**Purchase statuses:** `draft` → `confirmed` → `received` → `paid` (also `void`)

**Key fields on create:** `supplier_id`, `purchase_date`, `items` (array of `item_id`, `quantity`, `unit_price`)

---

### 6.5 Sales

Selling goods to customers.

| Method | Path | Description |
|---|---|---|
| `POST` | `/sales` | Create a sale invoice |
| `GET` | `/sales` | List invoices (filter by customer, status, dates) |
| `GET` | `/sales/{id}` | Get invoice detail with line items |
| `PATCH` | `/sales/{id}` | Update a draft invoice |
| `POST` | `/sales/{id}/confirm` | Confirm invoice → deducts stock |
| `POST` | `/sales/{id}/void` | Void a draft invoice |
| `POST` | `/sales/{id}/deliver` | Mark as delivered |
| `GET` | `/sales/{id}/payments` | List payments received |
| `POST` | `/sales/{id}/payments` | Record a payment from customer |
| `GET` | `/sales/{id}/returns` | List returns from customer |
| `POST` | `/sales/{id}/returns` | Record a return from customer |

**Sale statuses:** `draft` → `confirmed` → `delivered` → `paid` (also `void`)

**Key fields on create:** `customer_id`, `invoice_date`, `items` (array of `item_id`, `quantity`, `unit_price`)

---

### 6.6 Staff

Employee management, attendance, salary, and advances.

| Method | Path | Description |
|---|---|---|
| `POST` | `/staff` | Create a staff member |
| `GET` | `/staff` | List staff (filter by type, active status) |
| `GET` | `/staff/{id}` | Get staff detail |
| `PATCH` | `/staff/{id}` | Update staff profile |
| `DELETE` | `/staff/{id}` | Deactivate staff |
| `POST` | `/staff/{id}/allowances` | Add an allowance |
| `GET` | `/staff/{id}/allowances` | List allowances |
| `POST` | `/staff/{id}/deductions` | Add a deduction |
| `GET` | `/staff/{id}/attendance` | List attendance records |
| `PATCH` | `/staff/{id}/attendance/{att_id}` | Update an attendance record |
| `POST` | `/staff/{id}/attendance/bulk` | Bulk mark attendance |
| `GET` | `/staff/{id}/payments` | List salary payments |
| `POST` | `/staff/{id}/payments` | Record salary payment |
| `GET` | `/staff/{id}/advances` | List advance payments |
| `POST` | `/staff/{id}/advances` | Record an advance |

**Staff types:** `permanent`, `daily_wage`, `contractor`

**Key fields:** `name`, `staff_type`, `designation`, `base_salary`, `join_date`, `phone`, `cnic`

---

### 6.7 Transactions (Accounts & Transfers)

Internal financial accounts and money transfers between them (e.g. bank → cash).

| Method | Path | Description |
|---|---|---|
| `POST` | `/transactions/accounts` | Create an account (bank, cash, etc.) |
| `GET` | `/transactions/accounts` | List accounts |
| `GET` | `/transactions/accounts/{id}` | Get account detail |
| `PATCH` | `/transactions/accounts/{id}` | Update account |
| `DELETE` | `/transactions/accounts/{id}` | Delete account |
| `GET` | `/transactions/accounts/{id}/transactions` | Transaction history for account |
| `POST` | `/transactions/transfers` | Transfer money between accounts |
| `GET` | `/transactions/transfers` | List all transfers |

**Account types:** `cash`, `bank`, `mobile_wallet`

---

### 6.8 Production

Manufacturing orders — consume raw materials, record labor, produce finished goods.

| Method | Path | Description |
|---|---|---|
| `POST` | `/production` | Create a production order |
| `GET` | `/production` | List orders (filter by status, dates) |
| `GET` | `/production/{id}` | Get order detail (materials, labor, costs, output) |
| `PATCH` | `/production/{id}` | Update dates/notes |
| `POST` | `/production/{id}/start` | Start a planned order |
| `POST` | `/production/{id}/complete` | Complete order + record output |
| `POST` | `/production/{id}/cancel` | Cancel an order |
| `POST` | `/production/{id}/raw-materials` | Add raw material to order |
| `POST` | `/production/{id}/labor` | Add labor entry |

**Production statuses:** `planned` → `in_progress` → `completed` (also `cancelled`)

---

### 6.9 Reports

Read-only financial and operational reports. All require `date_from` and `date_to` query params (format: `YYYY-MM-DD`) except stock-level reports.

| Method | Path | Description |
|---|---|---|
| `GET` | `/reports/profit-loss` | Revenue, costs, gross/net profit |
| `GET` | `/reports/sales-summary` | Total sales, collected, outstanding, by customer |
| `GET` | `/reports/purchase-summary` | Total purchases, paid, outstanding, by supplier |
| `GET` | `/reports/stock-summary` | Current stock levels, items below reorder |
| `GET` | `/reports/stock-movement` | Stock ins/outs over a date range |
| `GET` | `/reports/customer-balances` | All customers with outstanding amounts |
| `GET` | `/reports/supplier-balances` | All suppliers with outstanding amounts |
| `GET` | `/reports/cash-flow` | Account balances, credits, debits |
| `GET` | `/reports/payroll-summary` | Monthly salary disbursements |
| `GET` | `/reports/production-summary` | Production orders, quantities, costs |

#### Inline Export (Small Data)
Append `?format=csv` or `?format=xlsx` to any GET report URL to download the file directly.

#### Async Export (Large Data)
For large exports use the job queue:

```
# 1. Queue the export
POST /reports/{report_name}/export
Body: { "format": "csv", "params": { "date_from": "2026-01-01", "date_to": "2026-03-31" } }
Response: { "job_id": "abc123", "status": "queued", "already_running": false }

# 2. Poll for status
GET /reports/exports/{job_id}
Response: { "job_id": "abc123", "status": "complete", "download_url": "/reports/exports/abc123/download" }

# 3. Download when complete
GET /reports/exports/{job_id}/download
→ File stream (CSV or XLSX)
```

**Export statuses:** `queued` → `in_progress` → `complete` (or `failed`)

If `already_running: true` in the response, the same export is already being processed — show "export already in progress" rather than "queued."

---

### 6.10 Audit Log

A tamper-proof log of every create/update/delete action in the system.

| Method | Path | Description |
|---|---|---|
| `GET` | `/audit-logs` | Paginated audit log |

**Filters:** `table_name`, `record_id`, `user_id`, `action` (`CREATE`/`UPDATE`/`DELETE`), `date_from`, `date_to`

**Response fields:** `id`, `user_id`, `action`, `table_name`, `record_id`, `old_values`, `new_values`, `ip_address`, `created_at`

---

## 7. Core Business Workflows

### Buying (Purchase Cycle)
```
Create Purchase (draft)
    → Confirm (stock received, supplier balance updated)
    → Record Payments as you pay
    → Status reaches "paid" when fully settled
    → Return goods if needed (reduces supplier balance)
```

### Selling (Sales Cycle)
```
Create Invoice (draft)
    → Confirm (stock deducted, customer balance updated)
    → Deliver goods
    → Record Payments as customer pays
    → Status reaches "paid" when fully settled
    → Accept returns if customer sends goods back
```

### Manufacturing (Production Cycle)
```
Create Production Order (planned)
    → Add raw materials, labor, and costs
    → Start order (in_progress)
    → Complete order + record actual output quantity
    → Finished goods added to inventory stock
```

### Paying Staff
```
Staff profile has base_salary + allowances - deductions
    → Mark attendance daily/monthly
    → Generate payroll → Record salary payment
    → Advance payments deducted from next salary
```

---

## 8. Important Data Relationships

```
Supplier ──< Purchase ──< PurchaseItem >── InventoryItem
Customer ──< Sale     ──< SaleItem     >── InventoryItem

InventoryItem ──< StockMovement
               ──< ProductionRawMaterial
               ──< ProductionOutput

Staff ──< Attendance
      ──< SalaryPayment
      ──< Advance

Account ──< AccountTransaction
        ──< Transfer
```

---

## 9. Numeric / Decimal Fields

All monetary amounts and quantities are returned as **strings in JSON** (e.g. `"1250.00"`) to avoid floating-point precision loss. Parse them with a decimal library on the frontend — do not use plain JavaScript `number` for financial values.

---

## 10. Dates & Times

- **Dates** (no time): `YYYY-MM-DD` — e.g. `"2026-04-01"`
- **Datetimes** (with time): ISO 8601 UTC — e.g. `"2026-04-29T09:52:41.135490Z"`
- Always send dates in `YYYY-MM-DD` format in request bodies and query params.

---

## 11. Suggested Page Structure (Admin)

| Page | Primary API calls |
|---|---|
| Login | `POST /auth/login` |
| Dashboard | Reports: profit-loss, stock-summary, customer-balances |
| Suppliers | `/suppliers` CRUD + balance + ledger |
| Customers | `/customers` CRUD + balance + ledger |
| Inventory | `/inventory/items`, `/inventory/categories`, `/inventory/units` |
| Purchases | `/purchases` CRUD + payments + returns |
| Sales | `/sales` CRUD + payments + returns |
| Staff | `/staff` CRUD + attendance + payments + advances |
| Accounts | `/transactions/accounts` + transfers |
| Production | `/production` CRUD + start/complete/cancel |
| Reports | All `/reports/*` endpoints |
| Audit Log | `GET /audit-logs` |

---

## 12. Recommended Frontend Practices

- **Store tokens in memory** (not localStorage) to reduce XSS risk. Use a short-lived in-memory access token and persist only the refresh token in an httpOnly cookie if possible.
- **Auto-refresh:** When any request returns `TOKEN_EXPIRED` (401), attempt a token refresh and retry the original request once.
- **Optimistic UI:** For status transitions (confirm, deliver, void) the response returns the updated object — use it directly instead of refetching.
- **Decimal handling:** Use a library like `decimal.js` or `big.js` for all financial calculations displayed to the user.
- **Pagination:** All list pages use `page` + `page_size`. Keep page state in the URL query string so the browser back button works.
- **Date pickers:** Always send dates as `YYYY-MM-DD`. Store selected dates as strings, not Date objects, to avoid timezone shift bugs.
