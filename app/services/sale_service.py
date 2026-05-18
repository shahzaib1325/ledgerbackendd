"""
Business logic for the Sales module.

Lifecycle:
─────────────────────────────────────────────────────────────────────────────
  draft  →  confirmed  →  partially_paid / paid
                      ↘  void          (draft only)
                      ↘  returned      (via create_return + approve_return)

CREATE (draft):
  - Validate customer is active; check credit limit for credit/partial types.
  - Validate each line item (item active, unit exists, sufficient stock for confirmed).
  - Compute line totals: total_price = quantity × unit_price − discount.
  - Compute header: subtotal = Σ total_price; total = subtotal − discount + tax.
  - For payment_type=cash, paid_amount = total_amount (fully paid at creation).
  - No stock movement yet — stock moves only on CONFIRM.

CONFIRM:
  - Only draft invoices can be confirmed.
  - For each line item → inventory_service.record_sale_out() (stock leaves).
  - Update customer balance via customer_service.apply_sale_to_balance().
  - Set status=confirmed (or paid/partially_paid for cash).
  - Set confirmed_by, confirmed_at.

RECORD PAYMENT (on confirmed credit/partial invoices):
  - SELECT FOR UPDATE on invoice.
  - Validate amount does not exceed due_amount.
  - Increment paid_amount; status transitions: confirmed → partially_paid → paid.
  - Insert SalePayment row.
  - Reduce customer receivable via customer_service.record_payment().

VOID:
  - Only draft invoices can be voided.

CREATE RETURN (on confirmed purchase):
  - Validate each return line item exists in the original invoice.
  - Compute return total.
  - Create SaleReturn with status=pending.

APPROVE RETURN:
  - Only pending returns can be approved.
  - For each return item → inventory_service.record_return_in() (stock comes back).
  - Reverse customer balance via customer_service.apply_sale_to_balance(−amount).
  - Set return status=approved.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.enums import AuditAction, PaymentType, SaleStatus, ReturnStatus
from app.models.sale import SaleInvoice, SalePayment, SaleReturn
from app.services import audit_service
from app.repositories.sale_repo import (
    SaleItemRepository,
    SalePaymentRepository,
    SaleRepository,
    SaleReturnRepository,
)
from app.schemas.sale import (
    SaleCreate,
    SalePaymentCreate,
    SaleReturnCreate,
    SaleUpdate,
)

_repo = SaleRepository()
_item_repo = SaleItemRepository()
_pay_repo = SalePaymentRepository()
_ret_repo = SaleReturnRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_status(invoice: SaleInvoice, *allowed: SaleStatus, action: str) -> None:
    if invoice.status not in allowed:
        raise ValidationException(
            f"Cannot {action} an invoice with status '{invoice.status.value}'."
        )


def _check_credit_limit(customer: object, sale_amount: Decimal) -> None:
    from app.core.exceptions import CreditLimitExceededError
    from app.models.enums import BalanceType
    if customer.credit_limit <= Decimal("0"):
        return
    current_receivable = (
        customer.balance if customer.balance_type == BalanceType.receivable else Decimal("0")
    )
    if current_receivable + sale_amount > customer.credit_limit:
        raise CreditLimitExceededError(
            f"Sale amount {sale_amount} would exceed credit limit "
            f"{customer.credit_limit} (current receivable: {current_receivable})."
        )


# ── Create ────────────────────────────────────────────────────────────────────

async def create_sale(
    db: AsyncSession,
    body: SaleCreate,
    *,
    created_by: int,
) -> SaleInvoice:
    """
    Create a sale invoice as confirmed.

    Stock is deducted, customer balance updated, and transactions posted
    immediately at creation time. No draft step.
    """
    from app.repositories.inventory_repo import ItemRepository
    from app.repositories.customer_repo import CustomerRepository

    customer = None
    if body.customer_type == "regular" and body.customer_id is not None:
        customer = await CustomerRepository().get_or_404(db, body.customer_id)
        if not customer.is_active:
            raise NotFoundException(f"Customer {body.customer_id} not found.")

    item_repo = ItemRepository()

    # Aggregate quantities for stock validation (handles duplicate items in one invoice)
    qty_by_item = {}
    for line in body.items:
        qty_by_item[line.item_id] = qty_by_item.get(line.item_id, Decimal("0")) + line.quantity

    line_data = []
    subtotal = Decimal("0")
    for line in body.items:
        inv_item = await item_repo.get_or_404(db, line.item_id)
        if not inv_item.is_active:
            raise NotFoundException(f"Item {line.item_id} not found.")

        # Validate aggregate stock
        total_qty_requested = qty_by_item[line.item_id]
        if total_qty_requested > inv_item.current_stock:
            raise ValidationException(
                f"Cannot save draft: Insufficient stock for '{inv_item.name}'. "
                f"Total Required: {total_qty_requested}, Available: {inv_item.current_stock}"
            )

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
    tax = body.tax
    total_amount = max(Decimal("0"), subtotal - header_discount + tax)

    if customer and body.payment_type in (PaymentType.credit, PaymentType.partial):
        _check_credit_limit(customer, total_amount)

    if body.payment_type == PaymentType.cash:
        paid_amount = total_amount
    elif body.payment_type == PaymentType.partial:
        paid_amount = body.amount_paid or Decimal("0")
        if paid_amount <= 0 or paid_amount >= total_amount:
            raise ValidationException("Partial payment amount must be greater than 0 and less than the total amount.", field="amount_paid")
    else:
        paid_amount = Decimal("0")

    invoice = await _repo.create(
        db,
        {
            "customer_id": body.customer_id,
            "customer_type": body.customer_type,
            "walking_customer_name": body.walking_customer_name,
            "walking_customer_phone": body.walking_customer_phone,
            "walking_customer_email": str(body.walking_customer_email) if body.walking_customer_email else None,
            "walking_customer_address": body.walking_customer_address,
            "walking_customer_tax_id": body.walking_customer_tax_id,
            "invoice_no": "PENDING",
            "invoice_date": body.invoice_date or date.today(),
            "due_date": body.due_date,
            "payment_type": body.payment_type,
            "subtotal": subtotal,
            "discount": header_discount,
            "tax": tax,
            "total_amount": total_amount,
            "paid_amount": paid_amount,
            "status": SaleStatus.paid if body.payment_type == PaymentType.cash else SaleStatus.confirmed,
            "notes": body.notes,
            "created_by": created_by,
            "confirmed_by": created_by,
            "confirmed_at": datetime.now(timezone.utc),
        },
    )

    await db.flush()
    invoice.invoice_no = f"INV-{date.today().strftime('%Y%m%d')}-{invoice.id:05d}"
    db.add(invoice)

    for line in line_data:
        line["invoice_id"] = invoice.id
    await _item_repo.bulk_create(db, line_data)

    await db.flush()
    await db.refresh(invoice, ["due_amount", "updated_at"])

    # ── Stock out for each line item ─────────────────────────────────────────
    from app.services import inventory_service, customer_service, transaction_service
    from app.models.enums import TransactionType, ReferenceType

    for line in line_data:
        await inventory_service.record_sale_out(
            db, line["item_id"], line["quantity"],
            reference_id=invoice.id, created_by=created_by,
        )

    # ── Customer balance ─────────────────────────────────────────────────────
    if invoice.customer_id and invoice.payment_type in (PaymentType.credit, PaymentType.partial):
        balance_amount = (
            invoice.total_amount - invoice.paid_amount
            if invoice.payment_type == PaymentType.partial
            else invoice.total_amount
        )
        await customer_service.apply_sale_to_balance(
            db, invoice.customer_id, sale_amount=balance_amount,
        )

    # ── Transactions ─────────────────────────────────────────────────────────
    await transaction_service.record_reference_transaction(
        db, payment_method=None,
        transaction_type=TransactionType.credit,
        reference_type=ReferenceType.sale,
        reference_id=invoice.id, amount=invoice.total_amount,
        description=f"{invoice.invoice_no} — sale invoiced",
        created_by=created_by,
    )
    if invoice.payment_type == PaymentType.cash:
        await transaction_service.record_reference_transaction(
            db, payment_method="cash",
            transaction_type=TransactionType.credit,
            reference_type=ReferenceType.sale_payment,
            reference_id=invoice.id, amount=invoice.total_amount,
            description=f"{invoice.invoice_no} — cash collected",
            created_by=created_by,
        )
    elif invoice.payment_type == PaymentType.partial and invoice.paid_amount > 0:
        await transaction_service.record_reference_transaction(
            db, payment_method="cash",
            transaction_type=TransactionType.credit,
            reference_type=ReferenceType.sale_payment,
            reference_id=invoice.id, amount=invoice.paid_amount,
            description=f"{invoice.invoice_no} — partial payment upfront",
            created_by=created_by,
        )

    result = await _repo.get_with_items(db, invoice.id)
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="sale_invoices", record_id=invoice.id,
        new_values=audit_service.snapshot(result),
    )
    return result


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_sale(db: AsyncSession, invoice_id: int) -> SaleInvoice:
    invoice = await _repo.get_with_items(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    return invoice


async def list_sales(
    db: AsyncSession,
    *,
    customer_id: int | None = None,
    status: SaleStatus | None = None,
    from_date=None,
    to_date=None,
    overdue_only: bool = False,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "invoice_date",
    sort_order: str = "desc",
) -> tuple[list[SaleInvoice], int]:
    return await _repo.list_sales(
        db,
        customer_id=customer_id,
        status=status,
        from_date=from_date,
        to_date=to_date,
        overdue_only=overdue_only,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


# ── Update (draft only) ───────────────────────────────────────────────────────

async def update_sale(
    db: AsyncSession, invoice_id: int, body: SaleUpdate, *, updated_by: int
) -> SaleInvoice:
    from app.repositories.inventory_repo import ItemRepository

    invoice = await _repo.get_with_items(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    _assert_status(
        invoice,
        SaleStatus.confirmed, SaleStatus.paid, SaleStatus.partially_paid,
        action="update",
    )

    old = audit_service.snapshot(invoice)

    new_items = body.items
    patch = body.model_dump(exclude_unset=True, exclude={"items"})

    # Resolve effective customer_type and payment_type for validation
    eff_type = patch.get("customer_type", invoice.customer_type)
    if eff_type == "walking":
        patch["customer_id"] = None
        patch["payment_type"] = PaymentType.cash
    elif eff_type == "regular":
        eff_cid = patch.get("customer_id", invoice.customer_id)
        if eff_cid is None:
            raise ValidationException("customer_id is required for regular customers.", field="customer_id")

    if new_items is not None:
        from app.services import inventory_service

        item_repo = ItemRepository()

        # Reverse stock for old line items
        for old_line in invoice.items:
            await inventory_service.record_return_in(
                db, old_line.item_id, old_line.quantity,
                reference_id=invoice.id, created_by=updated_by,
            )

        await _item_repo.delete_for_invoice(db, invoice.id)
        invoice.items = []  # Clear relationship in memory to prevent SQLAlchemy error

        # Aggregate quantities for stock validation
        qty_by_item = {}
        for line in new_items:
            qty_by_item[line.item_id] = qty_by_item.get(line.item_id, Decimal("0")) + line.quantity

        line_data = []
        subtotal = Decimal("0")
        for line in new_items:
            inv_item = await item_repo.get_or_404(db, line.item_id)
            if not inv_item.is_active:
                raise NotFoundException(f"Item {line.item_id} not found.")

            # Validate aggregate stock
            total_qty_requested = qty_by_item[line.item_id]
            if total_qty_requested > inv_item.current_stock:
                raise ValidationException(
                    f"Cannot update draft: Insufficient stock for '{inv_item.name}'. "
                    f"Total Required: {total_qty_requested}, Available: {inv_item.current_stock}"
                )

            total_price = (line.quantity * line.unit_price) - line.discount
            subtotal += total_price
            line_data.append({
                "invoice_id": invoice.id,
                "item_id": line.item_id,
                "unit_id": inv_item.unit_id,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount": line.discount,
                "total_price": total_price,
            })

        await _item_repo.bulk_create(db, line_data)

        # Apply stock out for new line items
        for line in line_data:
            await inventory_service.record_sale_out(
                db, line["item_id"], line["quantity"],
                reference_id=invoice.id, created_by=updated_by,
            )

        header_discount = Decimal(str(patch.get("discount", invoice.discount)))
        tax = Decimal(str(patch.get("tax", invoice.tax)))
        total_amount = max(Decimal("0"), subtotal - header_discount + tax)
        patch["subtotal"] = subtotal
        patch["total_amount"] = total_amount

        eff_pt = patch.get("payment_type", invoice.payment_type)
        if eff_pt == PaymentType.cash:
            patch["paid_amount"] = total_amount
        elif eff_pt == PaymentType.partial:
            # Prefer incoming amount_paid, fallback to invoice.paid_amount
            if "amount_paid" in patch and patch["amount_paid"] is not None:
                paid_amount = Decimal(str(patch["amount_paid"]))
            else:
                paid_amount = invoice.paid_amount

            if paid_amount <= 0 or paid_amount >= total_amount:
                raise ValidationException("Partial payment amount must be greater than 0 and less than the total amount.", field="amount_paid")
            patch["paid_amount"] = paid_amount
        else:
            patch["paid_amount"] = Decimal("0")

        # Remove amount_paid from patch so we don't try to save it directly to the model
        patch.pop("amount_paid", None)
    else:
        # No item changes — still validate payment_type/amount_paid changes against existing total
        eff_pt = patch.get("payment_type", invoice.payment_type)
        current_total = invoice.total_amount
        payment_type_changing = "payment_type" in patch
        amount_paid_changing = "amount_paid" in patch

        if payment_type_changing or amount_paid_changing:
            if eff_pt == PaymentType.cash:
                if payment_type_changing:
                    patch["paid_amount"] = current_total
            elif eff_pt == PaymentType.partial:
                if "amount_paid" in patch and patch["amount_paid"] is not None:
                    paid_amount = Decimal(str(patch["amount_paid"]))
                else:
                    paid_amount = invoice.paid_amount or Decimal("0")
                if paid_amount <= 0 or paid_amount >= current_total:
                    raise ValidationException(
                        "Partial payment amount must be greater than 0 and less than the total amount.",
                        field="amount_paid",
                    )
                patch["paid_amount"] = paid_amount
            else:  # credit
                if payment_type_changing:
                    patch["paid_amount"] = Decimal("0")

        patch.pop("amount_paid", None)

    # Coerce EmailStr to plain str if present (Pydantic EmailStr is not a plain string)
    if "walking_customer_email" in patch and patch["walking_customer_email"] is not None:
        patch["walking_customer_email"] = str(patch["walking_customer_email"])

    # Clear walking fields if switching to a regular customer
    if patch.get("customer_type") == "regular":
        patch.setdefault("walking_customer_name", None)
        patch.setdefault("walking_customer_phone", None)
        patch.setdefault("walking_customer_email", None)
        patch.setdefault("walking_customer_address", None)
        patch.setdefault("walking_customer_tax_id", None)

    # ── Reverse and reapply customer balance if financials changed ──────────
    from app.services import customer_service

    # Compute old balance contribution
    old_cid = invoice.customer_id
    old_pt = invoice.payment_type
    old_bal = Decimal("0")
    if old_cid and old_pt in (PaymentType.credit, PaymentType.partial):
        old_bal = (invoice.total_amount - invoice.paid_amount) if old_pt == PaymentType.partial else invoice.total_amount

    updated = await _repo.update(db, invoice, patch)
    await db.flush()
    await db.refresh(updated, ["due_amount", "updated_at", "total_amount", "paid_amount", "payment_type", "customer_id"])

    # Compute new balance contribution
    new_cid = updated.customer_id
    new_pt = updated.payment_type
    new_bal = Decimal("0")
    if new_cid and new_pt in (PaymentType.credit, PaymentType.partial):
        new_bal = (updated.total_amount - updated.paid_amount) if new_pt == PaymentType.partial else updated.total_amount

    # Reverse old, apply new (only if changed)
    if old_bal != new_bal or old_cid != new_cid:
        if old_cid and old_bal > 0:
            await customer_service.apply_sale_to_balance(db, old_cid, sale_amount=-old_bal)
        if new_cid and new_bal > 0:
            await customer_service.apply_sale_to_balance(db, new_cid, sale_amount=new_bal)

    result = await _repo.get_with_items(db, invoice_id)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="sale_invoices", record_id=invoice_id,
        old_values=old, new_values=audit_service.snapshot(result),
    )
    return result


# ── Confirm ───────────────────────────────────────────────────────────────────

async def confirm_sale(
    db: AsyncSession,
    invoice_id: int,
    *,
    confirmed_by: int,
) -> SaleInvoice:
    """
    Confirm a draft invoice.
    Triggers stock-out for every line item and updates customer balance.
    """
    from app.services import inventory_service, customer_service, transaction_service
    from app.models.enums import TransactionType, ReferenceType

    invoice = await _repo.get_with_items(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    _assert_status(invoice, SaleStatus.draft, action="confirm")

    old = audit_service.snapshot(invoice)

    from app.repositories.inventory_repo import ItemRepository
    item_repo = ItemRepository()

    # Aggregate quantities for stock validation (handles duplicate items in one invoice)
    qty_by_item = {}
    for line in invoice.items:
        qty_by_item[line.item_id] = qty_by_item.get(line.item_id, Decimal("0")) + line.quantity

    # Stock out for each line
    for line in invoice.items:
        # Validate stock against aggregate total
        inv_item = await item_repo.get_or_404(db, line.item_id)
        total_qty_requested = qty_by_item[line.item_id]
        if total_qty_requested > inv_item.current_stock:
            raise ValidationException(
                f"Cannot confirm sale: Insufficient stock for '{inv_item.name}'. "
                f"Total Required: {total_qty_requested}, Available: {inv_item.current_stock}"
            )

        await inventory_service.record_sale_out(
            db,
            line.item_id,
            line.quantity,
            reference_id=invoice.id,
            created_by=confirmed_by,
        )

    # Customer balance: only credit/partial go on account; cash is settled.
    # For partial: only the unpaid portion (due_amount) becomes a receivable —
    # the upfront paid_amount was already collected in cash.
    # Walking customers (customer_id=None) are cash-only, skipped.
    if invoice.customer_id and invoice.payment_type in (PaymentType.credit, PaymentType.partial):
        balance_amount = (
            invoice.total_amount - invoice.paid_amount
            if invoice.payment_type == PaymentType.partial
            else invoice.total_amount
        )
        await customer_service.apply_sale_to_balance(
            db,
            invoice.customer_id,
            sale_amount=balance_amount,
        )

    # 1. Always record the sale event (total invoiced — no payment_method, no cash yet)
    await transaction_service.record_reference_transaction(
        db,
        payment_method=None,
        transaction_type=TransactionType.credit,
        reference_type=ReferenceType.sale,
        reference_id=invoice.id,
        amount=invoice.total_amount,
        description=f"{invoice.invoice_no} — sale invoiced",
        created_by=confirmed_by,
    )

    # 2. Record cash movement for upfront payment (cash or partial)
    if invoice.payment_type == PaymentType.cash:
        await transaction_service.record_reference_transaction(
            db,
            payment_method="cash",
            transaction_type=TransactionType.credit,
            reference_type=ReferenceType.sale_payment,
            reference_id=invoice.id,
            amount=invoice.total_amount,
            description=f"{invoice.invoice_no} — cash collected",
            created_by=confirmed_by,
        )
    elif invoice.payment_type == PaymentType.partial and invoice.paid_amount > 0:
        await transaction_service.record_reference_transaction(
            db,
            payment_method="cash",
            transaction_type=TransactionType.credit,
            reference_type=ReferenceType.sale_payment,
            reference_id=invoice.id,
            amount=invoice.paid_amount,
            description=f"{invoice.invoice_no} — partial payment upfront",
            created_by=confirmed_by,
        )

    # Determine confirmed status
    if invoice.payment_type == PaymentType.cash:
        new_status = SaleStatus.paid
    else:
        new_status = SaleStatus.confirmed

    now = datetime.now(timezone.utc)
    await _repo.set_status(
        db, invoice,
        status=new_status,
        confirmed_by=confirmed_by,
        confirmed_at=now,
    )
    await db.flush()
    await db.refresh(invoice, ["due_amount", "updated_at", "confirmed_at"])
    confirmed = await _repo.get_with_items(db, invoice_id)
    await audit_service.log(
        db, user_id=confirmed_by, action=AuditAction.UPDATE,
        table_name="sale_invoices", record_id=invoice_id,
        old_values=old, new_values=audit_service.snapshot(confirmed),
    )
    return confirmed


# ── Void (draft only) ─────────────────────────────────────────────────────────

async def void_sale(db: AsyncSession, invoice_id: int, *, voided_by: int) -> SaleInvoice:
    """
    Void a sale invoice. Reverses stock and customer balance if confirmed.
    """
    from app.services import inventory_service, customer_service
    from app.repositories.customer_repo import CustomerRepository

    invoice = await _repo.get_with_items(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    _assert_status(
        invoice,
        SaleStatus.confirmed, SaleStatus.paid, SaleStatus.partially_paid,
        action="void",
    )

    old = audit_service.snapshot(invoice)

    # Reverse stock: return items to inventory
    for line in invoice.items:
        await inventory_service.record_return_in(
            db, line.item_id, line.quantity,
            reference_id=invoice.id, created_by=voided_by,
        )

    # Reverse customer balance
    if invoice.customer_id and invoice.payment_type in (PaymentType.credit, PaymentType.partial):
        from app.services.customer_service import _compute_new_balance
        customer_repo = CustomerRepository()
        customer = await customer_repo.get_with_lock(db, invoice.customer_id)
        if customer and customer.is_active:
            balance_amount = (
                invoice.total_amount - invoice.paid_amount
                if invoice.payment_type == PaymentType.partial
                else invoice.total_amount
            )
            new_balance, new_balance_type = _compute_new_balance(
                customer.balance, customer.balance_type, delta=-balance_amount,
            )
            await customer_repo.apply_balance_update(
                db, customer, new_balance=new_balance, new_balance_type=new_balance_type,
            )

    await _repo.set_status(db, invoice, status=SaleStatus.void)
    await db.flush()
    voided = await _repo.get_with_items(db, invoice_id)
    await audit_service.log(
        db, user_id=voided_by, action=AuditAction.UPDATE,
        table_name="sale_invoices", record_id=invoice_id,
        old_values=old, new_values=audit_service.snapshot(voided),
    )
    return voided


# ── Payments ──────────────────────────────────────────────────────────────────

async def record_payment(
    db: AsyncSession,
    invoice_id: int,
    body: SalePaymentCreate,
    *,
    created_by: int,
) -> SalePayment:
    invoice = await _repo.get_with_lock(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    _assert_status(
        invoice,
        SaleStatus.confirmed, SaleStatus.partially_paid,
        action="pay",
    )

    old_invoice = audit_service.snapshot(invoice)

    if body.amount > invoice.due_amount:
        raise ValidationException(
            f"Payment amount {body.amount} exceeds due amount {invoice.due_amount}.",
            field="amount",
        )

    await _repo.add_paid_amount(db, invoice, amount=body.amount)

    received_at = body.received_at or datetime.now(timezone.utc)
    payment = await _pay_repo.save(
        db,
        invoice_id=invoice_id,
        amount=body.amount,
        payment_mode=body.payment_mode,
        account_id=body.account_id,
        reference_no=body.reference_no,
        received_at=received_at,
        created_by=created_by,
    )

    # Reduce customer receivable by payment amount (balance update only — no CustomerPayment row)
    from app.services.customer_service import _compute_new_balance
    from app.repositories.customer_repo import CustomerRepository
    customer_repo = CustomerRepository()
    customer = await customer_repo.get_with_lock(db, invoice.customer_id) if invoice.customer_id else None
    if customer and customer.is_active:
        new_balance, new_balance_type = _compute_new_balance(
            customer.balance,
            customer.balance_type,
            delta=-body.amount,
        )
        await customer_repo.apply_balance_update(
            db, customer,
            new_balance=new_balance,
            new_balance_type=new_balance_type,
        )

    # Post reference transaction: money received via payment_mode
    from app.services import transaction_service
    from app.models.enums import TransactionType, ReferenceType
    await transaction_service.record_reference_transaction(
        db,
        payment_method=body.payment_mode.value,
        transaction_type=TransactionType.credit,
        reference_type=ReferenceType.sale_payment,
        reference_id=payment.id,
        amount=body.amount,
        description=f"{invoice.invoice_no} — payment received",
        created_by=created_by,
    )

    await db.flush()
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="sale_payments", record_id=payment.id,
        new_values=audit_service.snapshot(payment),
    )
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.UPDATE,
        table_name="sale_invoices", record_id=invoice.id,
        old_values=old_invoice, new_values=audit_service.snapshot(invoice),
    )
    return payment


async def list_payments(
    db: AsyncSession, invoice_id: int
) -> list[SalePayment]:
    invoice = await _repo.get_with_items(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    return await _pay_repo.list_for_invoice(db, invoice_id)


# ── Returns ───────────────────────────────────────────────────────────────────

async def create_return(
    db: AsyncSession,
    invoice_id: int,
    body: SaleReturnCreate,
    *,
    created_by: int,
) -> SaleReturn:
    invoice = await _repo.get_with_items(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    _assert_status(
        invoice,
        SaleStatus.confirmed, SaleStatus.partially_paid, SaleStatus.paid,
        action="return",
    )

    original = {line.item_id: line for line in invoice.items}

    return_items_data = []
    total_amount = Decimal("0")
    for ret_line in body.items:
        if ret_line.item_id not in original:
            raise ValidationException(
                f"Item {ret_line.item_id} was not in the original invoice.",
                field="item_id",
            )
        orig_line = original[ret_line.item_id]

        # Cumulative guard: account for quantities already returned and approved
        already_returned = await _ret_repo.get_approved_qty_by_item(
            db, invoice_id, ret_line.item_id
        )
        returnable_qty = orig_line.quantity - already_returned
        if ret_line.quantity > returnable_qty:
            raise ValidationException(
                f"Return quantity {ret_line.quantity} for item {ret_line.item_id} "
                f"exceeds returnable quantity {returnable_qty} "
                f"({already_returned} already returned of {orig_line.quantity} sold).",
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

    # Aggregate check: total approved returns + this return must not exceed invoice total
    total_approved = sum(
        r.total_amount
        for r in await _ret_repo.list_for_invoice(db, invoice_id)
        if r.status == ReturnStatus.approved
    )
    if total_approved + total_amount > invoice.total_amount:
        raise ValidationException(
            f"Total return amount ({total_approved + total_amount}) would exceed "
            f"invoice total ({invoice.total_amount}).",
        )

    penalty = body.penalty
    refund_amount = max(Decimal("0"), total_amount - penalty)

    sale_return = await _ret_repo.create_return(
        db,
        invoice_id=invoice_id,
        return_type=body.return_type,
        reason=body.reason,
        total_amount=total_amount,
        penalty=penalty,
        refund_amount=refund_amount,
        created_by=created_by,
    )

    for item_data in return_items_data:
        item_data["return_id"] = sale_return.id
    await _ret_repo.bulk_create_items(db, return_items_data)

    ret = await _ret_repo.get_with_items(db, sale_return.id)
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="sale_returns", record_id=ret.id,
        new_values={
            **audit_service.snapshot(ret),
            "items": [audit_service.snapshot(item) for item in ret.return_items],
        },
    )
    return ret


async def approve_return(
    db: AsyncSession,
    invoice_id: int,
    return_id: int,
    *,
    approved_by: int,
) -> SaleReturn:
    """
    Approve a pending return.
    Reverses stock (return_in) and reduces customer receivable.
    """
    from app.services import inventory_service
    from app.services.customer_service import _compute_new_balance
    from app.repositories.customer_repo import CustomerRepository

    sale_return = await _ret_repo.get_with_items(db, return_id)
    if sale_return is None or sale_return.invoice_id != invoice_id:
        raise NotFoundException(f"Return {return_id} not found.")
    if sale_return.status != ReturnStatus.pending:
        raise ValidationException(
            f"Return is already '{sale_return.status.value}'."
        )

    old = audit_service.snapshot(sale_return)

    for ret_item in sale_return.return_items:
        await inventory_service.record_return_in(
            db,
            ret_item.item_id,
            ret_item.quantity,
            reference_id=return_id,
            created_by=approved_by,
        )

    # Approval only moves stock. Financial balance changes happen when
    # return payments are recorded (same as sale payment lifecycle).

    now = datetime.now(timezone.utc)
    await _ret_repo.approve(
        db, sale_return, approved_by=approved_by, approved_at=now
    )

    # Full return: mark sale as "returned"
    invoice_for_return = await _repo.get_with_items(db, invoice_id)
    total_approved_returns = sum(
        r.total_amount
        for r in await _ret_repo.list_for_invoice(db, invoice_id)
        if r.status == ReturnStatus.approved
    )
    if total_approved_returns >= invoice_for_return.total_amount:
        invoice_for_return.status = SaleStatus.returned
        db.add(invoice_for_return)

    await db.flush()
    approved = await _ret_repo.get_with_items(db, return_id)
    await audit_service.log(
        db, user_id=approved_by, action=AuditAction.UPDATE,
        table_name="sale_returns", record_id=return_id,
        old_values=old, new_values=audit_service.snapshot(approved),
    )
    return approved


async def get_return(
    db: AsyncSession, invoice_id: int, return_id: int
) -> SaleReturn:
    sale_return = await _ret_repo.get_with_items(db, return_id)
    if sale_return is None or sale_return.invoice_id != invoice_id:
        raise NotFoundException(f"Return {return_id} not found.")
    return sale_return


async def reject_return(
    db: AsyncSession,
    invoice_id: int,
    return_id: int,
    *,
    rejected_by: int,
    rejection_reason: str | None = None,
) -> SaleReturn:
    sale_return = await _ret_repo.get_with_items(db, return_id)
    if sale_return is None or sale_return.invoice_id != invoice_id:
        raise NotFoundException(f"Return {return_id} not found.")
    if sale_return.status != ReturnStatus.pending:
        raise ValidationException(
            f"Return is already '{sale_return.status.value}' and cannot be rejected."
        )
    old = audit_service.snapshot(sale_return)
    now = datetime.now(timezone.utc)
    await _ret_repo.reject(
        db, sale_return,
        rejected_by=rejected_by,
        rejected_at=now,
        rejection_reason=rejection_reason,
    )
    await db.flush()
    rejected = await _ret_repo.get_with_items(db, return_id)
    await audit_service.log(
        db, user_id=rejected_by, action=AuditAction.UPDATE,
        table_name="sale_returns", record_id=return_id,
        old_values=old, new_values=audit_service.snapshot(rejected),
    )
    return rejected


async def list_returns(
    db: AsyncSession, invoice_id: int
) -> list[SaleReturn]:
    invoice = await _repo.get_with_items(db, invoice_id)
    if invoice is None:
        raise NotFoundException(f"Sale invoice {invoice_id} not found.")
    return await _ret_repo.list_for_invoice(db, invoice_id)


async def list_approved_partial_returns(
    db: AsyncSession, *, limit: int = 50
) -> list[SaleReturn]:
    """List approved partial returns globally (for display in sales list)."""
    return await _ret_repo.list_approved_partial(db, limit=limit)


async def record_return_payment(
    db: AsyncSession,
    invoice_id: int,
    return_id: int,
    body,
    *,
    created_by: int,
) -> SaleReturn:
    """
    Record a refund payment to the customer for an approved return.
    Updates received_amount and settlement_status. Adjusts customer balance.
    """
    from app.models.sale import SaleReturnPayment
    from app.services import transaction_service
    from app.services.customer_service import _compute_new_balance
    from app.repositories.customer_repo import CustomerRepository
    from app.models.enums import TransactionType, ReferenceType

    sale_return = await _ret_repo.get_with_items(db, return_id)
    if sale_return is None or sale_return.invoice_id != invoice_id:
        raise NotFoundException(f"Return {return_id} not found.")
    if sale_return.status != ReturnStatus.approved:
        raise ValidationException("Can only record payments for approved returns.")

    refund_due = sale_return.refund_amount - sale_return.received_amount
    if body.amount > refund_due:
        raise ValidationException(
            f"Payment amount ({body.amount}) exceeds remaining refund due ({refund_due})."
        )

    # Record the payment row
    payment = SaleReturnPayment(
        return_id=return_id,
        amount=body.amount,
        payment_mode=body.payment_mode,
        reference_no=body.reference_no,
        note=body.note,
        created_by=created_by,
    )
    db.add(payment)

    # Update return settlement
    new_received = sale_return.received_amount + body.amount
    sale_return.received_amount = new_received
    if new_received >= sale_return.refund_amount:
        sale_return.settlement_status = "settled"
    else:
        sale_return.settlement_status = "partially_settled"
    db.add(sale_return)

    # Adjust customer balance
    customer_repo = CustomerRepository()
    invoice = await _repo.get_with_lock(db, invoice_id)
    customer = await customer_repo.get_with_lock(db, invoice.customer_id) if invoice.customer_id else None
    if customer and customer.is_active:
        new_balance, new_balance_type = _compute_new_balance(
            customer.balance, customer.balance_type, delta=-body.amount,
        )
        await customer_repo.apply_balance_update(
            db, customer, new_balance=new_balance, new_balance_type=new_balance_type,
        )

    # Post financial transaction
    invoice_for_ref = await _repo.get_with_items(db, invoice_id)
    await transaction_service.record_reference_transaction(
        db,
        payment_method=body.payment_mode,
        transaction_type=TransactionType.debit,
        reference_type=ReferenceType.sale_return,
        reference_id=return_id,
        amount=body.amount,
        description=f"{invoice_for_ref.invoice_no} — return refund payment ({body.payment_mode})",
        created_by=created_by,
    )

    await db.flush()
    return await _ret_repo.get_with_items(db, return_id)
