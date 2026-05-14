"""
Auth endpoints — login, register, logout.

All business logic lives in app/services/auth_service.py.
Routes are thin: validate input → call service → wrap in envelope.

JWT is decoded exactly once per request by _resolve_auth (via get_auth_context).
No direct decode_token() calls here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import AuthContext, get_auth_context
from app.core.exceptions import ValidationException
from app.core.redis import get_redis
from app.schemas.auth import (
    LoginOut,
    LoginRequest,
    MessageOut,
    RefreshRequest,
    RegisterRequest,
    TokenOut,
    UserOut,
)
from app.schemas.common import SuccessResponse
from app.services import auth_service

router = APIRouter()

# Annotated dependency aliases — declared once, reused across endpoints.
DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
AuthCtxDep = Annotated[AuthContext, Depends(get_auth_context)]


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    summary="Login with email and password",
)
async def login(body: LoginRequest, db: DbDep) -> SuccessResponse[LoginOut]:
    token_pair, user = await auth_service.login_user(
        db, email=body.email, password=body.password
    )
    return SuccessResponse(
        data=LoginOut(
            tokens=TokenOut(
                access_token=token_pair.access_token,
                refresh_token=token_pair.refresh_token,
                token_type=token_pair.token_type,
                expires_in=token_pair.expires_in,
            ),
            user=UserOut.model_validate(user),
        )
    )


# ── POST /auth/register ───────────────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(body: RegisterRequest, db: DbDep) -> SuccessResponse[UserOut]:
    try:
        user = await auth_service.register_user(
            db,
            username=body.username,
            email=str(body.email),
            password=body.password,
            full_name=body.full_name,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise ValidationException(str(exc), field="password") from exc

    return SuccessResponse(data=UserOut.model_validate(user))


# ── POST /auth/refresh ───────────────────────────────────────────────────────

@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh(
    body: RefreshRequest,
    db: DbDep,
    redis: RedisDep,
) -> SuccessResponse[TokenOut]:
    token_pair = await auth_service.refresh_tokens(
        db, redis, refresh_token=body.refresh_token
    )
    return SuccessResponse(
        data=TokenOut(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
        )
    )


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Invalidate the current access token",
)
async def logout(ctx: AuthCtxDep, redis: RedisDep) -> SuccessResponse[MessageOut]:
    jti: str = ctx.payload["jti"]
    exp: int = ctx.payload["exp"]
    ttl = max(0, int(exp - datetime.now(timezone.utc).timestamp()))

    await auth_service.logout_user(redis, jti=jti, ttl_seconds=ttl)

    return SuccessResponse(data=MessageOut(message="Logged out successfully."))
