"""
Pydantic schemas for the RBAC / administration module.

Naming convention: {Entity}Request for input, {Entity}Out for output.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ── Permissions ───────────────────────────────────────────────────────────────

class PermissionOut(BaseModel):
    id: int
    module: str
    action: str
    permission_key: str
    description: str | None
    is_system_permission: bool

    model_config = {"from_attributes": True}


class PermissionGroupOut(BaseModel):
    """Permissions of one module, grouped for the frontend permission grid."""

    module: str
    label: str
    permissions: list[PermissionOut]


# ── Roles ─────────────────────────────────────────────────────────────────────

class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str | None = Field(None, max_length=255)
    is_active: bool = True
    permission_keys: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Role name cannot be empty.")
        return cleaned


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    description: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    # When provided, replaces the role's permission grants atomically in the
    # same request. Omit (null) to leave permissions unchanged.
    permission_keys: list[str] | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Role name cannot be empty.")
        return cleaned


class RolePermissionsRequest(BaseModel):
    """Full replacement of a role's permission grants."""

    permission_keys: list[str] = Field(default_factory=list)


class RoleCloneRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str | None = Field(None, max_length=255)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Role name cannot be empty.")
        return cleaned


class RoleListOut(BaseModel):
    """Compact role row for the roles table."""

    id: int
    name: str
    slug: str
    description: str | None
    is_system_role: bool
    is_active: bool
    permission_count: int
    user_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleDetailOut(BaseModel):
    """Full role detail including its granted permissions."""

    id: int
    name: str
    slug: str
    description: str | None
    is_system_role: bool
    is_active: bool
    permissions: list[PermissionOut]
    user_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Users / role assignment ───────────────────────────────────────────────────

class UserRoleBrief(BaseModel):
    id: int
    name: str
    slug: str
    is_system_role: bool

    model_config = {"from_attributes": True}


class UserListOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    last_login: datetime | None
    created_at: datetime
    roles: list[UserRoleBrief]

    model_config = {"from_attributes": True}


class AssignUserRolesRequest(BaseModel):
    """Full replacement of a user's role assignments."""

    role_ids: list[int] = Field(default_factory=list)


class CreateUserRequest(BaseModel):
    """Admin-side user creation, with optional initial role assignment."""

    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=150)
    role_ids: list[int] = Field(default_factory=list)

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


class UserStatusRequest(BaseModel):
    is_active: bool


class UserPermissionsOut(BaseModel):
    user_id: int
    roles: list[UserRoleBrief]
    permissions: list[str]


# ── Activity log ──────────────────────────────────────────────────────────────

class RbacActivityLogOut(BaseModel):
    id: int
    user_id: int | None
    action: str
    module: str
    target_type: str | None
    target_id: int | None
    old_value: dict | None
    new_value: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
