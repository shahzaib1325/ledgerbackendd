# Module 06 — Sales

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Sales |
| Prefix | `/api/v1/sales` |
| Files | `models/sale.py`, `schemas/sale.py`, `api/v1/endpoints/sales.py`, `services/sale_service.py`, `repositories/sale_repo.py` |
| Dependencies | Customers (credit limit, balance), Inventory (stock), Transactions (account) |

Sales manages all outgoing goods and services to customers. It generates auto-numbered invoices, enforces credit limits, handles cash/credit/partial payments, supports notifications for overdue invoices, and manages sales returns.

---

## 2. Functional Requirements

- **FR-SAL-01**: Create sales invoices in draft with multiple line items.
- **FR-SAL-02**: Auto-generate sequential, year-scoped invoice numbers (INV-2026-00001).
- **FR-SAL-03**: On confirmation, deduct stock and update customer balance atomically.
- **FR-SAL-04**: Enforce credit limit check before confirming credit/partial sales.
- **FR-SAL-05**: Accept partial and full payment receipts against confirmed invoices.
- **FR-SAL-06**: Automatically update invoice status based on payment progress.
- **FR-SAL-07**: Trigger notifications for overdue invoices via background task.
- **FR-SAL-08**: Support sales returns with stock restoration and balance adjustment.
- **FR-SAL-09**: Show notification history and allow marking notifications as read.

---

## 3. Status Flow

```
DRAFT ──► CONFIRMED ──► PARTIALLY_PAID ──► PAID
                │
                └──► RETURNED
                └──► VOID
```

| Status | Description | Trigger |
|--------|-------------|---------|
| `draft` | Not yet processed | Initial creation |
| `confirmed` | Stock deducted, customer balance updated | Manual confirm action |
| `partially_paid` | Some but not all payments received | Payment recorded (partial) |
| `paid` | Fully paid | Payment recorded (full) |
| `returned` | Fully returned | Return approved |
| `void` | Cancelled draft | Void action |

---

## 4. Data Models

### `SaleInvoice`
```python
class SaleInvoice(Base, TimestampMixin):
    __tablename__ = "sale_invoices"

    id: int
    customer_id: int (FK → customers)
    invoice_no: str (UNIQUE)             # auto-generated: INV-2026-00001
    invoice_date: date
    due_date: date | None                # for credit sales
    payment_type: PaymentType            # cash | credit | partial
    subtotal: Decimal
    discount: Decimal (default 0)
    tax: Decimal (default 0)
    total_amount: Decimal
    paid_amount: Decimal (default 0)
    due_amount: Decimal (GENERATED)
    status: SaleStatus
    notes: str | None
    confirmed_at: datetime | None
    confirmed_by: int | None (FK → users)
    created_by: int (FK → users)
```

### `SaleItem`
```python
class SaleItem(Base):
    __tablename__ = "sale_items"

    id: int
    invoice_id: int (FK → sale_invoices, CASCADE)
    item_id: int (FK → items)
    unit_id: int (FK → units)
    quantity: Decimal (> 0)
    unit_price: Decimal (snapshot of price at time of sale)
    discount: Decimal (default 0)
    total_price: Decimal
```

### `SalePayment`
```python
class SalePayment(Base):
    __tablename__ = "sale_payments"

    id: int
    invoice_id: int (FK → sale_invoices)
    amount: Decimal (> 0)
    payment_mode: PaymentMode
    account_id: int | None (FK → accounts)
    reference_no: str | None
    received_at: datetime
    created_by: int (FK → users)
```

### `SaleReturn` + `SaleReturnItem`
*(Same structure as PurchaseReturn/PurchaseReturnItem but references sale_invoices)*

### `Notification`
```python
class Notification(Base):
    __tablename__ = "notifications"

    id: int
    customer_id: int | None (FK → customers)
    invoice_id: int | None (FK → sale_invoices)
    item_id: int | None (FK → items)        # for low-stock alerts
    type: NotificationType                   # due | overdue | credit_limit | low_stock
    message: str
    is_read: bool (default False)
    sent_at: datetime
```

---

## 5. Pydantic Schemas

```python
class SaleItemCreate(BaseModel):
    item_id: int
    unit_id: int
    quantity: Decimal (> 0)
    unit_price: Decimal (>= 0)
    discount: Decimal (default 0)

class SaleCreate(BaseModel):
    customer_id: int
    invoice_date: date (default today)
    due_date: date | None              # required if payment_type is 'credit'
    payment_type: PaymentType
    discount: Decimal (default 0)
    tax: Decimal (default 0)
    items: list[SaleItemCreate] (min 1)
    paid_amount: Decimal (default 0)   # for 'partial' type
    notes: str | None

    @validator
    def due_date_required_for_credit(cls, v, values):
        if values.get('payment_type') == 'credit' and not v:
            raise ValueError('due_date is required for credit sales')

class SaleUpdate(BaseModel):
    invoice_date: date | None
    due_date: date | None
    payment_type: PaymentType | None
    discount: Decimal | None
    tax: Decimal | None
    items: list[SaleItemCreate] | None
    notes: str | None

class SaleOut(BaseModel):
    id: int
    customer: CustomerListOut
    invoice_no: str
    invoice_date: date
    due_date: date | None
    payment_type: PaymentType
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    due_amount: Decimal
    status: SaleStatus
    items: list[SaleItemOut]
    payments: list[SalePaymentOut]
    is_overdue: bool                   # = due_date < today and due_amount > 0
    days_overdue: int | None
    notes: str | None
    confirmed_at: datetime | None
    created_at: datetime

class SalePaymentCreate(BaseModel):
    amount: Decimal (> 0)
    payment_mode: PaymentMode
    account_id: int | None
    reference_no: str | None
    received_at: datetime | None

class NotificationOut(BaseModel):
    id: int
    type: NotificationType
    message: str
    customer_id: int | None
    invoice_id: int | None
    item_id: int | None
    is_read: bool
    sent_at: datetime
```

---

## 6. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/sales` | read | List invoices (paginated + filters) |
| POST | `/sales` | write | Create draft invoice |
| GET | `/sales/{id}` | read | Invoice detail |
| PUT | `/sales/{id}` | write | Edit draft invoice |
| DELETE | `/sales/{id}` | write | Void draft |
| POST | `/sales/{id}/confirm` | write | Confirm → stock out + customer balance |
| POST | `/sales/{id}/payments` | write | Record payment |
| GET | `/sales/{id}/payments` | read | Payment history |
| POST | `/sales/{id}/returns` | write | Create return |
| GET | `/sales/{id}/returns` | read | Returns |
| PUT | `/sales/returns/{return_id}/approve` | manager+ | Approve return |
| PUT | `/sales/returns/{return_id}/reject` | manager+ | Reject return |
| GET | `/sales/notifications` | read | Notification feed |
| PUT | `/sales/notifications/{id}/read` | write | Mark as read |
| PUT | `/sales/notifications/read-all` | write | Mark all as read |

### Query Parameters (GET /sales)
| Param | Type | Description |
|-------|------|-------------|
| `customer_id` | int | Filter by customer |
| `status` | enum | Filter by status |
| `payment_type` | enum | |
| `overdue` | bool | Only overdue invoices |
| `from_date`, `to_date` | date | Invoice date range |
| `search` | string | Invoice number search |
| `page`, `limit` | int | |

---

## 7. Invoice Number Generation

Invoice numbers are sequential per year and never recycled:

```python
# app/utils/invoice_number.py
async def generate_invoice_no(db, year: int) -> str:
    """
    Uses a PostgreSQL advisory lock + sequence to guarantee uniqueness
    even under concurrent requests.
    """
    result = await db.execute(
        text("SELECT nextval('sale_invoice_seq_:year')", year=year)
    )
    seq = result.scalar()
    return f"INV-{year}-{seq:05d}"   # INV-2026-00001
```

A new sequence is created at the start of each year (via migration or `CREATE SEQUENCE IF NOT EXISTS`).

---

## 8. Confirm Sale — Detailed Workflow

```python
async def confirm(db, invoice_id, actor_id, notes=None):
    async with db.begin():

        # Step 1: Fetch invoice
        invoice = await sale_repo.get_or_404(db, invoice_id)
        if invoice.status != SaleStatus.DRAFT:
            raise InvalidStatusTransitionError()

        # Step 2: Credit limit check (for credit/partial sales)
        if invoice.payment_type in (PaymentType.CREDIT, PaymentType.PARTIAL):
            await customer_service.check_credit_limit(
                db, invoice.customer_id,
                new_amount=invoice.total_amount - invoice.paid_amount
            )

        # Step 3: Stock deduction for each item
        for item_line in invoice.items:
            await inventory_service.deduct_stock(
                db, item_line.item_id, item_line.quantity,
                movement_type=MovementType.SALE_OUT,
                reference_type='sale', reference_id=invoice.id,
                actor_id=actor_id
            )

        # Step 4: Update customer balance
        credit_amount = invoice.total_amount - invoice.paid_amount
        await customer_service.update_balance(db, invoice.customer_id, credit_amount, 'add')

        # Step 5: Handle initial payment
        if invoice.payment_type == PaymentType.CASH:
            invoice.paid_amount = invoice.total_amount
            await transaction_service.record(db, transaction_type=CREDIT,
                reference_type='sale', reference_id=invoice.id,
                amount=invoice.total_amount, ...)
        elif invoice.payment_type == PaymentType.PARTIAL and invoice.paid_amount > 0:
            await transaction_service.record(db, ..., amount=invoice.paid_amount, ...)

        # Step 6: Update status
        invoice.status = SaleStatus.CONFIRMED
        invoice.confirmed_at = datetime.utcnow()
        invoice.confirmed_by = actor_id

        # Step 7: Schedule due-date notification if due_date set
        if invoice.due_date:
            await arq_pool.enqueue_job(
                'schedule_invoice_due_reminder',
                invoice_id=invoice.id,
                due_date=str(invoice.due_date)
            )
```

---

## 9. Payment Recording — Status Auto-Update

```python
async def add_payment(db, invoice_id, payment_in, actor_id):
    async with db.begin():
        invoice = await sale_repo.get_or_404(db, invoice_id)

        if invoice.status not in (SaleStatus.CONFIRMED, SaleStatus.PARTIALLY_PAID):
            raise InvalidStatusTransitionError()

        if payment_in.amount > invoice.due_amount:
            raise ValidationException("Payment exceeds remaining due amount")

        # Record payment
        payment = SalePayment(**payment_in.dict(), invoice_id=invoice_id, created_by=actor_id)
        db.add(payment)
        invoice.paid_amount += payment_in.amount

        # Update customer balance
        await customer_service.update_balance(db, invoice.customer_id, payment_in.amount, 'subtract')

        # Credit the account
        await transaction_service.record(db, transaction_type=CREDIT, amount=payment_in.amount, ...)

        # Auto-update status
        if invoice.due_amount <= 0:
            invoice.status = SaleStatus.PAID
        else:
            invoice.status = SaleStatus.PARTIALLY_PAID
```

---

## 10. Return Approval Workflow

```python
async def approve_return(db, return_id, actor_id):
    async with db.begin():
        ret = await sale_repo.get_return_or_404(db, return_id)
        invoice = ret.invoice

        # Restore stock
        for ret_item in ret.items:
            await inventory_service.add_stock(
                db, ret_item.item_id, ret_item.quantity,
                movement_type=MovementType.RETURN_IN,
                reference_type='sale_return', reference_id=ret.id, ...
            )

        # Reduce customer balance (credit note)
        await customer_service.update_balance(db, invoice.customer_id, ret.total_amount, 'subtract')

        # Update invoice status if applicable
        invoice.paid_amount -= ret.total_amount  # or reduce what they owe
        ret.status = ReturnStatus.APPROVED
```

---

## 11. Business Rules

| Rule | Detail |
|------|--------|
| Invoice number | Sequential per year; never reused even if invoice is voided |
| Draft only editable | `confirmed`, `paid`, `returned`, `void` are immutable |
| Credit check | Only for `credit` and `partial` payment types; `cash` bypasses |
| `due_date` | Required when `payment_type = credit`; optional for partial |
| Overdue | `is_overdue = due_date < today AND due_amount > 0` |
| Return quantity | Cannot exceed original sold quantity |
| Payment overflow | `payment_amount > due_amount` is rejected |
| Status progression | `partially_paid → paid` auto-triggered by payment recording |

---

## 12. Notification Rules

| Event | Notification Type | When |
|-------|------------------|------|
| Invoice due in ≤ 3 days | `due` | Daily background job |
| Invoice past due_date | `overdue` | Daily background job |
| Customer balance > 80% of credit_limit | `credit_limit` | On every payment update |
| Stock below reorder level | `low_stock` | Daily background job |

---

## 13. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Invoice not found | `NotFoundException` | 404 |
| Confirm non-draft | `InvalidStatusTransitionError` | 409 |
| Credit limit exceeded | `CreditLimitExceededError` | 409 |
| Insufficient stock | `InsufficientStockError` | 409 |
| Payment > due amount | `ValidationException` | 422 |
| Return qty > sale qty | `ValidationException` | 422 |
| Missing due_date for credit | `ValidationException` | 422 |
