from fastapi import APIRouter

from app.api.v1.endpoints import (
    audit,
    auth,
    customers,
    dashboard,
    inventory,
    permissions,
    production,
    purchases,
    rbac_logs,
    reports,
    roles,
    sales,
    search,
    staff,
    suppliers,
    transactions,
    users,
    whatsapp,
)

api_v1_router = APIRouter()

api_v1_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_v1_router.include_router(suppliers.router, prefix="/suppliers", tags=["Suppliers"])
api_v1_router.include_router(customers.router, prefix="/customers", tags=["Customers"])
api_v1_router.include_router(inventory.router, prefix="/inventory", tags=["Inventory"])
api_v1_router.include_router(purchases.router, prefix="/purchases", tags=["Purchases"])
api_v1_router.include_router(sales.router, prefix="/sales", tags=["Sales"])
api_v1_router.include_router(transactions.router, prefix="", tags=["Transactions"])
api_v1_router.include_router(staff.router, prefix="/staff", tags=["Staff"])
api_v1_router.include_router(production.router, prefix="/production", tags=["Production"])
api_v1_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_v1_router.include_router(audit.router, prefix="/audit-logs", tags=["Audit"])
api_v1_router.include_router(dashboard.router, prefix="", tags=["Dashboard"])
api_v1_router.include_router(search.router, prefix="", tags=["Search"])
api_v1_router.include_router(whatsapp.router, prefix="/whatsapp", tags=["WhatsApp"])

# ── RBAC / Administration ─────────────────────────────────────────────────────
api_v1_router.include_router(roles.router, prefix="/roles", tags=["RBAC - Roles"])
api_v1_router.include_router(
    permissions.router, prefix="/permissions", tags=["RBAC - Permissions"]
)
api_v1_router.include_router(users.router, prefix="/users", tags=["RBAC - Users"])
api_v1_router.include_router(
    rbac_logs.router, prefix="/rbac-logs", tags=["RBAC - Activity Logs"]
)
