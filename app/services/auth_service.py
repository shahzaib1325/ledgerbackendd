"""
Auth service — core authentication business logic.

Responsibilities:
  login_user     — verify credentials, issue token pair
  register_user  — create a new staff-level user
  refresh_tokens — validate refresh token, rotate and issue new pair
  logout_user    — blacklist a JTI in Redis

No FastAPI imports. No RBAC. No route logic.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    ConflictException,
    InvalidCredentialsError,
    TokenInvalidError,
)
from app.core.security import (
    create_token_pair,
    decode_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.models.auth import User
from app.models.enums import UserRole

logger = structlog.get_logger(__name__)


# ── Value object returned by login_user ───────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # seconds


# ── Service functions ─────────────────────────────────────────────────────────

async def login_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
) -> tuple[TokenPair, User]:
    """
    Authenticate a user by email + password.

    Returns (TokenPair, User) on success.
    Raises InvalidCredentialsError for any failure — wrong email, wrong
    password, or inactive account — using the same message to prevent
    user enumeration (SECURITY.md §1.2, 01_AUTH.md §10).
    """
    result = await db.execute(
        select(User).where(User.email == email.lower())
    )
    user: User | None = result.scalar_one_or_none()

    # Deliberate: same exception for "not found" and "wrong password".
    if user is None or not verify_password(password, user.hashed_password):
        logger.info("login_failed", email=email)
        raise InvalidCredentialsError()

    if not user.is_active:
        # Treat inactive account the same as bad credentials — don't reveal status.
        logger.info("login_failed_inactive", user_id=user.id)
        raise InvalidCredentialsError()

    access_token, _access_jti, refresh_token, _refresh_jti = create_token_pair(
        subject=user.id,
        username=user.username,
        role=user.role.value,
    )

    logger.info("login_success", user_id=user.id, role=user.role.value)

    return TokenPair(access_token=access_token, refresh_token=refresh_token), user


async def register_user(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    full_name: str,
    role: UserRole = UserRole.staff,
) -> User:
    """
    Create a new user account.

    - Username is stored and matched case-insensitively (lowercased on save).
    - Password is validated against policy then hashed.
    - Default role is 'staff'; callers (admin endpoints) may pass a different role.
    - Raises ConflictException if username or email is already taken.
    """
    username_lower = username.lower()

    # Only one admin may exist (enforced at DB level by partial unique index
    # uq_one_admin; this check provides a clear application-level error first).
    if role == UserRole.admin:
        existing_admin = await db.execute(
            select(User.id).where(User.role == UserRole.admin)
        )
        if existing_admin.scalar_one_or_none() is not None:
            raise ConflictException(
                "An admin user already exists. Only one admin is allowed.",
                code="CONFLICT",
                field="role",
            )

    # Uniqueness checks — separate queries so we can give a specific field error.
    existing_username = await db.execute(
        select(User.id).where(User.username == username_lower)
    )
    if existing_username.scalar_one_or_none() is not None:
        raise ConflictException(
            f"Username '{username}' is already taken.",
            code="CONFLICT",
            field="username",
        )

    existing_email = await db.execute(
        select(User.id).where(User.email == email.lower())
    )
    if existing_email.scalar_one_or_none() is not None:
        raise ConflictException(
            f"Email '{email}' is already registered.",
            code="CONFLICT",
            field="email",
        )

    # Password policy (raises ValueError → callers should convert to ValidationException)
    validate_password_policy(password, username=username_lower)

    user = User(
        username=username_lower,
        email=email.lower(),
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()   # assigns user.id without committing — caller owns the transaction
    await db.refresh(user)

    logger.info("user_registered", user_id=user.id, role=user.role.value)
    return user


async def refresh_tokens(
    db: AsyncSession,
    redis: Redis,
    *,
    refresh_token: str,
) -> TokenPair:
    """
    Validate a refresh token and issue a new access + refresh token pair.

    - Confirms token type is "refresh".
    - Checks JTI not blacklisted in Redis (fail-open if Redis unavailable).
    - Loads user from DB and confirms still active.
    - Blacklists the consumed refresh token (rotation — one-time use).
    - Returns a fresh TokenPair.
    """
    from datetime import datetime, timezone
    from jose import ExpiredSignatureError, JWTError

    try:
        payload = decode_token(refresh_token)
    except ExpiredSignatureError:
        raise TokenInvalidError()
    except JWTError:
        raise TokenInvalidError()

    if payload.get("type") != "refresh":
        raise TokenInvalidError()

    jti: str | None = payload.get("jti")
    sub: str | None = payload.get("sub")
    exp: int | None = payload.get("exp")

    if not jti or not sub or not exp:
        raise TokenInvalidError()

    try:
        is_blacklisted = await redis.exists(f"blacklist:jti:{jti}")
        if is_blacklisted:
            raise TokenInvalidError()
    except Exception:
        pass  # fail-open — same policy as _resolve_auth

    result = await db.execute(select(User).where(User.id == int(sub)))
    user: User | None = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise TokenInvalidError()

    # Blacklist the consumed refresh token (rotation — one-time use)
    ttl = max(0, int(exp - datetime.now(timezone.utc).timestamp()))
    await redis.set(f"blacklist:jti:{jti}", "1", ex=ttl)

    access_token, _access_jti, new_refresh_token, _refresh_jti = create_token_pair(
        subject=user.id,
        username=user.username,
        role=user.role.value,
    )

    logger.info("tokens_refreshed", user_id=user.id)
    return TokenPair(access_token=access_token, refresh_token=new_refresh_token)


async def logout_user(
    redis: Redis,
    *,
    jti: str,
    ttl_seconds: int,
) -> None:
    """
    Blacklist a token JTI in Redis.

    Key: blacklist:jti:{jti}
    TTL: remaining lifetime of the token in seconds (caller computes from exp claim).

    No error is raised if Redis is unavailable — the caller (logout endpoint)
    may choose to swallow the exception and return 200 anyway since the
    access token will naturally expire within 15 minutes.
    """
    await redis.set(f"blacklist:jti:{jti}", "1", ex=ttl_seconds)
    logger.info("token_blacklisted", jti=jti, ttl_seconds=ttl_seconds)
