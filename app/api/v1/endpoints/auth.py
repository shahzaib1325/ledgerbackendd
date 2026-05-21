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
from app.core.dependencies import AuthContext, get_auth_context, get_current_user
from app.core.exceptions import ValidationException
from app.core.rbac import get_user_permissions
from app.core.redis import get_redis
from app.models.auth import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginOut,
    LoginRequest,
    LogoutRequest,
    MeOut,
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
CurrentUserDep = Annotated[User, Depends(get_current_user)]


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
    summary="Invalidate the current access token and optionally a refresh token",
)
async def logout(
    body: LogoutRequest,
    ctx: AuthCtxDep,
    redis: RedisDep,
) -> SuccessResponse[MessageOut]:
    # Invalidate current access token
    access_jti: str = ctx.payload["jti"]
    access_exp: int = ctx.payload["exp"]
    access_ttl = max(0, int(access_exp - datetime.now(timezone.utc).timestamp()))

    await auth_service.logout_user(redis, jti=access_jti, ttl_seconds=access_ttl)

    # Invalidate optional refresh token
    if body.refresh_token:
        try:
            from app.core.security import decode_token
            refresh_payload = decode_token(body.refresh_token)
            if refresh_payload.get("type") == "refresh":
                refresh_jti = refresh_payload.get("jti")
                refresh_exp = refresh_payload.get("exp")
                if refresh_jti and refresh_exp:
                    refresh_ttl = max(0, int(refresh_exp - datetime.now(timezone.utc).timestamp()))
                    await auth_service.logout_user(redis, jti=refresh_jti, ttl_seconds=refresh_ttl)
        except Exception:
            pass  # fail-silent on refresh token decoding issues during logout

    return SuccessResponse(data=MessageOut(message="Logged out successfully."))


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Get authenticated user profile, roles and effective permissions",
)
async def get_me(
    user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> SuccessResponse[MeOut]:
    permissions = await get_user_permissions(db, redis, user.id)
    return SuccessResponse(
        data=MeOut(
            user=UserOut.model_validate(user),
            permissions=sorted(permissions),
        )
    )


# ── POST /auth/change-password ────────────────────────────────────────────────

@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change own password",
)
async def change_password(
    body: ChangePasswordRequest,
    user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> SuccessResponse[MessageOut]:
    try:
        await auth_service.change_password_user(
            db,
            redis,
            user=user,
            current_password=body.current_password,
            new_password=body.new_password,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise ValidationException(str(exc), field="new_password") from exc

    return SuccessResponse(data=MessageOut(message="Password changed successfully."))
