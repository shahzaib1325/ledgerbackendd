# SmartLedger — Complete Database Schema

## Design Principles

1. **Soft deletes everywhere** — `is_active BOOLEAN DEFAULT TRUE`, never `DROP` or `DELETE` on business records
2. **Audit columns on all tables** — `created_at`, `updated_at`, `created_by`
3. **Immutable stock** — stock changed only via `stock_movements`, never direct column update
4. **Computed balances** — supplier/customer balance derived from transaction aggregates
5. **Enum types** — PostgreSQL native `ENUM` types for status/type fields
6. **Cascades** — `ON DELETE RESTRICT` by default; no orphan records allowed

---

## PostgreSQL ENUM Types

```sql
CREATE TYPE user_role          AS ENUM ('admin', 'manager', 'staff');
CREATE TYPE payment_mode       AS ENUM ('cash', 'bank', 'digital');
CREATE TYPE payment_type       AS ENUM ('cash', 'credit', 'partial');
CREATE TYPE balance_type       AS ENUM ('payable', 'receivable');
CREATE TYPE item_type          AS ENUM ('purchased', 'produced');
CREATE TYPE movement_type      AS ENUM (
    'purchase_in', 'sale_out', 'production_in', 'production_out',
    'return_in', 'return_out', 'adjustment'
);
CREATE TYPE purchase_status    AS ENUM ('draft', 'confirmed', 'returned', 'void');
CREATE TYPE sale_status        AS ENUM ('draft', 'confirmed', 'partially_paid', 'paid', 'returned', 'void');
CREATE TYPE return_status      AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE staff_type         AS ENUM ('permanent', 'temporary');
CREATE TYPE attendance_status  AS ENUM ('present', 'absent', 'half_day', 'leave');
CREATE TYPE account_type       AS ENUM ('cash', 'bank', 'digital');
CREATE TYPE transaction_type   AS ENUM ('debit', 'credit');
CREATE TYPE reference_type     AS ENUM (
    'purchase', 'sale', 'purchase_payment', 'sale_payment',
    'salary', 'advance', 'transfer', 'expense', 'adjustment'
);
CREATE TYPE production_status  AS ENUM ('planned', 'in_progress', 'completed', 'cancelled');
CREATE TYPE notification_type  AS ENUM ('due', 'overdue', 'credit_limit', 'low_stock');
CREATE TYPE audit_action       AS ENUM ('CREATE', 'UPDATE', 'DELETE');
```

---

## Schema: Auth & Users

### `users`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | Auto-increment primary key |
| username | VARCHAR(50) | UNIQUE NOT NULL | Login username |
| email | VARCHAR(255) | UNIQUE NOT NULL | Email address |
| hashed_password | VARCHAR(255) | NOT NULL | bcrypt hash |
| full_name | VARCHAR(150) | NOT NULL | Display name |
| role | user_role | NOT NULL DEFAULT 'staff' | Role enum |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | Soft delete flag |
| last_login | TIMESTAMPTZ | | Last successful login |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_users_username`, `idx_users_email`

### `roles_permissions`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| role | user_role | NOT NULL | Which role |
| module | VARCHAR(50) | NOT NULL | Module name (e.g., 'purchases') |
| can_read | BOOLEAN | NOT NULL DEFAULT FALSE | |
| can_write | BOOLEAN | NOT NULL DEFAULT FALSE | |
| can_delete | BOOLEAN | NOT NULL DEFAULT FALSE | |

**Unique:** `(role, module)`

### `token_blacklist`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| jti | VARCHAR(36) | UNIQUE NOT NULL | JWT ID (UUID) |
| expires_at | TIMESTAMPTZ | NOT NULL | When to purge this record |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Index:** `idx_token_blacklist_jti`

---

## Schema: Suppliers

### `suppliers`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| name | VARCHAR(200) | NOT NULL | Supplier name |
| phone | VARCHAR(20) | | Contact number |
| email | VARCHAR(255) | | Email |
| address | TEXT | | Physical address |
| opening_balance | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Balance at time of creation |
| balance | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Current running balance |
| balance_type | balance_type | NOT NULL DEFAULT 'payable' | payable or receivable |
| notes | TEXT | | Internal notes |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | Soft delete |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_suppliers_name`, `idx_suppliers_is_active`

### `supplier_payments`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| supplier_id | INT | FK → suppliers(id) NOT NULL | |
| amount | NUMERIC(15,2) | NOT NULL CHECK (amount > 0) | Payment amount |
| payment_mode | payment_mode | NOT NULL | cash / bank / digital |
| reference_no | VARCHAR(100) | | Cheque/transfer ref |
| account_id | INT | FK → accounts(id) | Which account was debited |
| note | TEXT | | |
| paid_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

---

## Schema: Customers

### `customers`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| name | VARCHAR(200) | NOT NULL | |
| phone | VARCHAR(20) | | |
| email | VARCHAR(255) | | |
| address | TEXT | | |
| credit_limit | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Max credit allowed |
| opening_balance | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| balance | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Running receivable balance |
| balance_type | balance_type | NOT NULL DEFAULT 'receivable' | |
| notes | TEXT | | |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_customers_name`, `idx_customers_balance`

### `customer_payments`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| customer_id | INT | FK → customers(id) NOT NULL | |
| amount | NUMERIC(15,2) | NOT NULL CHECK (amount > 0) | |
| payment_mode | payment_mode | NOT NULL | |
| reference_no | VARCHAR(100) | | |
| account_id | INT | FK → accounts(id) | Account credited |
| note | TEXT | | |
| received_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

---

## Schema: Inventory

### `units`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| name | VARCHAR(50) | UNIQUE NOT NULL | Full name (Kilogram) |
| abbreviation | VARCHAR(10) | UNIQUE NOT NULL | Short form (kg) |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

### `categories`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| name | VARCHAR(100) | NOT NULL | |
| parent_id | INT | FK → categories(id) NULL | Self-referential |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Unique:** `(name, parent_id)`

### `items`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| name | VARCHAR(200) | NOT NULL | Item name |
| sku | VARCHAR(100) | UNIQUE | Optional SKU/barcode |
| category_id | INT | FK → categories(id) NULL | |
| unit_id | INT | FK → units(id) NOT NULL | Base unit |
| item_type | item_type | NOT NULL | purchased or produced |
| current_stock | NUMERIC(15,3) | NOT NULL DEFAULT 0 CHECK (current_stock >= 0) | |
| reorder_level | NUMERIC(15,3) | NOT NULL DEFAULT 0 | Alert threshold |
| sale_price | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Default sale price |
| purchase_price | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Latest/weighted average cost |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_items_name`, `idx_items_category`, `idx_items_is_active`

### `stock_movements`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| item_id | INT | FK → items(id) NOT NULL | |
| movement_type | movement_type | NOT NULL | |
| quantity | NUMERIC(15,3) | NOT NULL CHECK (quantity != 0) | Positive = in, negative = out |
| stock_before | NUMERIC(15,3) | NOT NULL | Stock level before this move |
| stock_after | NUMERIC(15,3) | NOT NULL | Stock level after this move |
| reference_type | VARCHAR(50) | | 'purchase', 'sale', etc. |
| reference_id | INT | | PK of the source record |
| note | TEXT | | |
| moved_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| created_by | INT | FK → users(id) | |

**Indexes:** `idx_stock_movements_item`, `idx_stock_movements_reference`, `idx_stock_movements_moved_at`

---

## Schema: Purchases

### `purchases`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| supplier_id | INT | FK → suppliers(id) NOT NULL | |
| invoice_no | VARCHAR(100) | | Supplier's invoice number |
| purchase_date | DATE | NOT NULL DEFAULT CURRENT_DATE | |
| payment_type | payment_type | NOT NULL | cash / credit / partial |
| subtotal | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Before discount |
| discount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| total_amount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | After discount |
| paid_amount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Payments received |
| due_amount | NUMERIC(15,2) | GENERATED ALWAYS AS (total_amount - paid_amount) STORED | |
| status | purchase_status | NOT NULL DEFAULT 'draft' | |
| notes | TEXT | | |
| confirmed_at | TIMESTAMPTZ | | When status changed to confirmed |
| confirmed_by | INT | FK → users(id) | |
| created_by | INT | FK → users(id) NOT NULL | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_purchases_supplier`, `idx_purchases_date`, `idx_purchases_status`

### `purchase_items`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| purchase_id | INT | FK → purchases(id) ON DELETE CASCADE NOT NULL | |
| item_id | INT | FK → items(id) NOT NULL | |
| unit_id | INT | FK → units(id) NOT NULL | Unit at time of purchase |
| quantity | NUMERIC(15,3) | NOT NULL CHECK (quantity > 0) | |
| unit_price | NUMERIC(15,2) | NOT NULL CHECK (unit_price >= 0) | |
| discount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Per-line discount |
| total_price | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |

### `purchase_payments`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| purchase_id | INT | FK → purchases(id) NOT NULL | |
| amount | NUMERIC(15,2) | NOT NULL CHECK (amount > 0) | |
| payment_mode | payment_mode | NOT NULL | |
| account_id | INT | FK → accounts(id) | |
| reference_no | VARCHAR(100) | | |
| paid_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| created_by | INT | FK → users(id) | |

### `purchase_returns`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| purchase_id | INT | FK → purchases(id) NOT NULL | |
| return_date | DATE | NOT NULL DEFAULT CURRENT_DATE | |
| reason | TEXT | | |
| total_amount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| status | return_status | NOT NULL DEFAULT 'pending' | |
| approved_by | INT | FK → users(id) NULL | |
| approved_at | TIMESTAMPTZ | | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

### `purchase_return_items`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| return_id | INT | FK → purchase_returns(id) ON DELETE CASCADE | |
| item_id | INT | FK → items(id) | |
| quantity | NUMERIC(15,3) | NOT NULL CHECK (quantity > 0) | |
| unit_price | NUMERIC(15,2) | NOT NULL | |
| total_price | NUMERIC(15,2) | NOT NULL | |

---

## Schema: Sales

### `sale_invoices`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| customer_id | INT | FK → customers(id) NOT NULL | |
| invoice_no | VARCHAR(50) | UNIQUE NOT NULL | Auto-generated: INV-2026-00001 |
| invoice_date | DATE | NOT NULL DEFAULT CURRENT_DATE | |
| due_date | DATE | | Payment due date |
| payment_type | payment_type | NOT NULL | |
| subtotal | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| discount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| tax | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| total_amount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| paid_amount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| due_amount | NUMERIC(15,2) | GENERATED ALWAYS AS (total_amount - paid_amount) STORED | |
| status | sale_status | NOT NULL DEFAULT 'draft' | |
| notes | TEXT | | |
| confirmed_at | TIMESTAMPTZ | | |
| confirmed_by | INT | FK → users(id) | |
| created_by | INT | FK → users(id) NOT NULL | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_sales_customer`, `idx_sales_invoice_no`, `idx_sales_date`, `idx_sales_status`, `idx_sales_due_date`

### `sale_items`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| invoice_id | INT | FK → sale_invoices(id) ON DELETE CASCADE | |
| item_id | INT | FK → items(id) | |
| unit_id | INT | FK → units(id) | |
| quantity | NUMERIC(15,3) | NOT NULL CHECK (quantity > 0) | |
| unit_price | NUMERIC(15,2) | NOT NULL | Sale price at time of invoice |
| discount | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| total_price | NUMERIC(15,2) | NOT NULL | |

### `sale_payments`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| invoice_id | INT | FK → sale_invoices(id) NOT NULL | |
| amount | NUMERIC(15,2) | NOT NULL CHECK (amount > 0) | |
| payment_mode | payment_mode | NOT NULL | |
| account_id | INT | FK → accounts(id) | |
| reference_no | VARCHAR(100) | | |
| received_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| created_by | INT | FK → users(id) | |

### `sale_returns` & `sale_return_items`
*(Same structure as purchase_returns/purchase_return_items but FK to sale_invoices)*

### `notifications`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| customer_id | INT | FK → customers(id) NULL | |
| invoice_id | INT | FK → sale_invoices(id) NULL | |
| item_id | INT | FK → items(id) NULL | For low-stock alerts |
| type | notification_type | NOT NULL | |
| message | TEXT | NOT NULL | |
| is_read | BOOLEAN | NOT NULL DEFAULT FALSE | |
| sent_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

---

## Schema: Staff

### `staff`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| name | VARCHAR(200) | NOT NULL | |
| phone | VARCHAR(20) | | |
| cnic | VARCHAR(20) | UNIQUE | National ID |
| address | TEXT | | |
| join_date | DATE | NOT NULL | |
| staff_type | staff_type | NOT NULL | permanent / temporary |
| designation | VARCHAR(100) | | Job title |
| department | VARCHAR(100) | | |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

### `salary_structures`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| staff_id | INT | FK → staff(id) NOT NULL | |
| basic_salary | NUMERIC(15,2) | NOT NULL | |
| allowances | JSONB | NOT NULL DEFAULT '{}' | `{"transport": 2000, "meal": 1000}` |
| deductions | JSONB | NOT NULL DEFAULT '{}' | `{"tax": 500, "insurance": 200}` |
| effective_from | DATE | NOT NULL | |
| effective_to | DATE | | NULL = currently active |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Constraint:** Only one active structure per staff (`WHERE effective_to IS NULL`)

### `attendance`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| staff_id | INT | FK → staff(id) NOT NULL | |
| date | DATE | NOT NULL | |
| status | attendance_status | NOT NULL | |
| notes | TEXT | | |
| created_by | INT | FK → users(id) | |

**Unique:** `(staff_id, date)`

### `staff_payments`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| staff_id | INT | FK → staff(id) NOT NULL | |
| payment_month | SMALLINT | NOT NULL CHECK (1-12) | |
| payment_year | SMALLINT | NOT NULL | |
| gross_salary | NUMERIC(15,2) | NOT NULL | |
| total_allowances | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| total_deductions | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| advance_deduction | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| net_salary | NUMERIC(15,2) | NOT NULL | |
| payment_mode | payment_mode | NOT NULL | |
| account_id | INT | FK → accounts(id) | |
| paid_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| notes | TEXT | | |
| created_by | INT | FK → users(id) | |

**Unique:** `(staff_id, payment_month, payment_year)` — one payment per month

### `advances`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| staff_id | INT | FK → staff(id) NOT NULL | |
| amount | NUMERIC(15,2) | NOT NULL CHECK (amount > 0) | |
| deduct_from_month | SMALLINT | NOT NULL | |
| deduct_from_year | SMALLINT | NOT NULL | |
| reason | TEXT | | |
| is_deducted | BOOLEAN | NOT NULL DEFAULT FALSE | |
| paid_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| created_by | INT | FK → users(id) | |

---

## Schema: Transactions

### `accounts`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| name | VARCHAR(150) | NOT NULL | e.g., "Main Cash", "HBL Account" |
| account_type | account_type | NOT NULL | cash / bank / digital |
| account_no | VARCHAR(100) | | Bank account number |
| bank_name | VARCHAR(150) | | For bank accounts |
| opening_balance | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| current_balance | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Running balance |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

### `transactions`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| account_id | INT | FK → accounts(id) NOT NULL | |
| transaction_type | transaction_type | NOT NULL | debit / credit |
| reference_type | reference_type | NOT NULL | What caused this transaction |
| reference_id | INT | | PK of source record |
| amount | NUMERIC(15,2) | NOT NULL CHECK (amount > 0) | |
| balance_after | NUMERIC(15,2) | NOT NULL | Running balance after this tx |
| description | TEXT | NOT NULL | Human-readable description |
| transaction_date | DATE | NOT NULL DEFAULT CURRENT_DATE | |
| created_by | INT | FK → users(id) NOT NULL | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_transactions_account`, `idx_transactions_date`, `idx_transactions_reference`

### `transfers`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| from_account_id | INT | FK → accounts(id) NOT NULL | |
| to_account_id | INT | FK → accounts(id) NOT NULL | |
| amount | NUMERIC(15,2) | NOT NULL CHECK (amount > 0) | |
| reference_no | VARCHAR(100) | | |
| note | TEXT | | |
| transferred_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| created_by | INT | FK → users(id) | |

**Constraint:** `CHECK (from_account_id != to_account_id)`

---

## Schema: Production

### `production_orders`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| order_no | VARCHAR(50) | UNIQUE NOT NULL | PRD-2026-00001 |
| product_item_id | INT | FK → items(id) NOT NULL | What is being produced |
| quantity_to_produce | NUMERIC(15,3) | NOT NULL CHECK (> 0) | |
| start_date | DATE | | |
| end_date | DATE | | |
| status | production_status | NOT NULL DEFAULT 'planned' | |
| total_material_cost | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| total_labor_cost | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| total_other_cost | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |
| total_cost | NUMERIC(15,2) | GENERATED ALWAYS AS (total_material_cost + total_labor_cost + total_other_cost) STORED | |
| notes | TEXT | | |
| created_by | INT | FK → users(id) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

### `production_raw_materials`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| order_id | INT | FK → production_orders(id) ON DELETE CASCADE | |
| item_id | INT | FK → items(id) NOT NULL | Raw material item |
| unit_id | INT | FK → units(id) | |
| required_quantity | NUMERIC(15,3) | NOT NULL | Planned |
| used_quantity | NUMERIC(15,3) | NOT NULL DEFAULT 0 | Actual (set on complete) |
| unit_cost | NUMERIC(15,2) | NOT NULL DEFAULT 0 | Cost at time of production |
| total_cost | NUMERIC(15,2) | NOT NULL DEFAULT 0 | |

### `production_labor`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| order_id | INT | FK → production_orders(id) ON DELETE CASCADE | |
| staff_id | INT | FK → staff(id) NULL | Optional (external labor) |
| description | VARCHAR(200) | NOT NULL | Role/task description |
| hours | NUMERIC(8,2) | NOT NULL CHECK (> 0) | |
| rate_per_hour | NUMERIC(15,2) | NOT NULL | |
| total_cost | NUMERIC(15,2) | GENERATED ALWAYS AS (hours * rate_per_hour) STORED | |

### `production_costs`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| order_id | INT | FK → production_orders(id) ON DELETE CASCADE | |
| cost_type | VARCHAR(100) | NOT NULL | e.g., 'Electricity', 'Packaging' |
| amount | NUMERIC(15,2) | NOT NULL CHECK (> 0) | |
| note | TEXT | | |

### `production_output`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PK | |
| order_id | INT | FK → production_orders(id) NOT NULL | |
| item_id | INT | FK → items(id) NOT NULL | Finished good item |
| quantity_produced | NUMERIC(15,3) | NOT NULL | |
| produced_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

---

## Schema: Audit

### `audit_logs`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | BIGSERIAL | PK | |
| user_id | INT | FK → users(id) NULL | NULL for system actions |
| action | audit_action | NOT NULL | CREATE / UPDATE / DELETE |
| table_name | VARCHAR(100) | NOT NULL | Which table was changed |
| record_id | INT | NOT NULL | PK of the changed record |
| old_values | JSONB | | Before state (NULL for CREATE) |
| new_values | JSONB | | After state (NULL for DELETE) |
| request_id | VARCHAR(36) | | For correlating request logs |
| ip_address | INET | | Client IP |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | |

**Indexes:** `idx_audit_table_record`, `idx_audit_user`, `idx_audit_created_at`
**Note:** Partitioned by month (RANGE on created_at) for performance at scale.

---

## Materialized Views (for Reports)

### `mv_customer_balances`
Precomputed summary: customer_id, name, total_invoiced, total_paid, balance, last_transaction_at
Refresh: nightly at 02:00

### `mv_supplier_balances`
Similar to customer balances for suppliers.
Refresh: nightly at 02:00

### `mv_profit_loss`
Monthly P&L: month, year, total_sales, total_purchases, gross_profit, total_expenses, net_profit
Refresh: nightly at 02:00

### `mv_stock_valuation`
item_id, name, current_stock, purchase_price, total_value
Refresh: after every stock movement (via trigger or nightly)

---

## Key Relationships Diagram

```
users ──────────────────────────────────────────── (created_by on all tables)
  │
  ├── roles_permissions (role → module permissions)
  │
accounts ──┬── transactions (account_id)
           └── transfers (from/to account_id)
                │
suppliers ──┬── purchases ──┬── purchase_items ──── items ──── units
            │               ├── purchase_payments          │
            └── supplier_payments                     categories
                            └── purchase_returns
                                └── purchase_return_items

customers ──┬── sale_invoices ──┬── sale_items ──── items
            │                   ├── sale_payments
            └── customer_payments└── sale_returns
                                     └── notifications

staff ──┬── salary_structures
        ├── attendance
        ├── staff_payments ── accounts
        └── advances

production_orders ──┬── production_raw_materials ── items
                    ├── production_labor ── staff
                    ├── production_costs
                    └── production_output ── items

items ──── stock_movements (all inventory changes logged here)
```
