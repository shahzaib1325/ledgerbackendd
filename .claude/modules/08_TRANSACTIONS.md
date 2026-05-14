# Module 08 — Transactions & Accounts

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Transactions & Accounts |
| Prefix | `/api/v1/accounts`, `/api/v1/transactions` |
| Files | `models/transaction.py`, `schemas/transaction.py`, `api/v1/endpoints/transactions.py`, `services/transaction_service.py`, `repositories/transaction_repo.py` |
| Dependencies | Called by ALL other modules for financial recording |

This module is the **central financial ledger** of the entire system. Every money movement — purchase payment, sale receipt, salary disbursement, transfer, expense — flows through here. It maintains accounts (cash, bank, digital wallets) with running balances, and provides the data that powers Cash Book, Bank Book, and General Ledger reports.

---

## 2. Functional Requirements

- **FR-TXN-01**: Manage multiple accounts by type (cash, bank, digital).
- **FR-TXN-02**: Record every financial event as a debit or credit transaction on the relevant account.
- **FR-TXN-03**: Maintain a running balance on each account (updated on every transaction).
- **FR-TXN-04**: Support inter-account transfers (e.g., cash → bank) as atomic operations.
- **FR-TXN-05**: Allow manual expense recording against any account.
- **FR-TXN-06**: Provide a full transaction history per account (Cash Book / Bank Book).
- **FR-TXN-07**: Provide a consolidated General Ledger view across all accounts.
- **FR-TXN-08**: Never allow manual editing or deletion of transaction records — they are immutable.

---

## 3. Data Models

### `Account`
```python
class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: int
    name: str (max 150)                  # "Main Cash", "HBL Current Account"
    account_type: AccountType            # cash | bank | digital
    account_no: str | None               # Bank account number (masked in API)
    bank_name: str | None
    opening_balance: Decimal (default 0)
    current_balance: Decimal (default 0) # Updated on every transaction
    is_active: bool (default True)
    created_by: int (FK → users)
```

### `Transaction`
```python
class Transaction(Base):
    __tablename__ = "transactions"

    id: int
    account_id: int (FK → accounts)
    transaction_type: TransactionType    # debit | credit
    reference_type: ReferenceType        # purchase | sale | salary | etc.
    reference_id: int | None             # PK of the source record
    amount: Decimal (> 0)
    balance_after: Decimal               # Running balance snapshot
    description: str                     # Human-readable (auto-generated)
    transaction_date: date
    created_by: int (FK → users)
    created_at: datetime
    # IMMUTABLE: no update, no delete allowed
```

### `Transfer`
```python
class Transfer(Base):
    __tablename__ = "transfers"

    id: int
    from_account_id: int (FK → accounts)
    to_account_id: int (FK → accounts)  # must differ from from_account_id
    amount: Decimal (> 0)
    reference_no: str | None
    note: str | None
    transferred_at: datetime
    created_by: int (FK → users)
```

---

## 4. Pydantic Schemas

```python
class AccountCreate(BaseModel):
    name: str
    account_type: AccountType
    account_no: str | None
    bank_name: str | None
    opening_balance: Decimal (default 0, >= 0)

class AccountUpdate(BaseModel):
    name: str | None
    account_no: str | None
    bank_name: str | None
    # opening_balance NOT updatable after creation

class AccountOut(BaseModel):
    id: int
    name: str
    account_type: AccountType
    account_no: str | None              # masked: "****1234"
    bank_name: str | None
    opening_balance: Decimal
    current_balance: Decimal
    is_active: bool
    created_at: datetime

class TransactionCreate(BaseModel):     # For manual expense recording only
    account_id: int
    amount: Decimal (> 0)
    description: str (required)
    transaction_date: date (default today)
    # transaction_type always DEBIT for manual expenses
    # reference_type = 'expense'

class TransactionOut(BaseModel):
    id: int
    account_id: int
    account_name: str
    transaction_type: TransactionType
    reference_type: ReferenceType
    reference_id: int | None
    amount: Decimal
    balance_after: Decimal
    description: str
    transaction_date: date
    created_at: datetime

class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: Decimal (> 0)
    reference_no: str | None
    note: str | None
    transferred_at: datetime | None     # defaults to now

class TransferOut(BaseModel):
    id: int
    from_account: AccountOut
    to_account: AccountOut
    amount: Decimal
    reference_no: str | None
    note: str | None
    transferred_at: datetime
```

---

## 5. API Endpoints

### Accounts
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/accounts` | read | List all accounts with balances |
| POST | `/accounts` | admin | Create account |
| GET | `/accounts/{id}` | read | Account detail |
| PUT | `/accounts/{id}` | admin | Update account name/details |
| DELETE | `/accounts/{id}` | admin | Soft delete (only if balance = 0) |
| GET | `/accounts/{id}/transactions` | read | Cash Book / Bank Book per account |
| GET | `/accounts/summary` | read | All accounts with total balances |

### Transactions
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/transactions` | read | All transactions with filters |
| POST | `/transactions` | write | Record manual expense |
| GET | `/transactions/{id}` | read | Transaction detail |
| GET | `/transactions/general-ledger` | read | General Ledger (all accounts) |

### Transfers
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/transactions/transfers` | write | Inter-account transfer |
| GET | `/transactions/transfers` | read | Transfer history |
| GET | `/transactions/transfers/{id}` | read | Transfer detail |

### Query Parameters (GET /accounts/{id}/transactions)
| Param | Type | Description |
|-------|------|-------------|
| `from_date`, `to_date` | date | Date range (Cash Book / Bank Book period) |
| `transaction_type` | debit\|credit | |
| `reference_type` | enum | Filter by source |
| `page`, `limit` | int | |

### Query Parameters (GET /transactions)
| Param | Type | Description |
|-------|------|-------------|
| `account_id` | int | Filter by account |
| `from_date`, `to_date` | date | |
| `reference_type` | enum | |
| `transaction_type` | debit\|credit | |
| `search` | string | Description search |
| `page`, `limit` | int | |

---

## 6. Service Layer — `TransactionService`

```python
class TransactionService:

    async def record(
        db,
        account_id: int,
        transaction_type: TransactionType,
        reference_type: ReferenceType,
        reference_id: int | None,
        amount: Decimal,
        description: str,
        transaction_date: date,
        actor_id: int
    ) -> Transaction:
        """
        INTERNAL METHOD — called by all other services.
        1. SELECT FOR UPDATE on account
        2. Calculate new balance:
           - CREDIT → balance += amount
           - DEBIT  → balance -= amount
        3. Create Transaction record with balance_after = new balance
        4. Update account.current_balance
        5. NOTE: No separate commit — runs in the caller's DB transaction
        """

    async def transfer(db, transfer_in: TransferCreate, actor_id) -> Transfer:
        """
        1. Validate from_account != to_account
        2. Validate from_account.current_balance >= transfer amount
        3. Create Transfer record
        4. DEBIT from_account: call record(db, from_account_id, DEBIT, 'transfer', ...)
        5. CREDIT to_account: call record(db, to_account_id, CREDIT, 'transfer', ...)
        All in one DB transaction — atomic.
        """

    async def record_expense(db, expense_in: TransactionCreate, actor_id) -> Transaction:
        """
        Manual expense entry.
        Always DEBIT the account.
        reference_type = 'expense', reference_id = None
        """
```

---

## 7. Transaction Description Auto-Generation

Each transaction is stored with a human-readable description so the Cash Book makes sense:

| Source | Description Template |
|--------|---------------------|
| Purchase payment | `"Payment to {supplier_name} for Purchase #{purchase_id}"` |
| Sale receipt | `"Payment from {customer_name} for Invoice {invoice_no}"` |
| Salary disbursement | `"Salary for {staff_name} — {month}/{year}"` |
| Transfer (debit) | `"Transfer to {to_account_name} — {reference_no or '-'}"` |
| Transfer (credit) | `"Transfer from {from_account_name} — {reference_no or '-'}"` |
| Manual expense | As entered by user |
| Advance payment | `"Advance to {staff_name}"` |

---

## 8. Running Balance Logic

`balance_after` is stored on every transaction row — this avoids expensive `SUM()` aggregations for every ledger view:

```
Transaction 1: CREDIT 100,000 → balance_after = 100,000
Transaction 2: DEBIT   20,000 → balance_after =  80,000
Transaction 3: CREDIT  50,000 → balance_after = 130,000
Transaction 4: DEBIT   15,000 → balance_after = 115,000
```

To reconstruct any point-in-time balance:
```sql
SELECT balance_after FROM transactions
WHERE account_id = :id AND transaction_date <= :as_of_date
ORDER BY id DESC LIMIT 1
```

---

## 9. Cash Book & Bank Book Query

The Cash Book / Bank Book is simply the transaction list for a specific account within a date range, with opening balance carried forward:

```python
async def get_cash_book(db, account_id, from_date, to_date, page, limit):
    # Opening balance = balance_after of last transaction BEFORE from_date
    opening = await get_balance_before(db, account_id, from_date)

    # Transactions in range
    transactions = await get_transactions_in_range(db, account_id, from_date, to_date, page, limit)

    return CashBookResponse(
        account=...,
        opening_balance=opening,
        transactions=transactions,
        closing_balance=transactions[-1].balance_after if transactions else opening
    )
```

---

## 10. Business Rules

| Rule | Detail |
|------|--------|
| Immutable transactions | No `UPDATE` or `DELETE` on `transactions` table ever |
| Error correction | To reverse a transaction, record an equal and opposite one with `reference_type='adjustment'` |
| Account deletion | Cannot delete account if it has any transactions |
| Account opening balance | Immutable after first transaction is recorded |
| Concurrent balance updates | All balance updates use `SELECT FOR UPDATE` on account row |
| Transfer same account | Rejected: `from_account_id != to_account_id` enforced |
| Negative balance | Allowed on bank accounts (overdraft); restricted on cash accounts via config |

---

## 11. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Account not found | `NotFoundException` | 404 |
| Transfer same account | `ValidationException` | 422 |
| Insufficient balance (cash account transfer) | `ValidationException` | 422 |
| Delete account with transactions | `ConflictException` | 409 |
| Amount = 0 | `ValidationException` | 422 |

---

## 12. Inter-Module Interactions

This is the module that ALL other financial modules depend on:

| Caller | Call | When |
|--------|------|------|
| `PurchaseService` | `record(DEBIT, 'purchase')` | On cash purchase confirm |
| `PurchaseService` | `record(DEBIT, 'purchase_payment')` | On payment added to credit purchase |
| `SaleService` | `record(CREDIT, 'sale')` | On cash sale confirm |
| `SaleService` | `record(CREDIT, 'sale_payment')` | On payment received |
| `SupplierService` | `record(DEBIT, 'purchase_payment')` | On standalone supplier payment |
| `CustomerService` | `record(CREDIT, 'sale_payment')` | On standalone customer payment |
| `StaffService` | `record(DEBIT, 'salary')` | On salary processing |
| `StaffService` | `record(DEBIT, 'advance')` | On advance payment |
