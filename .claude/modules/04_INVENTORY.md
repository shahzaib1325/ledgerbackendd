# Module 04 — Inventory

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Inventory |
| Prefix | `/api/v1/inventory`, `/api/v1/units`, `/api/v1/categories` |
| Files | `models/inventory.py`, `schemas/inventory.py`, `api/v1/endpoints/inventory.py`, `services/inventory_service.py`, `repositories/inventory_repo.py` |
| Dependencies | Used by Purchases, Sales, Production modules |

Inventory tracks all items (raw materials, finished goods, merchandise), their current stock levels, categories, and units of measurement. Stock is never directly edited — every change goes through `stock_movements` for full traceability.

---

## 2. Functional Requirements

- **FR-INV-01**: Manage items with name, category, unit, type (purchased/produced), pricing.
- **FR-INV-02**: Track real-time stock levels; stock can never go below zero.
- **FR-INV-03**: Record every stock change as a `stock_movement` with full context.
- **FR-INV-04**: Allow manual stock adjustments with a reason note.
- **FR-INV-05**: Set reorder levels per item; alert when stock falls below threshold.
- **FR-INV-06**: Manage units of measurement (kg, pcs, litres, etc.).
- **FR-INV-07**: Manage categories with optional parent-child hierarchy.
- **FR-INV-08**: View the complete stock movement history per item.

---

## 3. Data Models

### `Unit`
```python
class Unit(Base):
    __tablename__ = "units"

    id: int
    name: str (unique, max 50)            # "Kilogram"
    abbreviation: str (unique, max 10)    # "kg"
    is_active: bool (default True)
    created_at: datetime
```

### `Category`
```python
class Category(Base):
    __tablename__ = "categories"

    id: int
    name: str (max 100)
    parent_id: int | None (FK → categories, self-referential)
    is_active: bool (default True)
    created_at: datetime
    # Unique: (name, parent_id)
```

### `Item`
```python
class Item(Base, TimestampMixin):
    __tablename__ = "items"

    id: int
    name: str (max 200)
    sku: str | None (unique)
    category_id: int | None (FK → categories)
    unit_id: int (FK → units, NOT NULL)
    item_type: ItemType                   # purchased | produced
    current_stock: Decimal (>= 0, default 0)
    # ↑ PERFORMANCE-CACHE COLUMN. Never write to this column directly.
    # It is updated exclusively inside InventoryService.add_stock() /
    # deduct_stock(), within the same DB transaction that inserts the
    # stock_movements row. On-hand quantity is always reconstructable
    # via SUM(stock_movements.quantity) — current_stock is a cached
    # result of that sum to avoid a full-table scan on every read.
    reorder_level: Decimal (default 0)
    sale_price: Decimal (default 0)
    purchase_price: Decimal (default 0)   # weighted average cost
    is_active: bool (default True)
    created_by: int (FK → users)
```

### `StockMovement`
```python
class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: int
    item_id: int (FK → items)
    movement_type: MovementType           # purchase_in | sale_out | production_in |
                                          # production_out | return_in | return_out | adjustment
    quantity: Decimal                     # positive for inflow, negative for outflow
    stock_before: Decimal                 # snapshot before this movement
    stock_after: Decimal                  # snapshot after this movement
    reference_type: str | None            # 'purchase' | 'sale' | 'production' | 'adjustment'
    reference_id: int | None              # FK to source record
    note: str | None
    moved_at: datetime
    created_by: int (FK → users)
```

---

## 4. Pydantic Schemas

```python
class UnitCreate(BaseModel):
    name: str (max 50)
    abbreviation: str (max 10)

class UnitOut(BaseModel):
    id: int
    name: str
    abbreviation: str
    is_active: bool

class CategoryCreate(BaseModel):
    name: str
    parent_id: int | None

class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    parent_name: str | None               # resolved for display
    is_active: bool

class ItemCreate(BaseModel):
    name: str
    sku: str | None
    category_id: int | None
    unit_id: int
    item_type: ItemType
    reorder_level: Decimal (default 0, >= 0)
    sale_price: Decimal (default 0, >= 0)
    purchase_price: Decimal (default 0, >= 0)
    initial_stock: Decimal (default 0, >= 0)   # creates an 'adjustment' movement on create

class ItemUpdate(BaseModel):
    name: str | None
    sku: str | None
    category_id: int | None
    unit_id: int | None
    reorder_level: Decimal | None
    sale_price: Decimal | None
    purchase_price: Decimal | None
    # current_stock NOT updatable here

class ItemOut(BaseModel):
    id: int
    name: str
    sku: str | None
    category: CategoryOut | None
    unit: UnitOut
    item_type: ItemType
    current_stock: Decimal
    reorder_level: Decimal
    sale_price: Decimal
    purchase_price: Decimal
    stock_value: Decimal                  # = current_stock × purchase_price
    is_low_stock: bool                    # = current_stock < reorder_level
    is_active: bool
    created_at: datetime

class StockAdjustmentCreate(BaseModel):
    quantity: Decimal (cannot be 0)       # positive = add, negative = remove
    note: str (required for adjustments)

class StockMovementOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    movement_type: MovementType
    quantity: Decimal
    stock_before: Decimal
    stock_after: Decimal
    reference_type: str | None
    reference_id: int | None
    note: str | None
    moved_at: datetime
```

---

## 5. API Endpoints

### Units
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/units` | read | List all units |
| POST | `/units` | write | Create unit |
| GET | `/units/{id}` | read | Get unit |
| PUT | `/units/{id}` | write | Update unit |
| DELETE | `/units/{id}` | delete | Soft delete |

### Categories
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/categories` | read | List all (tree structure option) |
| POST | `/categories` | write | Create category |
| GET | `/categories/{id}` | read | Get category |
| PUT | `/categories/{id}` | write | Update |
| DELETE | `/categories/{id}` | delete | Soft delete |

### Items
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/inventory/items` | read | List items (paginated + filters) |
| POST | `/inventory/items` | write | Create item |
| GET | `/inventory/items/{id}` | read | Item detail |
| PUT | `/inventory/items/{id}` | write | Update item |
| DELETE | `/inventory/items/{id}` | delete | Soft delete |
| POST | `/inventory/items/{id}/adjust` | write | Manual stock adjustment |
| GET | `/inventory/items/{id}/movements` | read | Stock movement history |
| GET | `/inventory/stock-movements` | read | All movements (global) |
| GET | `/inventory/low-stock` | read | Items below reorder level |

### Query Parameters (GET /inventory/items)
| Param | Type | Description |
|-------|------|-------------|
| `search` | string | Name / SKU search |
| `category_id` | int | Filter by category |
| `item_type` | purchased\|produced | Filter by type |
| `low_stock` | bool | Only below reorder level |
| `is_active` | bool | Default true |
| `page`, `limit` | int | Pagination |

### Query Parameters (GET /inventory/stock-movements)
| Param | Type | Description |
|-------|------|-------------|
| `item_id` | int | Filter by item |
| `movement_type` | enum | Filter by movement type |
| `reference_type` | string | Filter by source (purchase, sale, etc.) |
| `from_date`, `to_date` | date | Date range |
| `page`, `limit` | int | Pagination |

---

## 6. Service Layer — `InventoryService`

```python
class InventoryService:

    async def create_item(db, item_in: ItemCreate, actor_id) -> Item:
        """
        1. Validate unit_id and category_id exist
        2. Create item record with current_stock = initial_stock
        3. If initial_stock > 0: record stock_movement (type: adjustment)
        4. Audit log
        """

    async def add_stock(db, item_id, quantity, movement_type, reference_type, reference_id, note, actor_id) -> StockMovement:
        """
        Internal method called by PurchaseService, ProductionService, SaleService (returns).
        1. SELECT FOR UPDATE on item
        2. Create StockMovement record (stock_before, stock_after)
        3. Update item.current_stock += quantity
        4. Audit log
        All in caller's DB transaction
        """

    async def deduct_stock(db, item_id, quantity, movement_type, reference_type, reference_id, note, actor_id) -> StockMovement:
        """
        Internal method called by SaleService, ProductionService.
        1. SELECT FOR UPDATE on item
        2. Check current_stock >= quantity → raise InsufficientStockError if not
        3. Create StockMovement (negative quantity)
        4. Update item.current_stock -= quantity
        All in caller's DB transaction
        """

    async def adjust_stock(db, item_id, adjustment: StockAdjustmentCreate, actor_id) -> StockMovement:
        """
        Manual adjustment endpoint handler.
        Calls add_stock (if positive) or deduct_stock (if negative).
        movement_type = 'adjustment'
        reference_type = None
        """

    async def get_low_stock_items(db) -> list[Item]:
        """
        Returns items where current_stock < reorder_level AND reorder_level > 0
        """
```

---

## 7. Stock Movement Rules

| Operation | Movement Type | Quantity Sign | Triggered By |
|-----------|--------------|---------------|--------------|
| Purchase confirmed | `purchase_in` | + (positive) | PurchaseService |
| Sale confirmed | `sale_out` | - (negative) | SaleService |
| Production start (reserve) | `production_out` | - (negative) | ProductionService |
| Production complete (output) | `production_in` | + (positive) | ProductionService |
| Purchase return approved | `return_out` | - (negative) | PurchaseService |
| Sale return approved | `return_in` | + (positive) | SaleService |
| Manual adjustment | `adjustment` | + or - | InventoryService |

**Critical Rule:** `current_stock` is a cached column updated exclusively via `add_stock()` or `deduct_stock()`. No other code path may touch this column. The update to `current_stock` and the insert of the `stock_movements` row always happen inside the same `async with db.begin()` transaction block — they are never split. The `stock_movements` table is the source of truth; `current_stock` is a derived cache that exists purely for read performance.

---

## 8. Business Rules

| Rule | Detail |
|------|--------|
| Non-negative stock | DB `CHECK (current_stock >= 0)` + service-level check before deduction |
| Stock before deduct | Always verify `current_stock >= quantity` before any deduction |
| Concurrent updates | Use `SELECT ... FOR UPDATE` on item row for all stock changes |
| Unit deletion | Cannot delete a unit if any item uses it |
| Category deletion | Cannot delete if any item belongs to it (even inactive items) |
| Item deletion | Cannot delete if it has any stock movements (historical) |
| SKU uniqueness | Optional field; if provided, must be globally unique |
| Item type immutable | `item_type` cannot be changed after creation (affects accounting) |

---

## 9. Weighted Average Cost Update

When a purchase is confirmed, `item.purchase_price` is updated using the weighted average formula:

```python
new_avg_cost = (
    (item.current_stock * item.purchase_price) + (purchase_quantity * purchase_unit_price)
) / (item.current_stock + purchase_quantity)

item.purchase_price = round(new_avg_cost, 2)
```

This gives an accurate cost for the stock valuation report.

---

## 10. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Item not found | `NotFoundException` | 404 |
| Insufficient stock | `InsufficientStockError` | 409 |
| Unit in use (delete) | `ConflictException` | 409 |
| Category in use (delete) | `ConflictException` | 409 |
| Duplicate SKU | `ConflictException` | 409 |
| Invalid unit_id | `ValidationException` | 422 |
| Adjustment quantity = 0 | `ValidationException` | 422 |
