# Module 02 — Suppliers

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Suppliers |
| Prefix | `/api/v1/suppliers` |
| Files | `models/supplier.py`, `schemas/supplier.py`, `api/v1/endpoints/suppliers.py`, `services/supplier_service.py`, `repositories/supplier_repo.py` |
| Dependencies | Transactions module (payment recording), Reports module (ledger) |

Suppliers are the entities from whom the business purchases raw materials or goods. This module manages supplier master records, tracks payable balances, and records standalone payments separate from purchase invoices.

---

## 2. Functional Requirements

- **FR-SUP-01**: Create, update, view, and soft-delete supplier records.
- **FR-SUP-02**: Track opening balance (amount owed at the time of supplier creation).
- **FR-SUP-03**: Maintain a running balance that auto-updates on every purchase and payment.
- **FR-SUP-04**: Allow recording standalone payments to suppliers (outside of a specific purchase).
- **FR-SUP-05**: Provide a full chronological ledger for each supplier showing all debits and credits.
- **FR-SUP-06**: Show all supplier balances in a summary view.
- **FR-SUP-07**: Balance type (`payable` / `receivable`) auto-flips when balance changes sign.

---

## 3. Data Models

### `Supplier`
```python
class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id: int
    name: str (max 200, NOT NULL)
    phone: str | None (max 20)
    email: str | None (max 255)
    address: str | None
    opening_balance: Decimal (default 0.00)
    balance: Decimal (default 0.00)         # running total, updated on each transaction
    balance_type: BalanceType               # payable | receivable
    notes: str | None
    is_active: bool (default True)
    created_by: int (FK → users)
```

### `SupplierPayment`
```python
class SupplierPayment(Base):
    __tablename__ = "supplier_payments"

    id: int
    supplier_id: int (FK → suppliers)
    amount: Decimal (> 0)
    payment_mode: PaymentMode               # cash | bank | digital
    account_id: int | None (FK → accounts) # which account was debited
    reference_no: str | None
    note: str | None
    paid_at: datetime
    created_by: int (FK → users)
    created_at: datetime
```

---

## 4. Pydantic Schemas

```python
class SupplierCreate(BaseModel):
    name: str (min 1, max 200)
    phone: str | None
    email: EmailStr | None
    address: str | None
    opening_balance: Decimal (default 0, >= 0)
    balance_type: BalanceType (default 'payable')
    notes: str | None

class SupplierUpdate(BaseModel):
    name: str | None
    phone: str | None
    email: EmailStr | None
    address: str | None
    notes: str | None
    # balance, opening_balance NOT updatable here

class SupplierOut(BaseModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    address: str | None
    opening_balance: Decimal
    balance: Decimal
    balance_type: BalanceType
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

class SupplierListOut(BaseModel):         # lightweight list version
    id: int
    name: str
    phone: str | None
    balance: Decimal
    balance_type: BalanceType
    is_active: bool

class SupplierPaymentCreate(BaseModel):
    amount: Decimal (> 0)
    payment_mode: PaymentMode
    account_id: int | None
    reference_no: str | None
    note: str | None
    paid_at: datetime | None              # defaults to now

class SupplierPaymentOut(BaseModel):
    id: int
    supplier_id: int
    amount: Decimal
    payment_mode: PaymentMode
    reference_no: str | None
    note: str | None
    paid_at: datetime
    created_at: datetime

class SupplierLedgerEntry(BaseModel):     # one row in ledger report
    date: date
    description: str
    debit: Decimal                        # amount paid to supplier
    credit: Decimal                       # amount owed to supplier (purchase)
    balance: Decimal                      # running balance
    reference_type: str                   # 'purchase' | 'payment'
    reference_id: int
```

---

## 5. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/suppliers` | read | List all suppliers (paginated, searchable) |
| POST | `/suppliers` | write | Create a new supplier |
| GET | `/suppliers/{id}` | read | Get supplier detail |
| PUT | `/suppliers/{id}` | write | Update supplier |
| DELETE | `/suppliers/{id}` | delete | Soft delete |
| GET | `/suppliers/{id}/ledger` | read | Full transaction ledger |
| POST | `/suppliers/{id}/payments` | write | Record a standalone payment |
| GET | `/suppliers/{id}/payments` | read | Payment history |
| GET | `/suppliers/balances/summary` | read | All supplier balances (Party Balance Report) |

### Query Parameters (GET /suppliers)
| Param | Type | Description |
|-------|------|-------------|
| `search` | string | Filter by name (case-insensitive, partial) |
| `balance_type` | payable\|receivable | Filter by balance type |
| `is_active` | bool | Default true |
| `page` | int | Page number |
| `limit` | int | Items per page |
| `sort_by` | name\|balance\|created_at | Sort field |
| `sort_order` | asc\|desc | Sort direction |

### Query Parameters (GET /suppliers/{id}/ledger)
| Param | Type | Description |
|-------|------|-------------|
| `from_date` | date | Start of ledger period |
| `to_date` | date | End of ledger period |
| `page` | int | |
| `limit` | int | |

---

## 6. Service Layer — `SupplierService`

```python
class SupplierService:

    async def create(db, supplier_in: SupplierCreate, actor_id) -> Supplier:
        """
        1. Create supplier record
        2. Set balance = opening_balance
        3. Write audit log
        """

    async def update(db, supplier_id, supplier_in: SupplierUpdate, actor_id) -> Supplier:
        """
        1. Fetch supplier or raise 404
        2. Apply updates
        3. Write audit log
        """

    async def soft_delete(db, supplier_id, actor_id) -> None:
        """
        1. Check no unpaid purchase dues (balance > 0)
           → raise ConflictException if balance exists
        2. Set is_active = False
        3. Write audit log
        """

    async def add_payment(db, supplier_id, payment_in, actor_id) -> SupplierPayment:
        """
        1. Fetch supplier (lock row with SELECT FOR UPDATE)
        2. Create SupplierPayment record
        3. Deduct payment.amount from supplier.balance
        4. If supplier.balance < 0: flip balance_type to 'receivable'
        5. If account_id provided: call TransactionService.record() (debit account)
        6. Write audit log
        All in one DB transaction
        """

    async def update_balance(db, supplier_id, amount, operation) -> None:
        """
        Internal method called by PurchaseService.
        operation: 'add' (new purchase) | 'subtract' (return/payment)
        Uses SELECT FOR UPDATE to prevent race conditions.
        """

    async def get_ledger(db, supplier_id, from_date, to_date, page, limit) -> list[SupplierLedgerEntry]:
        """
        Queries purchases and payments for this supplier in date range.
        Calculates running balance using opening_balance as starting point.
        Returns chronological list with debit/credit/balance columns.
        """
```

---

## 7. Business Rules

| Rule | Detail |
|------|--------|
| Balance auto-update | Calling `add_payment` or `update_balance` always uses `SELECT FOR UPDATE` to prevent concurrent balance corruption |
| Balance sign flip | If `balance` goes negative (we overpaid), `balance_type` flips to `receivable` and balance stored as positive |
| Deletion restriction | Cannot soft-delete a supplier if `balance != 0` — must settle all dues first |
| Opening balance | Set once at creation; cannot be edited afterward (affects ledger integrity) |
| Historical integrity | Soft-deleted suppliers still appear in historical purchases and ledger |
| Payment account | When payment mode is `bank` or `digital`, `account_id` is required |

---

## 8. Ledger Query Logic

The supplier ledger is constructed by:

1. Start with `opening_balance` as the initial balance
2. Union two result sets:
   - All confirmed `purchases` for this supplier (credit entries — increases payable)
   - All `supplier_payments` for this supplier (debit entries — decreases payable)
3. Order by `date ASC`, then `created_at ASC` for same-day ordering
4. Calculate running balance using PostgreSQL window function:
   ```sql
   SUM(credit - debit) OVER (ORDER BY date, created_at) + opening_balance AS balance
   ```
5. Apply date filter and pagination

---

## 9. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Supplier not found | `NotFoundException` | 404 |
| Delete with balance | `ConflictException` | 409 |
| Payment > balance (warning only, not error) | — | 200 + warning field |
| Invalid account for bank payment | `ValidationException` | 422 |

---

## 10. Inter-Module Interactions

| Interaction | Direction | Description |
|-------------|-----------|-------------|
| `PurchaseService` → `SupplierService.update_balance()` | Inbound | On purchase confirm/return |
| `SupplierService.add_payment()` → `TransactionService.record()` | Outbound | Records debit in account ledger |
| `ReportService` → `SupplierRepository` | Inbound | Supplier ledger, balance reports |
