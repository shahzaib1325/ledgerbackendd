# Module 05 — Purchases

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Purchases |
| Prefix | `/api/v1/purchases` |
| Files | `models/purchase.py`, `schemas/purchase.py`, `api/v1/endpoints/purchases.py`, `services/purchase_service.py`, `repositories/purchase_repo.py` |
| Dependencies | Suppliers (balance), Inventory (stock), Transactions (account ledger) |

The Purchases module handles all incoming goods from suppliers. It supports cash, credit, and partial payment types. On confirmation, it automatically updates inventory stock and the supplier's payable balance. Returns are fully supported with stock reversal.

---

## 2. Functional Requirements

- **FR-PUR-01**: Create purchase orders in draft state with multiple line items.
- **FR-PUR-02**: Confirm a purchase to update stock and supplier balance atomically.
- **FR-PUR-03**: Support cash (immediate payment), credit (pay later), and partial (partial upfront) payment types.
- **FR-PUR-04**: Record additional payments against credit/partial purchases.
- **FR-PUR-05**: Initiate and approve purchase returns; reversal updates stock and supplier balance.
- **FR-PUR-06**: View complete purchase history with filters by supplier, date, status, payment type.
- **FR-PUR-07**: Only draft purchases can be edited or cancelled.

---

## 3. Status Flow

```
DRAFT ──► CONFIRMED ──► (RETURNED)
  │
  └──► VOID (cancelled before confirming)
```

| Status | Description | Editable? | Actions Available |
|--------|-------------|-----------|-------------------|
| `draft` | Created but not processed | Yes | Edit, Confirm, Void |
| `confirmed` | Stock and balance updated | No | Add Payment, Initiate Return |
| `returned` | Fully returned | No | — |
| `void` | Cancelled draft | No | — |

---

## 4. Data Models

### `Purchase`
```python
class Purchase(Base, TimestampMixin):
    __tablename__ = "purchases"

    id: int
    supplier_id: int (FK → suppliers)
    invoice_no: str | None               # supplier's own invoice number
    purchase_date: date
    payment_type: PaymentType            # cash | credit | partial
    subtotal: Decimal
    discount: Decimal (default 0)
    total_amount: Decimal
    paid_amount: Decimal (default 0)
    due_amount: Decimal (GENERATED: total_amount - paid_amount)
    status: PurchaseStatus
    notes: str | None
    confirmed_at: datetime | None
    confirmed_by: int | None (FK → users)
    created_by: int (FK → users)
```

### `PurchaseItem`
```python
class PurchaseItem(Base):
    __tablename__ = "purchase_items"

    id: int
    purchase_id: int (FK → purchases, CASCADE DELETE)
    item_id: int (FK → items)
    unit_id: int (FK → units)
    quantity: Decimal (> 0)
    unit_price: Decimal (>= 0)
    discount: Decimal (default 0)
    total_price: Decimal              # (quantity × unit_price) - discount
```

### `PurchasePayment`
```python
class PurchasePayment(Base):
    __tablename__ = "purchase_payments"

    id: int
    purchase_id: int (FK → purchases)
    amount: Decimal (> 0)
    payment_mode: PaymentMode
    account_id: int | None (FK → accounts)
    reference_no: str | None
    paid_at: datetime
    created_by: int (FK → users)
```

### `PurchaseReturn`
```python
class PurchaseReturn(Base):
    __tablename__ = "purchase_returns"

    id: int
    purchase_id: int (FK → purchases)
    return_date: date
    reason: str | None
    total_amount: Decimal
    status: ReturnStatus              # pending | approved | rejected
    approved_by: int | None (FK → users)
    approved_at: datetime | None
    created_by: int (FK → users)
    created_at: datetime
```

### `PurchaseReturnItem`
```python
class PurchaseReturnItem(Base):
    __tablename__ = "purchase_return_items"

    id: int
    return_id: int (FK → purchase_returns, CASCADE)
    item_id: int (FK → items)
    quantity: Decimal (> 0)
    unit_price: Decimal
    total_price: Decimal
```

---

## 5. Pydantic Schemas

```python
class PurchaseItemCreate(BaseModel):
    item_id: int
    unit_id: int
    quantity: Decimal (> 0)
    unit_price: Decimal (>= 0)
    discount: Decimal (default 0, >= 0)

class PurchaseCreate(BaseModel):
    supplier_id: int
    invoice_no: str | None
    purchase_date: date (default today)
    payment_type: PaymentType
    discount: Decimal (default 0, >= 0)
    items: list[PurchaseItemCreate] (min 1)
    paid_amount: Decimal (default 0, >= 0)    # only for 'partial' type
    notes: str | None

class PurchaseUpdate(BaseModel):
    invoice_no: str | None
    purchase_date: date | None
    payment_type: PaymentType | None
    discount: Decimal | None
    items: list[PurchaseItemCreate] | None     # replaces all items if provided
    notes: str | None

class PurchaseOut(BaseModel):
    id: int
    supplier: SupplierListOut
    invoice_no: str | None
    purchase_date: date
    payment_type: PaymentType
    subtotal: Decimal
    discount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    due_amount: Decimal
    status: PurchaseStatus
    items: list[PurchaseItemOut]
    payments: list[PurchasePaymentOut]
    notes: str | None
    confirmed_at: datetime | None
    created_at: datetime

class PurchasePaymentCreate(BaseModel):
    amount: Decimal (> 0)
    payment_mode: PaymentMode
    account_id: int | None
    reference_no: str | None

class PurchaseReturnCreate(BaseModel):
    return_date: date (default today)
    reason: str | None
    items: list[PurchaseReturnItemCreate] (min 1)

class PurchaseReturnItemCreate(BaseModel):
    item_id: int
    quantity: Decimal (> 0)
    unit_price: Decimal (> 0)
```

---

## 6. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/purchases` | read | List purchases (paginated + filters) |
| POST | `/purchases` | write | Create draft purchase |
| GET | `/purchases/{id}` | read | Purchase detail with items + payments |
| PUT | `/purchases/{id}` | write | Update draft purchase |
| DELETE | `/purchases/{id}` | write | Void draft purchase |
| POST | `/purchases/{id}/confirm` | write | Confirm purchase |
| POST | `/purchases/{id}/payments` | write | Add payment to credit purchase |
| GET | `/purchases/{id}/payments` | read | Payment history |
| POST | `/purchases/{id}/returns` | write | Create return |
| GET | `/purchases/{id}/returns` | read | View returns |
| PUT | `/purchases/returns/{return_id}/approve` | manager+ | Approve return |
| PUT | `/purchases/returns/{return_id}/reject` | manager+ | Reject return |

### Query Parameters (GET /purchases)
| Param | Type | Description |
|-------|------|-------------|
| `supplier_id` | int | Filter by supplier |
| `status` | draft\|confirmed\|returned\|void | |
| `payment_type` | cash\|credit\|partial | |
| `from_date`, `to_date` | date | Purchase date range |
| `search` | string | Invoice number search |
| `page`, `limit` | int | Pagination |

---

## 7. Confirm Purchase — Detailed Workflow

This is the most critical operation. All steps are **atomic** (single DB transaction):

```python
async def confirm(db, purchase_id, actor_id, notes=None):
    async with db.begin():

        # Step 1: Fetch and lock purchase
        purchase = await purchase_repo.get_or_404(db, purchase_id)
        if purchase.status != PurchaseStatus.DRAFT:
            raise InvalidStatusTransitionError("Only draft purchases can be confirmed")

        # Step 2: Validate all items still exist and are active
        for item_line in purchase.items:
            item = await inventory_repo.get_or_404(db, item_line.item_id)
            if not item.is_active:
                raise ValidationException(f"Item {item.name} is no longer active")

        # Step 3: Update stock for each item
        for item_line in purchase.items:
            await inventory_service.add_stock(
                db, item_line.item_id, item_line.quantity,
                movement_type=MovementType.PURCHASE_IN,
                reference_type='purchase', reference_id=purchase.id,
                actor_id=actor_id
            )
            # Also update weighted average cost on item
            await inventory_service.update_purchase_price(db, item_line.item_id, item_line.unit_price, item_line.quantity)

        # Step 4: Update supplier balance
        await supplier_service.update_balance(
            db, purchase.supplier_id,
            amount=purchase.total_amount,
            operation='add'    # increases payable
        )

        # Step 5: Handle initial payment (for cash or partial)
        if purchase.payment_type == PaymentType.CASH:
            purchase.paid_amount = purchase.total_amount
            await transaction_service.record(db,
                account_id=<default_cash_account>,
                transaction_type=TransactionType.DEBIT,
                reference_type='purchase', reference_id=purchase.id,
                amount=purchase.total_amount,
                description=f"Payment for Purchase #{purchase.id}",
                actor_id=actor_id
            )
        elif purchase.payment_type == PaymentType.PARTIAL and purchase.paid_amount > 0:
            await transaction_service.record(db, ..., amount=purchase.paid_amount, ...)

        # Step 6: Update status
        purchase.status = PurchaseStatus.CONFIRMED
        purchase.confirmed_at = datetime.utcnow()
        purchase.confirmed_by = actor_id
        if notes:
            purchase.notes = notes

        # Step 7: Audit log
        await audit_service.log(db, actor_id, 'UPDATE', 'purchases', purchase.id, ...)
```

---

## 8. Add Payment Workflow

```python
async def add_payment(db, purchase_id, payment_in, actor_id):
    async with db.begin():
        purchase = await purchase_repo.get_or_404(db, purchase_id)

        if purchase.status != PurchaseStatus.CONFIRMED:
            raise InvalidStatusTransitionError("Can only add payment to confirmed purchases")

        if payment_in.amount > purchase.due_amount:
            raise ValidationException("Payment exceeds remaining due amount")

        # Create payment record
        payment = PurchasePayment(**payment_in.dict(), purchase_id=purchase_id, created_by=actor_id)
        db.add(payment)

        # Update paid amount
        purchase.paid_amount += payment_in.amount

        # Reduce supplier balance
        await supplier_service.update_balance(db, purchase.supplier_id, payment_in.amount, 'subtract')

        # Record in transaction ledger
        await transaction_service.record(db, account_id=payment_in.account_id,
            transaction_type=TransactionType.DEBIT, ...)
```

---

## 9. Return Approval Workflow

```python
async def approve_return(db, return_id, actor_id):
    async with db.begin():
        ret = await purchase_repo.get_return_or_404(db, return_id)
        if ret.status != ReturnStatus.PENDING:
            raise InvalidStatusTransitionError()

        # Reverse stock for each returned item
        for ret_item in ret.items:
            await inventory_service.deduct_stock(
                db, ret_item.item_id, ret_item.quantity,
                movement_type=MovementType.RETURN_OUT,
                reference_type='purchase_return', reference_id=ret.id, ...
            )

        # Reduce supplier balance (credit note)
        await supplier_service.update_balance(db, purchase.supplier_id, ret.total_amount, 'subtract')

        ret.status = ReturnStatus.APPROVED
        ret.approved_by = actor_id
        ret.approved_at = datetime.utcnow()
```

---

## 10. Business Rules

| Rule | Detail |
|------|--------|
| Edit restriction | Only `draft` purchases can be edited; confirmed/void are immutable |
| Void restriction | Only `draft` purchases can be voided |
| Return quantity | Return quantity cannot exceed original purchase quantity |
| Payment overflow | Payment amount cannot exceed `due_amount` |
| Cash purchase | `paid_amount` auto-set to `total_amount` on confirm |
| Partial purchase | `paid_amount` must be > 0 and < `total_amount` |
| Calculations | `subtotal` = sum of all `item.total_price`; `total_amount` = `subtotal - discount` |

---

## 11. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Purchase not found | `NotFoundException` | 404 |
| Confirm non-draft | `InvalidStatusTransitionError` | 409 |
| Inactive item in purchase | `ValidationException` | 422 |
| Payment exceeds due | `ValidationException` | 422 |
| Return qty > purchase qty | `ValidationException` | 422 |
| Void confirmed purchase | `InvalidStatusTransitionError` | 409 |
