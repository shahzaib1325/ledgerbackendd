# Module 09 — Production

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Production |
| Prefix | `/api/v1/production` |
| Files | `models/production.py`, `schemas/production.py`, `api/v1/endpoints/production.py`, `services/production_service.py`, `repositories/production_repo.py` |
| Dependencies | Inventory (raw material stock, finished goods), Staff (labor), Transactions (cost recording) |

The Production module tracks the complete manufacturing lifecycle — from planning through completion. It consumes raw materials (purchased items), applies labor and overhead costs, and produces finished goods (produced items). On completion, it updates inventory stock bidirectionally and calculates the actual unit cost of the finished product.

---

## 2. Functional Requirements

- **FR-PRD-01**: Create production orders specifying what to produce and in what quantity.
- **FR-PRD-02**: Define the bill of materials (raw materials required) per production order.
- **FR-PRD-03**: Attach labor entries (internal staff or external) with hours and rates.
- **FR-PRD-04**: Add other overhead costs (electricity, packaging, etc.) per order.
- **FR-PRD-05**: Start a production order — validates raw material availability.
- **FR-PRD-06**: Complete a production order — deducts raw materials, adds finished goods to stock.
- **FR-PRD-07**: Calculate total production cost and update the item's purchase_price (weighted avg).
- **FR-PRD-08**: Cancel a planned/in-progress order with explanation.
- **FR-PRD-09**: View production cost breakdown per order.

---

## 3. Status Flow

```
PLANNED ──► IN_PROGRESS ──► COMPLETED
   │              │
   └──► CANCELLED └──► CANCELLED
```

| Status | Description | Actions |
|--------|-------------|---------|
| `planned` | Order created, not started | Edit, Start, Cancel |
| `in_progress` | Materials reserved, production active | Add labor/costs, Complete, Cancel |
| `completed` | Stock updated, costing finalized | View only |
| `cancelled` | Abandoned, stock released | View only |

---

## 4. Data Models

### `ProductionOrder`
```python
class ProductionOrder(Base, TimestampMixin):
    __tablename__ = "production_orders"

    id: int
    order_no: str (UNIQUE)               # PRD-2026-00001
    product_item_id: int (FK → items)   # must be item_type = 'produced'
    quantity_to_produce: Decimal (> 0)
    start_date: date | None
    end_date: date | None
    status: ProductionStatus             # planned | in_progress | completed | cancelled
    total_material_cost: Decimal (default 0)
    total_labor_cost: Decimal (default 0)
    total_other_cost: Decimal (default 0)
    total_cost: Decimal (GENERATED: sum of above three)
    unit_cost: Decimal | None            # total_cost / quantity_produced
    notes: str | None
    created_by: int (FK → users)
```

### `ProductionRawMaterial`
```python
class ProductionRawMaterial(Base):
    __tablename__ = "production_raw_materials"

    id: int
    order_id: int (FK → production_orders, CASCADE)
    item_id: int (FK → items)           # must be item_type = 'purchased'
    unit_id: int (FK → units)
    required_quantity: Decimal (> 0)    # planned amount
    used_quantity: Decimal (default 0)  # actual (set on complete)
    unit_cost: Decimal (default 0)      # item.purchase_price at time of start
    total_cost: Decimal (default 0)     # used_quantity × unit_cost
```

### `ProductionLabor`
```python
class ProductionLabor(Base):
    __tablename__ = "production_labor"

    id: int
    order_id: int (FK → production_orders, CASCADE)
    staff_id: int | None (FK → staff)   # NULL = external/contractor labor
    description: str                     # e.g., "Machine Operator", "Packaging"
    hours: Decimal (> 0)
    rate_per_hour: Decimal (> 0)
    total_cost: Decimal (GENERATED: hours × rate_per_hour)
```

### `ProductionCost`
```python
class ProductionCost(Base):
    __tablename__ = "production_costs"

    id: int
    order_id: int (FK → production_orders, CASCADE)
    cost_type: str                       # "Electricity", "Packaging", "Equipment Rental"
    amount: Decimal (> 0)
    note: str | None
```

### `ProductionOutput`
```python
class ProductionOutput(Base):
    __tablename__ = "production_output"

    id: int
    order_id: int (FK → production_orders)
    item_id: int (FK → items)
    quantity_produced: Decimal (> 0)
    produced_at: datetime
```

---

## 5. Pydantic Schemas

```python
class ProductionRawMaterialCreate(BaseModel):
    item_id: int
    unit_id: int
    required_quantity: Decimal (> 0)

class ProductionLaborCreate(BaseModel):
    staff_id: int | None
    description: str (min 1)
    hours: Decimal (> 0)
    rate_per_hour: Decimal (> 0)

class ProductionCostCreate(BaseModel):
    cost_type: str
    amount: Decimal (> 0)
    note: str | None

class ProductionOrderCreate(BaseModel):
    product_item_id: int
    quantity_to_produce: Decimal (> 0)
    start_date: date | None
    end_date: date | None
    raw_materials: list[ProductionRawMaterialCreate] (min 1)
    labor: list[ProductionLaborCreate] (default [])
    other_costs: list[ProductionCostCreate] (default [])
    notes: str | None

class ProductionOrderUpdate(BaseModel):
    quantity_to_produce: Decimal | None
    start_date: date | None
    end_date: date | None
    raw_materials: list[ProductionRawMaterialCreate] | None
    labor: list[ProductionLaborCreate] | None
    other_costs: list[ProductionCostCreate] | None
    notes: str | None

class CompleteProductionIn(BaseModel):
    quantity_produced: Decimal (> 0)      # actual quantity produced (may differ from planned)
    actual_materials: list[ActualMaterialIn]  # actual quantities used per material

class ActualMaterialIn(BaseModel):
    raw_material_id: int
    used_quantity: Decimal (>= 0)

class ProductionOrderOut(BaseModel):
    id: int
    order_no: str
    product_item: ItemListOut
    quantity_to_produce: Decimal
    start_date: date | None
    end_date: date | None
    status: ProductionStatus
    raw_materials: list[ProductionRawMaterialOut]
    labor: list[ProductionLaborOut]
    other_costs: list[ProductionCostOut]
    total_material_cost: Decimal
    total_labor_cost: Decimal
    total_other_cost: Decimal
    total_cost: Decimal
    unit_cost: Decimal | None
    notes: str | None
    created_at: datetime

class ProductionCostSummaryOut(BaseModel):
    order_no: str
    product_name: str
    quantity_produced: Decimal
    total_cost: Decimal
    unit_cost: Decimal
    material_cost_pct: float
    labor_cost_pct: float
    overhead_cost_pct: float
    materials: list[dict]
    labor: list[dict]
    other_costs: list[dict]
```

---

## 6. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/production` | read | List production orders |
| POST | `/production` | write | Create production order |
| GET | `/production/{id}` | read | Order detail with full breakdown |
| PUT | `/production/{id}` | write | Edit planned order |
| POST | `/production/{id}/start` | write | Start production |
| POST | `/production/{id}/complete` | write | Complete order + update stock |
| POST | `/production/{id}/cancel` | write | Cancel order |
| GET | `/production/{id}/cost-summary` | read | Cost breakdown report |
| POST | `/production/{id}/labor` | write | Add labor entry (in_progress only) |
| DELETE | `/production/{id}/labor/{labor_id}` | write | Remove labor entry |
| POST | `/production/{id}/costs` | write | Add overhead cost |
| DELETE | `/production/{id}/costs/{cost_id}` | write | Remove overhead cost |

### Query Parameters (GET /production)
| Param | Type | Description |
|-------|------|-------------|
| `status` | enum | Filter by status |
| `product_item_id` | int | Filter by product |
| `from_date`, `to_date` | date | Filter by start_date |
| `page`, `limit` | int | |

---

## 7. Start Production — Workflow

```python
async def start(db, order_id, actor_id):
    async with db.begin():
        order = await production_repo.get_or_404(db, order_id)

        if order.status != ProductionStatus.PLANNED:
            raise InvalidStatusTransitionError("Only planned orders can be started")

        # Validate all raw materials have sufficient stock
        for material in order.raw_materials:
            item = await inventory_repo.get_or_404(db, material.item_id)
            if item.current_stock < material.required_quantity:
                raise InsufficientStockError(
                    f"Item '{item.name}' needs {material.required_quantity} "
                    f"but only {item.current_stock} available"
                )
            # Snapshot the current purchase_price for costing
            material.unit_cost = item.purchase_price

        # NOTE: Stock is NOT deducted on start — only on complete.
        # (Allows production to run while stock continues to be received)
        # If strict reservation is needed, deduct here and reverse on cancel.

        order.status = ProductionStatus.IN_PROGRESS
        order.start_date = order.start_date or date.today()
```

---

## 8. Complete Production — Workflow

This is the most complex operation, involving bidirectional stock changes:

```python
async def complete(db, order_id, complete_in: CompleteProductionIn, actor_id):
    async with db.begin():
        order = await production_repo.get_or_404(db, order_id)

        if order.status != ProductionStatus.IN_PROGRESS:
            raise InvalidStatusTransitionError()

        # Step 1: Deduct raw materials (actual quantities used)
        total_material_cost = Decimal(0)
        for actual in complete_in.actual_materials:
            material = get_material_by_id(order, actual.raw_material_id)
            material.used_quantity = actual.used_quantity
            material.total_cost = actual.used_quantity * material.unit_cost
            total_material_cost += material.total_cost

            await inventory_service.deduct_stock(
                db, material.item_id, actual.used_quantity,
                movement_type=MovementType.PRODUCTION_OUT,
                reference_type='production', reference_id=order.id,
                actor_id=actor_id
            )

        # Step 2: Add finished goods to stock
        await inventory_service.add_stock(
            db, order.product_item_id, complete_in.quantity_produced,
            movement_type=MovementType.PRODUCTION_IN,
            reference_type='production', reference_id=order.id,
            actor_id=actor_id
        )

        # Step 3: Update cost totals
        order.total_material_cost = total_material_cost
        order.total_labor_cost = sum(l.total_cost for l in order.labor)
        order.total_other_cost = sum(c.amount for c in order.other_costs)

        # Step 4: Calculate unit cost
        if complete_in.quantity_produced > 0:
            order.unit_cost = order.total_cost / complete_in.quantity_produced

        # Step 5: Update product item's purchase_price (weighted average)
        product_item = await inventory_repo.get_or_404(db, order.product_item_id)
        existing_stock = product_item.current_stock - complete_in.quantity_produced  # before this addition
        if existing_stock + complete_in.quantity_produced > 0:
            new_avg = (
                (existing_stock * product_item.purchase_price) +
                (complete_in.quantity_produced * order.unit_cost)
            ) / (existing_stock + complete_in.quantity_produced)
            product_item.purchase_price = round(new_avg, 2)

        # Step 6: Record production output
        output = ProductionOutput(
            order_id=order.id,
            item_id=order.product_item_id,
            quantity_produced=complete_in.quantity_produced,
            produced_at=datetime.utcnow()
        )
        db.add(output)

        # Step 7: Update status
        order.status = ProductionStatus.COMPLETED
        order.end_date = date.today()
```

---

## 9. Cancel Production — Workflow

```python
async def cancel(db, order_id, reason, actor_id):
    async with db.begin():
        order = await production_repo.get_or_404(db, order_id)

        if order.status not in (ProductionStatus.PLANNED, ProductionStatus.IN_PROGRESS):
            raise InvalidStatusTransitionError("Cannot cancel completed production")

        # If stock was deducted on start (if reservation approach used):
        # Restore deducted materials here.
        # In the non-reservation approach: no stock to reverse.

        order.status = ProductionStatus.CANCELLED
        order.notes = f"{order.notes or ''}\nCancelled: {reason}"
```

---

## 10. Order Number Generation

Same pattern as sales invoices:
```
PRD-{YEAR}-{SEQUENCE:05d}
Example: PRD-2026-00042
```

Uses a PostgreSQL sequence `production_order_seq_{year}`, reset annually.

---

## 11. Business Rules

| Rule | Detail |
|------|--------|
| Product item type | `product_item_id` must have `item_type = 'produced'` |
| Raw material item type | Each raw material `item_id` must have `item_type = 'purchased'` |
| Edit restriction | Only `planned` orders can be edited; `in_progress` allows adding labor/costs only |
| Stock check on start | All raw materials must have sufficient stock |
| Actual vs planned | `used_quantity` can differ from `required_quantity` (over/under-use) |
| Cancel completed | Not allowed — production history is immutable |
| Unit cost | Calculated as `total_cost / quantity_produced`; updates item.purchase_price |
| Labor staff | Staff link is optional — supports external/contract labor |

---

## 12. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Order not found | `NotFoundException` | 404 |
| Start non-planned | `InvalidStatusTransitionError` | 409 |
| Insufficient raw material | `InsufficientStockError` | 409 |
| Complete non-in-progress | `InvalidStatusTransitionError` | 409 |
| Cancel completed | `InvalidStatusTransitionError` | 409 |
| Wrong item type for product | `ValidationException` | 422 |
| Wrong item type for material | `ValidationException` | 422 |
| Quantity ≤ 0 | `ValidationException` | 422 |

---

## 13. Inter-Module Interactions

| Interaction | Direction | Description |
|-------------|-----------|-------------|
| `ProductionService.start()` → `InventoryService` | Outbound | Stock check on raw materials |
| `ProductionService.complete()` → `InventoryService.deduct_stock()` | Outbound | Deduct raw materials |
| `ProductionService.complete()` → `InventoryService.add_stock()` | Outbound | Add finished goods |
| `ReportService` → `ProductionRepository` | Inbound | Production report |
