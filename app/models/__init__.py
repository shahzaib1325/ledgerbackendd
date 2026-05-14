# Re-export all ORM models so Alembic autodiscovery finds them via:
#   target_metadata = Base.metadata  (in alembic/env.py)
#
# Import order matters: Base first, then enums, then tables with no FKs,
# then tables that reference them. SQLAlchemy resolves string-based FKs
# lazily, but keeping a logical order avoids confusion.

from app.models.base import AuditMixin, Base, TimestampMixin  # noqa: F401
from app.models.enums import (  # noqa: F401
    AccountType,
    AttendanceStatus,
    AuditAction,
    BalanceType,
    ItemType,
    MovementType,
    NotificationType,
    PaymentMode,
    PaymentType,
    ProductionStatus,
    PurchaseStatus,
    ReferenceType,
    ReturnStatus,
    SaleStatus,
    StaffType,
    TransactionType,
    UserRole,
)

# ── Auth ──────────────────────────────────────────────────────────────────────
from app.models.auth import RolePermission, TokenBlacklist, User  # noqa: F401

# ── Transactions (imported early — many other models FK into accounts) ────────
from app.models.transaction import Account, Transaction, Transfer  # noqa: F401

# ── Inventory ─────────────────────────────────────────────────────────────────
from app.models.inventory import Category, Item, StockMovement, Unit  # noqa: F401

# ── Suppliers ─────────────────────────────────────────────────────────────────
from app.models.supplier import Supplier, SupplierPayment  # noqa: F401

# ── Customers ─────────────────────────────────────────────────────────────────
from app.models.customer import Customer, CustomerPayment  # noqa: F401

# ── Purchases ─────────────────────────────────────────────────────────────────
from app.models.purchase import (  # noqa: F401
    Purchase,
    PurchaseItem,
    PurchasePayment,
    PurchaseReturn,
    PurchaseReturnItem,
)

# ── Sales ─────────────────────────────────────────────────────────────────────
from app.models.sale import (  # noqa: F401
    Notification,
    SaleInvoice,
    SaleItem,
    SalePayment,
    SaleReturn,
    SaleReturnItem,
)

# ── Staff ─────────────────────────────────────────────────────────────────────
from app.models.staff import (  # noqa: F401
    Advance,
    Attendance,
    SalaryStructure,
    Staff,
    StaffPayment,
)

# ── Production ────────────────────────────────────────────────────────────────
from app.models.production import (  # noqa: F401
    ProductionCost,
    ProductionLabor,
    ProductionOrder,
    ProductionOutput,
    ProductionRawMaterial,
)

# ── Audit ─────────────────────────────────────────────────────────────────────
from app.models.audit import AuditLog  # noqa: F401

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    "AuditMixin",
    # Enums
    "UserRole", "PaymentMode", "PaymentType", "BalanceType", "ItemType",
    "MovementType", "PurchaseStatus", "SaleStatus", "ReturnStatus", "StaffType",
    "AttendanceStatus", "AccountType", "TransactionType", "ReferenceType",
    "ProductionStatus", "NotificationType", "AuditAction",
    # Auth
    "User", "RolePermission", "TokenBlacklist",
    # Transactions
    "Account", "Transaction", "Transfer",
    # Inventory
    "Unit", "Category", "Item", "StockMovement",
    # Suppliers
    "Supplier", "SupplierPayment",
    # Customers
    "Customer", "CustomerPayment",
    # Purchases
    "Purchase", "PurchaseItem", "PurchasePayment", "PurchaseReturn", "PurchaseReturnItem",
    # Sales
    "SaleInvoice", "SaleItem", "SalePayment", "SaleReturn", "SaleReturnItem", "Notification",
    # Staff
    "Staff", "SalaryStructure", "Attendance", "StaffPayment", "Advance",
    # Production
    "ProductionOrder", "ProductionRawMaterial", "ProductionLabor", "ProductionCost", "ProductionOutput",
    # Audit
    "AuditLog",
]
