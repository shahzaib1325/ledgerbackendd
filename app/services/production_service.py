"""
Business logic for the Production module.

Lifecycle:
─────────────────────────────────────────────────────────────────────────────
  planned → in_progress → completed
                       ↘ cancelled

CREATE (planned):
  - Validate product item exists and is active (type=produced).
  - Validate each raw material item exists.
  - Compute line-level total_cost = required_quantity × unit_cost for materials.
  - Aggregate total_material_cost, total_labor_cost, total_other_cost on header.
  - No stock movement at creation.

START:
  - planned → in_progress.

COMPLETE:
  - in_progress → completed.
  - For each raw material line → inventory_service.record_production_out()
    (raw material stock leaves).
  - Record output quantity → inventory_service.record_production_in()
    (finished good stock enters).
  - Sets used_quantity = required_quantity on each raw material line.

CANCEL:
  - planned or in_progress → cancelled. No stock movement.

ADD LABOR / COST (while planned or in_progress):
  - Appends a labor or other-cost line and recomputes header totals.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.enums import AuditAction, ProductionStatus
from app.services import audit_service
from app.models.production import (
    ProductionCost,
    ProductionLabor,
    ProductionOrder,
    ProductionOutput,
)
from app.repositories.production_repo import (
    ProductionCostRepository,
    ProductionLaborRepository,
    ProductionOrderRepository,
    ProductionOutputRepository,
    ProductionRawMaterialRepository,
)
from app.schemas.production import (
    LaborCreate,
    ProductionCostCreate,
    ProductionOrderCreate,
    ProductionOrderUpdate,
    ProductionOutputCreate,
)

_repo = ProductionOrderRepository()
_mat_repo = ProductionRawMaterialRepository()
_labor_repo = ProductionLaborRepository()
_cost_repo = ProductionCostRepository()
_out_repo = ProductionOutputRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_status(
    order: ProductionOrder, *allowed: ProductionStatus, action: str
) -> None:
    if order.status not in allowed:
        raise ValidationException(
            f"Cannot {action} an order with status '{order.status.value}'."
        )


async def _recompute_header_costs(
    db: AsyncSession, order: ProductionOrder
) -> None:
    """Reload children and recompute the three cost buckets on the header."""
    order = await _repo.get_with_details(db, order.id)
    mat_total = sum(m.total_cost for m in order.raw_materials)
    labor_total = sum(lb.total_cost for lb in order.labor)
    other_total = sum(c.amount for c in order.costs)
    await _repo.update_costs(
        db, order,
        total_material_cost=mat_total,
        total_labor_cost=labor_total,
        total_other_cost=other_total,
    )


# ── Create ────────────────────────────────────────────────────────────────────

async def create_order(
    db: AsyncSession,
    body: ProductionOrderCreate,
    *,
    created_by: int,
) -> ProductionOrder:
    from app.repositories.inventory_repo import ItemRepository, UnitRepository

    item_repo = ItemRepository()

    # Validate product item
    product_item = await item_repo.get_or_404(db, body.product_item_id)
    if not product_item.is_active:
        raise NotFoundException(f"Item {body.product_item_id} not found.")

    # Check unique order_no
    existing = await _repo.get_by_order_no(db, body.order_no)
    if existing:
        raise ConflictException(f"Production order '{body.order_no}' already exists.")

    # Validate raw materials and compute material costs
    if not body.raw_materials:
        raise ValidationException("At least one raw material is required.")

    unit_repo = UnitRepository()
    mat_data = []
    total_material_cost = Decimal("0")
    for mat in body.raw_materials:
        mat_item = await item_repo.get_or_404(db, mat.item_id)
        if not mat_item.is_active:
            raise NotFoundException(f"Raw material item {mat.item_id} not found.")
        if mat.unit_id:
            await unit_repo.get_or_404(db, mat.unit_id)
        total_cost = mat.required_quantity * mat.unit_cost
        total_material_cost += total_cost
        mat_data.append({
            "item_id": mat.item_id,
            "unit_id": mat.unit_id,
            "required_quantity": mat.required_quantity,
            "used_quantity": Decimal("0"),
            "unit_cost": mat.unit_cost,
            "total_cost": total_cost,
        })

    # Compute labor costs
    labor_data = []
    total_labor_cost = Decimal("0")
    for lb in body.labor:
        lb_cost = lb.quantity_produced * lb.rate_per_unit
        total_labor_cost += lb_cost
        labor_data.append({
            "staff_id": lb.staff_id,
            "item_id": lb.item_id,
            "quantity_produced": lb.quantity_produced,
            "rate_per_unit": lb.rate_per_unit,
        })

    # Compute other costs
    cost_data = []
    total_other_cost = Decimal("0")
    for c in body.costs:
        total_other_cost += c.amount
        cost_data.append({
            "cost_type": c.cost_type,
            "amount": c.amount,
            "note": c.note,
        })

    order = await _repo.create(
        db,
        {
            "order_no": body.order_no,
            "product_item_id": body.product_item_id,
            "quantity_to_produce": body.quantity_to_produce,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "selling_price": body.selling_price,
            "status": ProductionStatus.planned,
            "total_material_cost": total_material_cost,
            "total_labor_cost": total_labor_cost,
            "total_other_cost": total_other_cost,
            "notes": body.notes,
            "created_by": created_by,
        },
    )

    for item in mat_data:
        item["order_id"] = order.id
    for item in labor_data:
        item["order_id"] = order.id
    for item in cost_data:
        item["order_id"] = order.id

    if mat_data:
        await _mat_repo.bulk_create(db, mat_data)
    if labor_data:
        await _labor_repo.bulk_create(db, labor_data)
    if cost_data:
        await _cost_repo.bulk_create(db, cost_data)

    await db.flush()
    await db.refresh(order, ["total_cost", "updated_at"])
    result = await _repo.get_with_details(db, order.id)
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="production_orders", record_id=order.id,
        new_values=audit_service.snapshot(result),
    )
    return result


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_order(db: AsyncSession, order_id: int) -> ProductionOrder:
    order = await _repo.get_with_details(db, order_id)
    if order is None:
        raise NotFoundException(f"Production order {order_id} not found.")
    return order


async def list_orders(
    db: AsyncSession,
    *,
    status=None,
    product_item_id: int | None = None,
    from_date=None,
    to_date=None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> tuple[list[ProductionOrder], int]:
    return await _repo.list_orders(
        db,
        status=status,
        product_item_id=product_item_id,
        from_date=from_date,
        to_date=to_date,
        skip=(page - 1) * limit,
        limit=limit,
        sort_by=sort_by,        # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


# ── Update (planned / in_progress only) ──────────────────────────────────────

async def update_order(
    db: AsyncSession, order_id: int, body: ProductionOrderUpdate, *, updated_by: int
) -> ProductionOrder:
    order = await _repo.get_with_details(db, order_id)
    if order is None:
        raise NotFoundException(f"Production order {order_id} not found.")
    _assert_status(
        order,
        ProductionStatus.planned, ProductionStatus.in_progress,
        action="update",
    )
    old = audit_service.snapshot(order)
    patch = body.model_dump(exclude_unset=True)
    await _repo.update(db, order, patch)
    updated = await _repo.get_with_details(db, order_id)
    await audit_service.log(
        db, user_id=updated_by, action=AuditAction.UPDATE,
        table_name="production_orders", record_id=order_id,
        old_values=old, new_values=audit_service.snapshot(updated),
    )
    return updated


# ── Status transitions ────────────────────────────────────────────────────────

async def start_order(db: AsyncSession, order_id: int, *, started_by: int) -> ProductionOrder:
    order = await _repo.get_with_details(db, order_id)
    if order is None:
        raise NotFoundException(f"Production order {order_id} not found.")
    _assert_status(order, ProductionStatus.planned, action="start")

    from app.repositories.inventory_repo import ItemRepository
    item_repo = ItemRepository()
    for mat in order.raw_materials:
        mat_item = await item_repo.get_or_404(db, mat.item_id)
        if mat_item.current_stock < mat.required_quantity:
            raise ValidationException(
                f"Cannot start order: Insufficient stock for material '{mat_item.name}'. "
                f"Required: {mat.required_quantity}, Available: {mat_item.current_stock}"
            )

    old = audit_service.snapshot(order)
    await _repo.set_status(db, order, status=ProductionStatus.in_progress)
    await db.flush()
    started = await _repo.get_with_details(db, order_id)
    await audit_service.log(
        db, user_id=started_by, action=AuditAction.UPDATE,
        table_name="production_orders", record_id=order_id,
        old_values=old, new_values=audit_service.snapshot(started),
    )
    return started


async def complete_order(
    db: AsyncSession,
    order_id: int,
    body: ProductionOutputCreate,
    *,
    completed_by: int,
) -> ProductionOrder:
    """
    Complete a production order.
    - Raw materials → production_out (stock leaves).
    - Finished good → production_in (stock enters).
    - Updates used_quantity on each material line.
    """
    from app.services import inventory_service

    order = await _repo.get_with_details(db, order_id)
    if order is None:
        raise NotFoundException(f"Production order {order_id} not found.")
    _assert_status(order, ProductionStatus.in_progress, action="complete")

    if body.quantity_produced > order.quantity_to_produce:
        raise ValidationException(
            f"Quantity produced ({body.quantity_produced}) cannot exceed the planned quantity "
            f"({order.quantity_to_produce})."
        )

    old = audit_service.snapshot(order)

    # Re-validate stock availability before consuming (stock may have changed since start)
    from app.repositories.inventory_repo import ItemRepository
    item_repo = ItemRepository()
    for mat in order.raw_materials:
        inv_item = await item_repo.get_or_404(db, mat.item_id)
        if inv_item.current_stock < mat.required_quantity:
            raise ValidationException(
                f"Cannot complete order: Insufficient stock for material '{inv_item.name}'. "
                f"Required: {mat.required_quantity}, Available: {inv_item.current_stock}"
            )

    # Consume raw materials from stock
    for mat in order.raw_materials:
        await inventory_service.record_production_out(
            db,
            mat.item_id,
            mat.required_quantity,
            reference_id=order_id,
            created_by=completed_by,
        )
        await _mat_repo.update_used(
            db, mat,
            used_quantity=mat.required_quantity,
            total_cost=mat.required_quantity * mat.unit_cost,
        )

    # Post expense transaction for overhead costs only.
    # Labor costs are accrued here but cash only leaves when staff salary
    # is disbursed — recording labor as a cash outflow now would double-count.
    from app.services import transaction_service
    from app.models.enums import TransactionType, ReferenceType as RefType
    if order.total_other_cost > Decimal("0"):
        await transaction_service.record_reference_transaction(
            db,
            payment_method="cash",
            transaction_type=TransactionType.debit,
            reference_type=RefType.expense,
            reference_id=order_id,
            amount=order.total_other_cost,
            description=f"{order.order_no} — overhead expenses",
            created_by=completed_by,
        )

    # Add finished good to stock
    await inventory_service.record_production_in(
        db,
        order.product_item_id,
        body.quantity_produced,
        reference_id=order_id,
        created_by=completed_by,
    )

    # Record output row
    output = await _out_repo.create(
        db,
        {
            "order_id": order_id,
            "item_id": order.product_item_id,
            "quantity_produced": body.quantity_produced,
            "produced_at": datetime.now(timezone.utc),
        },
    )
    await audit_service.log(
        db, user_id=completed_by, action=AuditAction.CREATE,
        table_name="production_outputs", record_id=output.id,
        new_values=audit_service.snapshot(output),
    )

    order.end_date = date.today()
    await _repo.set_status(db, order, status=ProductionStatus.completed)
    await db.flush()
    await db.refresh(order, ["total_cost", "updated_at"])
    completed = await _repo.get_with_details(db, order_id)
    await audit_service.log(
        db, user_id=completed_by, action=AuditAction.UPDATE,
        table_name="production_orders", record_id=order_id,
        old_values=old, new_values=audit_service.snapshot(completed),
    )
    return completed


async def cancel_order(db: AsyncSession, order_id: int, *, cancelled_by: int) -> ProductionOrder:
    order = await _repo.get_with_details(db, order_id)
    if order is None:
        raise NotFoundException(f"Production order {order_id} not found.")
    _assert_status(
        order,
        ProductionStatus.planned, ProductionStatus.in_progress,
        action="cancel",
    )
    old = audit_service.snapshot(order)
    await _repo.set_status(db, order, status=ProductionStatus.cancelled)
    await db.flush()
    cancelled = await _repo.get_with_details(db, order_id)
    await audit_service.log(
        db, user_id=cancelled_by, action=AuditAction.UPDATE,
        table_name="production_orders", record_id=order_id,
        old_values=old, new_values=audit_service.snapshot(cancelled),
    )
    return cancelled


# ── Add labor / cost lines ────────────────────────────────────────────────────

async def add_labor(
    db: AsyncSession,
    order_id: int,
    body: LaborCreate,
) -> ProductionLabor:
    order = await _repo.get_with_details(db, order_id)
    if order is None:
        raise NotFoundException(f"Production order {order_id} not found.")
    _assert_status(
        order,
        ProductionStatus.planned, ProductionStatus.in_progress,
        action="add labor to",
    )

    labor = await _labor_repo.create(
        db,
        {
            "order_id": order_id,
            "staff_id": body.staff_id,
            "item_id": body.item_id,
            "quantity_produced": body.quantity_produced,
            "rate_per_unit": body.rate_per_unit,
        },
    )
    await db.flush()
    await db.refresh(labor, ["total_cost"])
    await _recompute_header_costs(db, order)
    await db.flush()
    await audit_service.log(
        db, user_id=body.staff_id, action=AuditAction.CREATE,
        table_name="production_labor", record_id=labor.id,
        new_values=audit_service.snapshot(labor),
    )
    return labor


async def add_cost(
    db: AsyncSession,
    order_id: int,
    body: ProductionCostCreate,
    *,
    created_by: int,
) -> ProductionCost:
    order = await _repo.get_with_details(db, order_id)
    if order is None:
        raise NotFoundException(f"Production order {order_id} not found.")
    _assert_status(
        order,
        ProductionStatus.planned, ProductionStatus.in_progress,
        action="add cost to",
    )

    cost = await _cost_repo.create(
        db,
        {
            "order_id": order_id,
            "cost_type": body.cost_type,
            "amount": body.amount,
            "note": body.note,
        },
    )
    await _recompute_header_costs(db, order)
    await db.flush()
    await audit_service.log(
        db, user_id=created_by, action=AuditAction.CREATE,
        table_name="production_costs", record_id=cost.id,
        new_values=audit_service.snapshot(cost),
    )
    return cost
