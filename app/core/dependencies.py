"""
Shared FastAPI dependencies: authentication and dynamic RBAC.

Design decisions:
- RBAC is fully dynamic: roles and their permission grants live in the
  database and are managed at runtime by users with the `roles` permissions.
- A user's effective permissions are resolved from the DB and cached in
  Redis (see app/core/rbac.py). The cache is versioned, so any role or
  permission change invalidates every cached entry at once.
- The JWT identifies the user (`sub`) only; permissions are NEVER trusted
  from the token — they are always resolved server-side per request.
- The Super Admin system role short-circuits to allow-all, so newly added
  permission keys are covered without re-granting.
- require_permission keeps a backward-compatible signature: it accepts
  either require_permission("module", "action") or the combined
  require_permission("module:action").
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
from app.core.rbac import SUPER_ADMIN_SLUG, get_user_permissions
from app.core.redis import get_redis
from app.core.security import decode_token
from app.models.auth import User

logger = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


# ── AuthContext ───────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AuthContext:
    """
    Carries both the authenticated User and the decoded token payload.

    Routes that only need the user inject get_current_user (→ User).
    Routes that also need payload fields (jti, exp) inject get_auth_context.
    """
    user: User
    payload: dict  # decoded JWT claims: sub, jti, exp, type, …


# ── Private core resolver — decoded exactly once per request ──────────────────

async def _resolve_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AuthContext:
    """
    Validate the Bearer token and return AuthContext(user, payload).

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

        # Check if user sessions were globally revoked (e.g. password changed)
        iat = payload.get("iat")
        revoked_before_raw = await redis.get(f"user:revoked_before:{sub}")
        if revoked_before_raw:
            if isinstance(revoked_before_raw, bytes):
                revoked_before = float(revoked_before_raw.decode())
            else:
                revoked_before = float(revoked_before_raw)
            if iat is None or iat < int(revoked_before):
                logger.info("access_token_revoked_by_password_change", user_id=sub)
                raise TokenExpiredError()
    except (TokenInvalidError, TokenExpiredError):
        raise
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
    """Return the full AuthContext (user + token payload)."""
    return ctx


# ── Permission helpers ────────────────────────────────────────────────────────

def is_super_admin(user: User) -> bool:
    """True if any of the user's roles is the Super Admin system role."""
    return any(
        role.slug == SUPER_ADMIN_SLUG and role.is_active for role in user.roles
    )


async def get_effective_permissions(
    user: User,
    db: AsyncSession,
    redis: Redis,
) -> set[str]:
    """Resolve the user's effective permission keys (Redis-cached)."""
    return await get_user_permissions(db, redis, user.id)


# ── require_permission ────────────────────────────────────────────────────────

def require_permission(module: str, action: str | None = None):
    """
    Dependency factory enforcing dynamic RBAC.

    Accepts either form:
        require_permission("suppliers", "delete")
        require_permission("suppliers:delete")

    Super Admins are always allowed. Everyone else must hold the resolved
    permission key in their effective (DB-backed, cached) permission set.

    Returns the authenticated User so routes don't need a second Depends.
    """
    permission_key = module if action is None else f"{module}:{action}"

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        redis: Redis = Depends(get_redis),
    ) -> User:
        if is_super_admin(current_user):
            return current_user

        perms = await get_user_permissions(db, redis, current_user.id)
        if permission_key not in perms:
            logger.info(
                "permission_denied",
                user_id=current_user.id,
                permission=permission_key,
            )
            raise PermissionDeniedError(
                f"Missing required permission: {permission_key}"
            )
        return current_user

    return _check
