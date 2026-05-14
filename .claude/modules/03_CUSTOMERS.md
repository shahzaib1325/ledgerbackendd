# Module 03 — Customers

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Customers |
| Prefix | `/api/v1/customers` |
| Files | `models/customer.py`, `schemas/customer.py`, `api/v1/endpoints/customers.py`, `services/customer_service.py`, `repositories/customer_repo.py` |
| Dependencies | Transactions module (payment recording), Sales module (credit limit enforcement) |

Customers are entities that purchase goods or services from the business on cash or credit. This module tracks their contact information, credit limits, receivable balances, and complete transaction history.

---

## 2. Functional Requirements

- **FR-CUS-01**: Create, update, view, and soft-delete customer records.
- **FR-CUS-02**: Track a credit limit — the maximum outstanding amount a customer can owe.
- **FR-CUS-03**: Maintain a running receivable balance updated on every sale and payment.
- **FR-CUS-04**: Block sales on credit if they would exceed the customer's credit limit.
- **FR-CUS-05**: Record standalone payments received from customers.
- **FR-CUS-06**: Provide a full chronological ledger per customer.
- **FR-CUS-07**: Provide an aging report showing how long balances have been outstanding.
- **FR-CUS-08**: Notify users when a customer's balance exceeds 80% of their credit limit.

---

## 3. Data Models

### `Customer`
```python
class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: int
    name: str (max 200)
    phone: str | None
    email: str | None
    address: str | None
    credit_limit: Decimal (default 0.00)    # 0 = no credit allowed
    opening_balance: Decimal (default 0.00)
    balance: Decimal (default 0.00)         # running receivable
    balance_type: BalanceType               # receivable | payable
    notes: str | None
    is_active: bool (default True)
    created_by: int (FK → users)
```

### `CustomerPayment`
```python
class CustomerPayment(Base):
    __tablename__ = "customer_payments"

    id: int
    customer_id: int (FK → customers)
    amount: Decimal (> 0)
    payment_mode: PaymentMode
    account_id: int | None (FK → accounts)
    reference_no: str | None
    note: str | None
    received_at: datetime
    created_by: int (FK → users)
    created_at: datetime
```

---

## 4. Pydantic Schemas

```python
class CustomerCreate(BaseModel):
    name: str
    phone: str | None
    email: EmailStr | None
    address: str | None
    credit_limit: Decimal (default 0, >= 0)
    opening_balance: Decimal (default 0, >= 0)
    balance_type: BalanceType (default 'receivable')
    notes: str | None

class CustomerUpdate(BaseModel):
    name: str | None
    phone: str | None
    email: EmailStr | None
    address: str | None
    credit_limit: Decimal | None (>= 0)
    notes: str | None

class CustomerOut(BaseModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    address: str | None
    credit_limit: Decimal
    opening_balance: Decimal
    balance: Decimal
    balance_type: BalanceType
    available_credit: Decimal              # = credit_limit - balance (if receivable)
    credit_utilization_pct: float          # = balance / credit_limit * 100
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

class CustomerPaymentCreate(BaseModel):
    amount: Decimal (> 0)
    payment_mode: PaymentMode
    account_id: int | None
    reference_no: str | None
    note: str | None
    received_at: datetime | None

class AgingEntry(BaseModel):
    customer_id: int
    customer_name: str
    current: Decimal          # balance from invoices not yet due
    days_1_30: Decimal        # 1-30 days overdue
    days_31_60: Decimal       # 31-60 days overdue
    days_61_90: Decimal       # 61-90 days overdue
    days_over_90: Decimal     # 90+ days overdue
    total_balance: Decimal
```

---

## 5. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/customers` | read | List customers (paginated + filters) |
| POST | `/customers` | write | Create customer |
| GET | `/customers/{id}` | read | Customer detail with balance |
| PUT | `/customers/{id}` | write | Update customer |
| DELETE | `/customers/{id}` | delete | Soft delete |
| GET | `/customers/{id}/ledger` | read | Full ledger |
| GET | `/customers/{id}/transactions` | read | Transaction history |
| POST | `/customers/{id}/payments` | write | Record payment received |
| GET | `/customers/{id}/payments` | read | Payment history |
| GET | `/customers/balances/summary` | read | All customer balances |
| GET | `/customers/aging` | read | Aging report (all customers) |

### Query Parameters (GET /customers)
| Param | Type | Description |
|-------|------|-------------|
| `search` | string | Name search |
| `balance_type` | receivable\|payable | |
| `overdue_only` | bool | Only customers with overdue invoices |
| `credit_limit_exceeded` | bool | Balance > credit_limit |
| `page`, `limit` | int | Pagination |

### Query Parameters (GET /customers/aging)
| Param | Type | Description |
|-------|------|-------------|
| `as_of_date` | date | Aging calculated as of this date (default: today) |
| `page`, `limit` | int | |

---

## 6. Service Layer — `CustomerService`

```python
class CustomerService:

    async def create(db, customer_in, actor_id) -> Customer:
        """
        1. Create customer with opening_balance as initial balance
        2. Write audit log
        """

    async def update(db, customer_id, customer_in, actor_id) -> Customer:
        """
        1. Validate credit_limit >= current balance if being reduced
           → raise ValidationException if not
        2. Apply updates
        3. Write audit log
        """

    async def soft_delete(db, customer_id, actor_id) -> None:
        """
        1. Check balance == 0 (no outstanding receivables)
           → raise ConflictException if balance > 0
        2. Set is_active = False
        """

    async def check_credit_limit(db, customer_id, new_sale_amount) -> None:
        """
        Called by SaleService before confirming a credit/partial sale.
        Raises CreditLimitExceededError if:
            customer.balance + new_sale_amount > customer.credit_limit
        (Only applies when credit_limit > 0)
        """

    async def add_payment(db, customer_id, payment_in, actor_id) -> CustomerPayment:
        """
        1. SELECT FOR UPDATE on customer
        2. Create CustomerPayment record
        3. Reduce customer.balance by payment amount
        4. If balance < 0: flip balance_type to 'payable'
        5. Call TransactionService.record() to credit the account
        6. Audit log
        """

    async def update_balance(db, customer_id, amount, operation) -> None:
        """
        Internal: called by SaleService on confirm/return.
        Uses SELECT FOR UPDATE.
        After update: check if balance > 80% of credit_limit
        → if so, enqueue background task to create notification
        """

    async def get_aging(db, as_of_date, page, limit) -> list[AgingEntry]:
        """
        Groups overdue invoice amounts by age bucket per customer.
        Uses: MAX(0, due_amount) grouped by CASE WHEN ...
        """
```

---

## 7. Business Rules

| Rule | Detail |
|------|--------|
| Credit limit = 0 | Means unlimited credit allowed (no check performed) |
| Credit check | Only performed for `credit` and `partial` payment type sales |
| Credit limit reduction | Cannot set `credit_limit` lower than current `balance` |
| Deletion | Cannot soft-delete if outstanding balance > 0 |
| 80% alert | When balance exceeds 80% of credit_limit, a notification is queued |
| Opening balance | Set once on creation; immutable afterward |

---

## 8. Aging Calculation Logic

The aging report is calculated as of `as_of_date` (default: today):

```sql
SELECT
    c.id, c.name,
    SUM(CASE WHEN si.due_date >= :as_of_date THEN si.due_amount ELSE 0 END) AS current,
    SUM(CASE WHEN si.due_date BETWEEN :as_of_date - 30 AND :as_of_date - 1
             THEN si.due_amount ELSE 0 END) AS days_1_30,
    SUM(CASE WHEN si.due_date BETWEEN :as_of_date - 60 AND :as_of_date - 31
             THEN si.due_amount ELSE 0 END) AS days_31_60,
    SUM(CASE WHEN si.due_date BETWEEN :as_of_date - 90 AND :as_of_date - 61
             THEN si.due_amount ELSE 0 END) AS days_61_90,
    SUM(CASE WHEN si.due_date < :as_of_date - 90
             THEN si.due_amount ELSE 0 END) AS days_over_90
FROM customers c
JOIN sale_invoices si ON si.customer_id = c.id
WHERE si.status IN ('confirmed', 'partially_paid')
  AND si.due_amount > 0
GROUP BY c.id, c.name
```

---

## 9. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Customer not found | `NotFoundException` | 404 |
| Credit limit exceeded (on sale) | `CreditLimitExceededError` | 409 |
| Credit limit < current balance (on update) | `ValidationException` | 422 |
| Delete with outstanding balance | `ConflictException` | 409 |

---

## 10. Inter-Module Interactions

| Interaction | Direction | Description |
|-------------|-----------|-------------|
| `SaleService` → `CustomerService.check_credit_limit()` | Inbound | Before confirming credit sale |
| `SaleService` → `CustomerService.update_balance()` | Inbound | After sale confirm / return |
| `CustomerService.add_payment()` → `TransactionService.record()` | Outbound | Credit account with payment received |
| Background task → `CustomerService` | Inbound | Generates overdue notifications daily |
