"""
Business logic for the Purchases module.

Lifecycle:
─────────────────────────────────────────────────────────────────────────────
  draft  →  confirmed  →  void          (confirmed cannot be un-confirmed)
                      ↘  returned       (via create_return + approve_return)

CREATE (draft):
  - Validate supplier is active.
  - Validate each line item (item active, unit exists).
  - Compute line totals: total_price = quantity × unit_price − discount.
  - Compute header: subtotal = Σ total_price, total = subtotal − header_discount.
  - For payment_type=cash, paid_amount = total_amount (fully paid at creation).
  - No stock movement yet — stock moves only on CONFIRM.

CONFIRM:
  - Only draft purchases can be confirmed.
  - For each line item → inventory_service.record_purchase_in().
  - Update supplier balance via supplier_service.apply_purchase_to_balance().
  - Set status=confirmed, confirmed_by, confirmed_at.

RECORD PAYMENT (on confirmed credit/partial purchases):
  - SELECT FOR UPDATE on purchase.
  - Validate amount does not exceed due_amount.
  - Increment paid_amount.
  - Insert PurchasePayment row.

VOID:
  - Only draft purchases can be voided (confirmed orders must be returned).

CREATE RETURN (on confirmed purchase):
  - Validate each return line item exists in the original purchase.
  - Compute return total.
  - Create PurchaseReturn with status=pending.

APPROVE RETURN:
  - Only pending returns can be approved.
  - For each return item → inventory_service.record_return_out() (stock leaves).
  - Reverse supplier balance via supplier_service.apply_purchase_to_balance(−amount).
  - Set return status=approved.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.enums import AuditAction, PaymentType, PurchaseStatus, ReturnStatus
from app.models.purchase import Purchase, PurchasePayment, PurchaseReturn
from app.services import audit_service
from app.repositories.purchase_repo import (
    PurchaseItemRepository,
    PurchasePaymentRepository,
    PurchaseRepository,
    PurchaseReturnRepository,
)
from app.schemas.purchase import (
    PurchaseCreate,
    PurchasePaymentCreate,
    PurchaseReturnCreate,
    PurchaseUpdate,
)

_repo = PurchaseRepository()
_item_repo = PurchaseItemRepository()
_pay_repo = PurchasePaymentRepository()
_ret_repo = PurchaseReturnRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_status(purchase: Purchase, *allowed: PurchaseStatus, action: str) -> None:
    if purchase.status not in allowed:
        raise ValidationException(
            f"Cannot {action} a purchase with status '{purchase.status.value}'."
        )


# ── Create ────────────────────────────────────────────────────────────────────

async def create_purchase(
    db: AsyncSession,
    body: PurchaseCreate,
    *,
    created_by: int,
) -> Purchase:
    """
    Create a purchase in draft status.

    Totals are computed here; stock and supplier balance are NOT touched
    until the purchase is confirmed.
    """
    from app.repositories.inventory_repo import ItemRepository
    from app.repositories.supplier_repo import SupplierRepository

    supplier = await SupplierRepository().get_or_404(db, body.supplier_id)
    if not supplier.is_active:
        raise NotFoundException(f"Supplier {body.supplier_id} not found.")

    item_repo = ItemRepository()

    # Validate and compute line totals; unit_id comes from the item itself
    line_data = []
    subtotal = Decimal("0")
    for line in body.items:
        inv_item = await item_repo.get_or_404(db, line.item_id)
        if not inv_item.is_active:
            raise NotFoundException(f"Item {line.item_id} not found.")

        total_price = (line.quantity * line.unit_price) - line.discount
        subtotal += total_price
        line_data.append({
            "item_id": line.item_id,
            "unit_id": inv_item.unit_id,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
            "discount": line.discount,
            "total_price": total_price,
        })

    header_discount = body.discount
    overhead = body.overhead_cost
    total_amount = max(Decimal("0"), subtotal - header_discount + overhead)

    if body.payment_type == PaymentType.cash:
        paid_amount = total_amount
    elif body.payment_type == PaymentType.partial:
        paid_amount = body.paid_amount  # schema guarantees it is not None
        if paid_amount > total_amount:
            raise ValidationException(
                "paid_amount exceeds total_amount.", field="paid_amount"
            )
    else:
        paid_amount = Decimal("0")

    purchase = await _repo.create(
        db,
        {
            "supplier_id": body.supplier_id,
            "purchase_date": body.purchase_date or date.today(),
            "payment_type": body.payment_type,
            "subtotal": subtotal,
            "discount": header_discount,
            "overhead_cost": overhead,
            "total_amount": total_amount,
            "paid_amount": paid_amount,
            "status": PurchaseStatus.draft,
            "notes": body.notes,
            "created_by": created_by,
        },
    )

    # Auto-generate invoice number now that we have the purchase ID
    purchase.invoice_no = f"PO-{date.today().strftime('%Y%m%d')}-{purchase.id:05d}"
    db.add(purchase)

    # Attach purchase_id to each line and bulk insert
    for line in line_data:
        line["purchase_id"] = purchase.id
    await _item_repo.bulk_create(db, line_data)

    await db.flush()
    await db.refresh(purchase, ["due_amount", "updated_at"])
    result = await _repo.get_with_items(db, purchase.id)
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="purchases", record_id=purchase.id,
        new_values=audit_service.snapshot(result),
    )
    return result


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_purchase(db: AsyncSession, purchase_id: int) -> Purchase:
    purchase = await _repo.get_with_items(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    return purchase


async def list_purchases(
    db: AsyncSession,
    *,
    supplier_id: int | None = None,
    status: PurchaseStatus | None = None,
    payment_type=None,
    search: str | None = None,
    from_date=None,
    to_date=None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "purchase_date",
    sort_order: str = "desc",
) -> tuple[list[Purchase], int]:
    return await _repo.list_purchases(
        db,
        supplier_id=supplier_id,
        status=status,
        payment_type=payment_type,
        search=search,
        from_date=from_date,
        to_date=to_date,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


# ── Update (draft only) ───────────────────────────────────────────────────────

async def update_purchase(
    db: AsyncSession, purchase_id: int, body: PurchaseUpdate, *, updated_by: int
) -> Purchase:
    from app.repositories.inventory_repo import ItemRepository

    purchase = await _repo.get_with_items(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    _assert_status(purchase, PurchaseStatus.draft, action="update")

    old = audit_service.snapshot(purchase)

    patch = body.model_dump(exclude_unset=True, exclude={"items"})
    if patch:
        await _repo.update(db, purchase, patch)

    if body.items is not None:
        # Delete existing line items
        existing = await _item_repo.get_for_purchase(db, purchase_id)
        for item in existing:
            await db.delete(item)
        await db.flush()

        # Validate new items and recompute totals
        item_repo = ItemRepository()
        line_data = []
        subtotal = Decimal("0")
        for line in body.items:
            inv_item = await item_repo.get_or_404(db, line.item_id)
            if not inv_item.is_active:
                raise NotFoundException(f"Item {line.item_id} not found.")
            total_price = (line.quantity * line.unit_price) - line.discount
            subtotal += total_price
            line_data.append({
                "purchase_id": purchase_id,
                "item_id": line.item_id,
                "unit_id": inv_item.unit_id,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount": line.discount,
                "total_price": total_price,
            })
        await _item_repo.bulk_create(db, line_data)

        header_discount = body.discount if body.discount is not None else purchase.discount
        total_amount = max(Decimal("0"), subtotal - header_discount + purchase.overhead_cost)
        await _repo.update_totals(
            db, purchase,
            subtotal=subtotal,
            discount=header_discount,
            total_amount=total_amount,
        )

    await db.flush()
    await db.refresh(purchase, ["due_amount", "updated_at"])
    updated = await _repo.get_with_items(db, purchase_id)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="purchases", record_id=purchase_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return updated


# ── Confirm ───────────────────────────────────────────────────────────────────

async def confirm_purchase(
    db: AsyncSession,
    purchase_id: int,
    *,
    confirmed_by: int,
) -> Purchase:
    """
    Confirm a draft purchase.
    Triggers stock-in for every line item and updates supplier balance.
    """
    from app.services import inventory_service, supplier_service, transaction_service
    from app.models.enums import TransactionType, ReferenceType

    purchase = await _repo.get_with_items(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    _assert_status(purchase, PurchaseStatus.draft, action="confirm")

    old = audit_service.snapshot(purchase)

    # Stock movements and price update for each line
    for line in purchase.items:
        await inventory_service.record_purchase_in(
            db,
            line.item_id,
            line.quantity,
            reference_id=purchase.id,
            created_by=confirmed_by,
        )
        await inventory_service.update_purchase_price(
            db,
            line.item_id,
            new_price=line.unit_price,
        )

    # Supplier balance: only credit/partial go on account; cash is settled
    if purchase.payment_type in (PaymentType.credit, PaymentType.partial):
        await supplier_service.apply_purchase_to_balance(
            db,
            purchase.supplier_id,
            purchase_amount=purchase.due_amount,
        )

    # 1. Always record the purchase event (total invoiced — no payment_method, no cash yet)
    await transaction_service.record_reference_transaction(
        db,
        payment_method=None,
        transaction_type=TransactionType.debit,
        reference_type=ReferenceType.purchase,
        reference_id=purchase.id,
        amount=purchase.total_amount,
        description=f"{purchase.invoice_no} — purchase invoiced",
        created_by=confirmed_by,
    )

    # 2. Record cash movement for upfront payment (cash or partial)
    if purchase.payment_type == PaymentType.cash:
        await transaction_service.record_reference_transaction(
            db,
            payment_method="cash",
            transaction_type=TransactionType.debit,
            reference_type=ReferenceType.purchase_payment,
            reference_id=purchase.id,
            amount=purchase.total_amount,
            description=f"{purchase.invoice_no} — cash paid",
            created_by=confirmed_by,
        )
    elif purchase.payment_type == PaymentType.partial and purchase.paid_amount > 0:
        await transaction_service.record_reference_transaction(
            db,
            payment_method="cash",
            transaction_type=TransactionType.debit,
            reference_type=ReferenceType.purchase_payment,
            reference_id=purchase.id,
            amount=purchase.paid_amount,
            description=f"{purchase.invoice_no} — partial payment upfront",
            created_by=confirmed_by,
        )

    now = datetime.now(timezone.utc)
    await _repo.set_status(
        db, purchase,
        status=PurchaseStatus.confirmed,
        confirmed_by=confirmed_by,
        confirmed_at=now,
    )
    await db.flush()
    await db.refresh(purchase, ["due_amount", "updated_at", "confirmed_at"])
    confirmed = await _repo.get_with_items(db, purchase_id)
    await audit_service.log(
        db, user_id=confirmed_by, action=AuditAction.UPDATE,
        table_name="purchases", record_id=purchase_id,
        old_values=old, new_values=audit_service.snapshot(confirmed),
    )
    return confirmed


# ── Void (draft only) ─────────────────────────────────────────────────────────

async def void_purchase(db: AsyncSession, purchase_id: int, *, voided_by: int) -> Purchase:
    purchase = await _repo.get_with_items(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    _assert_status(purchase, PurchaseStatus.draft, action="void")
    old = audit_service.snapshot(purchase)
    await _repo.set_status(db, purchase, status=PurchaseStatus.void)
    await db.flush()
    voided = await _repo.get_with_items(db, purchase_id)
    await audit_service.log(
        db, user_id=voided_by, action=AuditAction.UPDATE,
        table_name="purchases", record_id=purchase_id,
        old_values=old, new_values=audit_service.snapshot(voided),
    )
    return voided


# ── Payments (confirmed credit/partial) ───────────────────────────────────────

async def record_payment(
    db: AsyncSession,
    purchase_id: int,
    body: PurchasePaymentCreate,
    *,
    created_by: int,
) -> PurchasePayment:
    purchase = await _repo.get_with_lock(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    _assert_status(purchase, PurchaseStatus.confirmed, action="pay")

    old_purchase = audit_service.snapshot(purchase)

    if body.amount > purchase.due_amount:
        raise ValidationException(
            f"Payment amount {body.amount} exceeds due amount {purchase.due_amount}.",
            field="amount",
        )

    await _repo.add_paid_amount(db, purchase, amount=body.amount)

    paid_at = body.paid_at or datetime.now(timezone.utc)
    payment = await _pay_repo.save(
        db,
        purchase_id=purchase_id,
        amount=body.amount,
        payment_mode=body.payment_mode,
        account_id=body.account_id,
        reference_no=body.reference_no,
        paid_at=paid_at,
        created_by=created_by,
    )

    # Reduce supplier payable by the payment amount
    from app.services import supplier_service, transaction_service
    from app.models.enums import TransactionType, ReferenceType
    await supplier_service.record_payment(
        db,
        purchase.supplier_id,
        body,  # type: ignore[arg-type]
        created_by=created_by,
    )

    # Post reference transaction: money paid out via payment_mode
    await transaction_service.record_reference_transaction(
        db,
        payment_method=body.payment_mode.value,
        transaction_type=TransactionType.debit,
        reference_type=ReferenceType.purchase_payment,
        reference_id=payment.id,
        amount=body.amount,
        description=f"{purchase.invoice_no} — payment made",
        created_by=created_by,
    )

    await db.flush()
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="purchase_payments", record_id=payment.id,
        new_values=audit_service.snapshot(payment),
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.UPDATE,
        table_name="purchases", record_id=purchase.id,
        old_values=old_purchase, new_values=audit_service.snapshot(purchase),
    )
    return payment


async def list_payments(
    db: AsyncSession, purchase_id: int
) -> list[PurchasePayment]:
    purchase = await _repo.get_with_items(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    return await _pay_repo.list_for_purchase(db, purchase_id)


# ── Returns ───────────────────────────────────────────────────────────────────

async def create_return(
    db: AsyncSession,
    purchase_id: int,
    body: PurchaseReturnCreate,
    *,
    created_by: int,
) -> PurchaseReturn:
    purchase = await _repo.get_with_items(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    _assert_status(purchase, PurchaseStatus.confirmed, action="return")

    # Build a lookup of original line quantities {item_id: quantity}
    original = {line.item_id: line for line in purchase.items}

    return_items_data = []
    total_amount = Decimal("0")
    for ret_line in body.items:
        if ret_line.item_id not in original:
            raise ValidationException(
                f"Item {ret_line.item_id} was not in the original purchase.",
                field="item_id",
            )
        orig_line = original[ret_line.item_id]
        if ret_line.quantity > orig_line.quantity:
            raise ValidationException(
                f"Return quantity {ret_line.quantity} exceeds purchased "
                f"quantity {orig_line.quantity} for item {ret_line.item_id}.",
                field="quantity",
            )
        total_price = ret_line.quantity * ret_line.unit_price
        total_amount += total_price
        return_items_data.append({
            "item_id": ret_line.item_id,
            "quantity": ret_line.quantity,
            "unit_price": ret_line.unit_price,
            "total_price": total_price,
        })

    purchase_return = await _ret_repo.create_return(
        db,
        purchase_id=purchase_id,
        reason=body.reason,
        total_amount=total_amount,
        created_by=created_by,
    )

    for item_data in return_items_data:
        item_data["return_id"] = purchase_return.id
    await _ret_repo.bulk_create_items(db, return_items_data)

    ret = await _ret_repo.get_with_items(db, purchase_return.id)
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="purchase_returns", record_id=ret.id,
        new_values=audit_service.snapshot(ret),
    )
    return ret


async def approve_return(
    db: AsyncSession,
    purchase_id: int,
    return_id: int,
    *,
    approved_by: int,
) -> PurchaseReturn:
    """
    Approve a pending return.
    Reverses stock (return_out) and reduces supplier balance.
    """
    from app.services import inventory_service, supplier_service

    purchase_return = await _ret_repo.get_with_items(db, return_id)
    if purchase_return is None or purchase_return.purchase_id != purchase_id:
        raise NotFoundException(f"Return {return_id} not found.")
    if purchase_return.status != ReturnStatus.pending:
        raise ValidationException(
            f"Return is already '{purchase_return.status.value}'."
        )

    old = audit_service.snapshot(purchase_return)

    # Validate stock availability before deducting any items
    from app.repositories.inventory_repo import ItemRepository
    item_repo = ItemRepository()
    for ret_item in purchase_return.return_items:
        inv_item = await item_repo.get_or_404(db, ret_item.item_id)
        if inv_item.current_stock < ret_item.quantity:
            raise ValidationException(
                f"Cannot approve return: Insufficient stock for '{inv_item.name}'. "
                f"Available: {inv_item.current_stock}, Return qty: {ret_item.quantity}"
            )

    for ret_item in purchase_return.return_items:
        await inventory_service.record_return_out(
            db,
            ret_item.item_id,
            ret_item.quantity,
            reference_id=return_id,
            created_by=approved_by,
        )

    # Reduce supplier payable by return amount
    from app.services.supplier_service import _compute_new_balance
    from app.repositories.supplier_repo import SupplierRepository
    supplier_repo = SupplierRepository()
    purchase = await _repo.get_with_lock(db, purchase_id)
    supplier = await supplier_repo.get_with_lock(db, purchase.supplier_id)
    if supplier and supplier.is_active:
        new_balance, new_balance_type = _compute_new_balance(
            supplier.balance,
            supplier.balance_type,
            delta=-purchase_return.total_amount,
        )
        await supplier_repo.apply_balance_update(
            db, supplier,
            new_balance=new_balance,
            new_balance_type=new_balance_type,
        )

    now = datetime.now(timezone.utc)
    await _ret_repo.approve(
        db, purchase_return, approved_by=approved_by, approved_at=now
    )
    await db.flush()
    approved = await _ret_repo.get_with_items(db, return_id)
    await audit_service.log(
        db, user_id=approved_by, action=AuditAction.UPDATE,
        table_name="purchase_returns", record_id=return_id,
        old_values=old, new_values=audit_service.snapshot(approved),
    )
    return approved


async def reject_return(
    db: AsyncSession,
    purchase_id: int,
    return_id: int,
    *,
    rejected_by: int,
) -> PurchaseReturn:
    """Reject a pending return — no stock or balance changes."""
    purchase_return = await _ret_repo.get_with_items(db, return_id)
    if purchase_return is None or purchase_return.purchase_id != purchase_id:
        raise NotFoundException(f"Return {return_id} not found.")
    if purchase_return.status != ReturnStatus.pending:
        raise ValidationException(
            f"Return is already '{purchase_return.status.value}'."
        )

    old = audit_service.snapshot(purchase_return)
    now = datetime.now(timezone.utc)
    await _ret_repo.reject(
        db, purchase_return, rejected_by=rejected_by, rejected_at=now
    )
    await db.flush()
    rejected = await _ret_repo.get_with_items(db, return_id)
    await audit_service.log(
        db, user_id=rejected_by, action=AuditAction.UPDATE,
        table_name="purchase_returns", record_id=return_id,
        old_values=old, new_values=audit_service.snapshot(rejected),
    )
    return rejected


async def list_returns(
    db: AsyncSession, purchase_id: int
) -> list[PurchaseReturn]:
    purchase = await _repo.get_with_items(db, purchase_id)
    if purchase is None:
        raise NotFoundException(f"Purchase {purchase_id} not found.")
    return await _ret_repo.list_for_purchase(db, purchase_id)
