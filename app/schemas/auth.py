"""
Pydantic schemas for the auth module.

Naming convention: {Entity}Request for input, {Entity}Out for output.
hashed_password is never included in any output schema.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Input schemas ─────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=150)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        cleaned = v.strip()
        if not all(c.isalnum() or c == "_" for c in cleaned):
            raise ValueError("Username may only contain letters, digits, and underscores.")
        return cleaned

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, v: str) -> str:
        return v.strip()


# ── Output schemas ────────────────────────────────────────────────────────────

class RoleBrief(BaseModel):
    """Compact role representation embedded in user payloads."""

    id: int
    name: str
    slug: str
    is_system_role: bool

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    last_login: datetime | None
    created_at: datetime
    roles: list[RoleBrief] = []

    model_config = {"from_attributes": True}


class MeOut(BaseModel):
    """
    Response for GET /auth/me — profile + assigned roles + the flattened,
    de-duplicated list of effective permission keys used by the frontend.
    """

    user: UserOut
    permissions: list[str]


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int  # seconds until access token expires


class LoginOut(BaseModel):
    """Combined token + user info returned on successful login."""

    tokens: TokenOut
    user: UserOut


class MessageOut(BaseModel):
    """Generic single-message response body (e.g. logout confirmation)."""

    message: str
