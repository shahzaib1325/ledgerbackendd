"""
Shared FastAPI dependencies: authentication and RBAC.

Design decisions (from SECURITY.md §2.3 and 01_AUTH.md §8):
- RBAC uses a hardcoded PERMISSION_MATRIX resolved from user.role.
  Zero DB lookups per request.  If runtime-configurable permissions
  are needed in v2, the dict can be migrated to roles_permissions without
  any API contract changes.
- Redis blacklist check uses fail-open: if Redis is unreachable the
  check is skipped and the request proceeds (token TTL bounds the risk).
- JWT is decoded exactly ONCE per request inside _resolve_auth.
  Both get_current_user and get_auth_context delegate to it; FastAPI's
  per-request dependency cache ensures _resolve_auth runs only once even
  when multiple dependants exist in the same route.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import (
    PermissionDeniedError,
    TokenExpiredError,
    TokenInvalidError,
    UnauthorizedException,
)
from app.core.redis import get_redis
from app.core.security import decode_token
from app.models.auth import User

logger = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

# ── Static RBAC permission matrix ────────────────────────────────────────────
# Source: 01_AUTH.md §8.  Keys: role → module → action → bool.
# action is one of: "read", "write", "delete"

PERMISSION_MATRIX: dict[str, dict[str, dict[str, bool]]] = {
    "admin": {
        "users":        {"read": True,  "write": True,  "delete": True},
        "suppliers":    {"read": True,  "write": True,  "delete": True},
        "customers":    {"read": True,  "write": True,  "delete": True},
        "inventory":    {"read": True,  "write": True,  "delete": True},
        "purchases":    {"read": True,  "write": True,  "delete": True},
        "sales":        {"read": True,  "write": True,  "delete": True},
        "staff":        {"read": True,  "write": True,  "delete": True},
        "transactions": {"read": True,  "write": True,  "delete": True},
        "production":   {"read": True,  "write": True,  "delete": True},
        "reports":      {"read": True,  "write": False, "delete": False},
        "audit":        {"read": True,  "write": False, "delete": False},
    },
    "manager": {
        "users":        {"read": False, "write": False, "delete": False},
        "suppliers":    {"read": True,  "write": True,  "delete": False},
        "customers":    {"read": True,  "write": True,  "delete": False},
        "inventory":    {"read": True,  "write": True,  "delete": False},
        "purchases":    {"read": True,  "write": True,  "delete": False},
        "sales":        {"read": True,  "write": True,  "delete": False},
        "staff":        {"read": True,  "write": True,  "delete": False},
        "transactions": {"read": True,  "write": True,  "delete": False},
        "production":   {"read": True,  "write": True,  "delete": False},
        "reports":      {"read": True,  "write": False, "delete": False},
        "audit":        {"read": True,  "write": False, "delete": False},
    },
    "staff": {
        "users":        {"read": False, "write": False, "delete": False},
        "suppliers":    {"read": True,  "write": False, "delete": False},
        "customers":    {"read": True,  "write": False, "delete": False},
        "inventory":    {"read": True,  "write": False, "delete": False},
        "purchases":    {"read": True,  "write": True,  "delete": False},
        "sales":        {"read": True,  "write": True,  "delete": False},
        "staff":        {"read": True,  "write": False, "delete": False},
        "transactions": {"read": True,  "write": False, "delete": False},
        "production":   {"read": True,  "write": True,  "delete": False},
        "reports":      {"read": False, "write": False, "delete": False},
    },
}


# ── AuthContext ───────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AuthContext:
    """
    Carries both the authenticated User and the decoded token payload.

    Routes that only need the user inject get_current_user (→ User).
    Routes that also need payload fields (jti, exp) inject get_auth_context.
    """
    user: User
    payload: dict  # decoded JWT claims: sub, jti, exp, role, username, type


# ── Private core resolver — decoded exactly once per request ──────────────────

async def _resolve_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AuthContext:
    """
    Validate the Bearer token and return AuthContext(user, payload).

    Steps (SECURITY.md §1.5):
      1. Require Authorization: Bearer header
      2. Decode JWT — ExpiredSignatureError → 401 TOKEN_EXPIRED
                       JWTError            → 401 TOKEN_INVALID
      3. Verify token type is "access"
      4. Check JTI not in Redis blacklist  (fail-open if Redis unavailable)
      5. Load User from DB by sub claim
      6. Verify user.is_active
    """
    if credentials is None:
        raise UnauthorizedException()

    try:
        payload = decode_token(credentials.credentials)
    except ExpiredSignatureError:
        raise TokenExpiredError()
    except JWTError:
        raise TokenInvalidError()

    if payload.get("type") != "access":
        raise TokenInvalidError()

    jti: str | None = payload.get("jti")
    sub: str | None = payload.get("sub")

    if not jti or not sub:
        raise TokenInvalidError()

    try:
        is_blacklisted = await redis.exists(f"blacklist:jti:{jti}")
        if is_blacklisted:
            raise TokenInvalidError()
    except (RedisConnectionError, RedisTimeoutError):
        logger.warning("redis_unavailable_blacklist_check_skipped", jti=jti)
        # Fail-open: 15-min TTL bounds the exploitable window.

    result = await db.execute(select(User).where(User.id == int(sub)))
    user: User | None = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise TokenInvalidError()

    return AuthContext(user=user, payload=payload)


# ── Public dependencies ───────────────────────────────────────────────────────

def get_current_user(
    ctx: AuthContext = Depends(_resolve_auth),
) -> User:
    """Return the authenticated User. JWT decoded once via _resolve_auth."""
    return ctx.user


def get_auth_context(
    ctx: AuthContext = Depends(_resolve_auth),
) -> AuthContext:
    """
    Return the full AuthContext (user + token payload).

    Use this instead of get_current_user when the route needs payload
    fields such as jti or exp (e.g. logout).
    """
    return ctx


# ── require_permission ────────────────────────────────────────────────────────

def require_permission(module: str, action: str):
    """
    Dependency factory enforcing RBAC via the static PERMISSION_MATRIX.

    action must be one of: "read", "write", "delete"

    Usage:
        @router.delete("/{id}")
        async def delete_supplier(
            id: int,
            current_user: User = Depends(require_permission("suppliers", "delete")),
        ):

    Returns the authenticated User so routes don't need a second Depends call.
    """

    def _check(current_user: User = Depends(get_current_user)) -> User:
        role_key = current_user.role.value
        allowed = (
            PERMISSION_MATRIX
            .get(role_key, {})
            .get(module, {})
            .get(action, False)
        )
        if not allowed:
            logger.info(
                "permission_denied",
                user_id=current_user.id,
                role=role_key,
                module=module,
                action=action,
            )
            raise PermissionDeniedError()
        return current_user

    return _check
