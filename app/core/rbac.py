"""
RBAC core — permission registry, seeding, and permission resolution cache.

Design:
- PERMISSION_REGISTRY is the single source of truth for what permissions
  exist. Permissions map 1-to-1 with real API capabilities; admins never
  invent permission keys — they only group existing ones into roles.
- Permission keys use the "module:action" format.
- A user's effective permissions = de-duplicated union of every assigned
  role's permissions. Resolved from the DB and cached in Redis, keyed by a
  global version counter so any role/permission change invalidates all
  cached entries at once (RBAC writes are rare; reads are hot).
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

SUPER_ADMIN_SLUG = "super-admin"
SUPER_ADMIN_NAME = "Super Admin"

# Permission cache settings
_VERSION_KEY = "rbac:version"
_CACHE_TTL = 300  # seconds — safety net; explicit version bump is primary


# ── Permission registry ───────────────────────────────────────────────────────
# Each entry: (module, action, description). permission_key is "module:action".
# Actions: read / write / delete  — matching the existing require_permission
# call sites across all endpoints (no endpoint rewrites needed).

_RAW: list[tuple[str, str, str]] = [
    ("dashboard",    "read",   "View the dashboard"),
    ("suppliers",    "read",   "View suppliers"),
    ("suppliers",    "write",  "Create and edit suppliers"),
    ("suppliers",    "delete", "Delete suppliers"),
    ("customers",    "read",   "View customers"),
    ("customers",    "write",  "Create and edit customers"),
    ("customers",    "delete", "Delete customers"),
    ("inventory",    "read",   "View inventory"),
    ("inventory",    "write",  "Create and edit inventory"),
    ("inventory",    "delete", "Delete inventory"),
    ("purchases",    "read",   "View purchases"),
    ("purchases",    "write",  "Create and edit purchases"),
    ("purchases",    "delete", "Delete purchases"),
    ("sales",        "read",   "View sales"),
    ("sales",        "write",  "Create and edit sales"),
    ("sales",        "delete", "Delete sales"),
    ("production",   "read",   "View production"),
    ("production",   "write",  "Create and edit production"),
    ("production",   "delete", "Delete production"),
    ("staff",        "read",   "View staff"),
    ("staff",        "write",  "Create and edit staff"),
    ("staff",        "delete", "Delete staff"),
    ("transactions", "read",   "View transactions"),
    ("transactions", "write",  "Create and edit transactions"),
    ("transactions", "delete", "Delete transactions"),
    ("reports",      "read",   "View and export reports"),
    ("audit",        "read",   "View audit logs"),
    ("users",        "read",   "View users"),
    ("users",        "write",  "Create and edit users"),
    ("users",        "delete", "Delete users"),
    ("roles",        "read",   "View roles and permissions"),
    ("roles",        "write",  "Create and edit roles and assign permissions"),
    ("roles",        "delete", "Delete roles"),
    ("settings",     "read",   "View settings"),
    ("settings",     "write",  "Edit settings"),
]

PERMISSION_REGISTRY: list[dict[str, str]] = [
    {
        "module": module,
        "action": action,
        "permission_key": f"{module}:{action}",
        "description": description,
    }
    for module, action, description in _RAW
]

ALL_PERMISSION_KEYS: frozenset[str] = frozenset(
    p["permission_key"] for p in PERMISSION_REGISTRY
)

# Human-friendly module labels for the frontend permission grid.
MODULE_LABELS: dict[str, str] = {
    "dashboard": "Dashboard",
    "suppliers": "Suppliers",
    "customers": "Customers",
    "inventory": "Inventory",
    "purchases": "Purchases",
    "sales": "Sales",
    "production": "Production",
    "staff": "Staff",
    "transactions": "Transactions",
    "reports": "Reports",
    "audit": "Audit Logs",
    "users": "Users",
    "roles": "Roles & Permissions",
    "settings": "Settings",
}


# ── Permission seeding (idempotent) ───────────────────────────────────────────

async def sync_permissions(db: AsyncSession) -> dict[str, int]:
    """
    Upsert PERMISSION_REGISTRY into the permissions table.

    - New permission keys are inserted.
    - Existing keys have module/action/description refreshed.
    - Nothing is deleted (removing a key is a deliberate code/migration step).

    Returns {"created": n, "updated": n}. Caller owns the transaction.
    """
    from app.models.rbac import Permission

    result = await db.execute(select(Permission))
    existing = {p.permission_key: p for p in result.scalars().all()}

    created = updated = 0
    for entry in PERMISSION_REGISTRY:
        key = entry["permission_key"]
        row = existing.get(key)
        if row is None:
            db.add(
                Permission(
                    module=entry["module"],
                    action=entry["action"],
                    permission_key=key,
                    description=entry["description"],
                    is_system_permission=True,
                )
            )
            created += 1
        else:
            if (
                row.module != entry["module"]
                or row.action != entry["action"]
                or row.description != entry["description"]
            ):
                row.module = entry["module"]
                row.action = entry["action"]
                row.description = entry["description"]
                updated += 1

    await db.flush()
    logger.info("permissions_synced", created=created, updated=updated)
    return {"created": created, "updated": updated}


# ── Permission resolution + Redis cache ───────────────────────────────────────

async def resolve_user_permissions(db: AsyncSession, user_id: int) -> set[str]:
    """Load the de-duplicated union of permission keys for a user from the DB."""
    from app.models.rbac import Permission, Role, RolePermission, UserRole

    stmt = (
        select(Permission.permission_key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.is_active.is_(True))
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def get_user_permissions(
    db: AsyncSession,
    redis: Redis,
    user_id: int,
) -> set[str]:
    """
    Return a user's effective permission keys, using a versioned Redis cache.

    Fail-safe: on any Redis error the DB is queried directly (never skipped —
    permissions are security-sensitive).
    """
    version = "1"
    cache_key: str | None = None
    try:
        version = (await redis.get(_VERSION_KEY)) or "1"
        cache_key = f"rbac:perms:v{version}:{user_id}"
        cached = await redis.smembers(cache_key)
        if cached:
            # Sentinel for "resolved but empty" so we don't re-query every time.
            return set() if cached == {"__none__"} else set(cached)
    except RedisError:
        logger.warning("rbac_cache_read_failed", user_id=user_id)

    perms = await resolve_user_permissions(db, user_id)

    if cache_key is not None:
        try:
            members = perms or {"__none__"}
            await redis.sadd(cache_key, *members)
            await redis.expire(cache_key, _CACHE_TTL)
        except RedisError:
            logger.warning("rbac_cache_write_failed", user_id=user_id)

    return perms


async def invalidate_permission_cache(redis: Redis) -> None:
    """
    Invalidate every cached permission set by bumping the global version.

    Called after any role create/update/delete, permission grant change, or
    user-role assignment. O(1) and avoids tracking which users are affected.
    """
    try:
        await redis.incr(_VERSION_KEY)
        logger.info("rbac_cache_invalidated")
    except RedisError:
        logger.warning("rbac_cache_invalidate_failed")
