# Module 01 — Auth & Users

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Auth & Users |
| Prefix | `/api/v1/auth`, `/api/v1/users` |
| Files | `models/auth.py`, `schemas/auth.py`, `api/v1/endpoints/auth.py`, `api/v1/endpoints/users.py`, `services/auth_service.py`, `repositories/auth_repo.py` |
| Dependencies | Redis (token blacklist), bcrypt (password hashing) |

This module handles all authentication (who you are) and authorization setup (what you can do). It is the foundation every other module depends on.

---

## 2. Functional Requirements

- **FR-AUTH-01**: Users must authenticate with username + password to receive JWT tokens.
- **FR-AUTH-02**: Access tokens expire after 15 minutes; refresh tokens allow obtaining new access tokens without re-login.
- **FR-AUTH-03**: Logout must invalidate the current session (token blacklisting).
- **FR-AUTH-04**: Admin users can create, deactivate, and reset passwords for other users.
- **FR-AUTH-05**: Each user has exactly one role (`admin`, `manager`, `staff`).
- **FR-AUTH-06**: Role permissions define per-module read/write/delete access via a hardcoded static matrix in `app/core/dependencies.py`. There is no runtime permission management UI or `roles_permissions` database table in v1.

---

## 3. Data Models

### `User`
```python
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: int (PK)
    username: str (unique, max 50)
    email: str (unique, max 255)
    hashed_password: str
    full_name: str (max 150)
    role: UserRole (enum: admin | manager | staff)
    is_active: bool (default True)
    last_login: datetime | None
```

### `TokenBlacklist`
```python
class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id: int (PK)
    jti: str (unique)          # JWT ID from token payload
    expires_at: datetime       # Auto-cleanup: delete when past this
```

---

## 4. Pydantic Schemas

```python
# Input schemas
class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str (min 3, max 50, alphanumeric + underscore)
    email: EmailStr
    full_name: str (min 1, max 150)
    password: str (min 8, max 128)
    role: UserRole

class UserUpdate(BaseModel):
    full_name: str | None
    email: EmailStr | None
    role: UserRole | None
    is_active: bool | None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str (min 8, max 128)

# Output schemas
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int            # seconds until access token expires

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    last_login: datetime | None
    created_at: datetime
    # hashed_password NEVER included
```

---

## 5. API Endpoints

### Auth Endpoints

#### `POST /auth/login`
- **Auth:** Public
- **Request:** `LoginRequest`
- **Response:** `TokenResponse`
- **Logic:**
  1. Fetch user by username (case-insensitive)
  2. Verify password with bcrypt
  3. If invalid: check rate limit → increment fail counter → return 401
  4. If valid: reset fail counter, update `last_login`, generate tokens
  5. Return `TokenResponse`
- **Rate Limit:** 10/minute per IP

#### `POST /auth/refresh`
- **Auth:** Public (refresh token in body)
- **Request:** `{ "refresh_token": "..." }`
- **Response:** `TokenResponse`
- **Logic:**
  1. Decode and validate refresh token
  2. Check JTI not blacklisted
  3. Issue new access + refresh token (rotation)
  4. Blacklist old refresh token JTI
- **Rate Limit:** 30/minute per IP

#### `POST /auth/logout`
- **Auth:** Required
- **Request:** Empty body
- **Response:** `{ "success": true, "data": { "message": "Logged out successfully" } }`
- **Logic:** Extract JTI from access token → add to blacklist with TTL

#### `GET /auth/me`
- **Auth:** Required
- **Response:** `UserOut`
- **Logic:** Return `current_user` from dependency

#### `PUT /auth/me/password`
- **Auth:** Required
- **Request:** `ChangePasswordRequest`
- **Logic:**
  1. Verify `current_password` against stored hash
  2. Validate new password rules
  3. Check not in last 5 passwords
  4. Hash and save new password
  5. Blacklist current access token (force re-login)

---

### User Management Endpoints (Admin Only)

#### `GET /users`
- **Auth:** admin
- **Query Params:** `page`, `limit`, `search`, `role`, `is_active`
- **Response:** Paginated `UserOut` list

#### `POST /users`
- **Auth:** admin
- **Request:** `UserCreate`
- **Response:** `UserOut` (201)
- **Logic:** Hash password, save user, seed default permissions

#### `GET /users/{id}`
- **Auth:** admin
- **Response:** `UserOut`

#### `PUT /users/{id}`
- **Auth:** admin
- **Request:** `UserUpdate`
- **Response:** `UserOut`
- **Logic:** Cannot change own role; cannot deactivate own account

#### `POST /users/{id}/reset-password`
- **Auth:** admin
- **Response:** `{ "temp_password": "..." }`
- **Logic:** Generate secure random temp password, hash and save, return plaintext once

---

## 6. Service Layer — `AuthService`

```python
class AuthService:
    async def login(db, redis, username, password) -> TokenResponse
    async def refresh(db, redis, refresh_token) -> TokenResponse
    async def logout(redis, access_token) -> None
    async def create_user(db, user_in: UserCreate, actor_id) -> User
    async def update_user(db, user_id, user_in: UserUpdate, actor_id) -> User
    async def change_password(db, redis, user, current_pw, new_pw) -> None
    async def reset_password(db, user_id) -> str  # returns temp password
```

> **Removed from v1:** `get_permissions()` and `upsert_permissions()` are not implemented. RBAC is a static hardcoded matrix — not DB-driven.

---

## 7. Business Rules

| Rule | Detail |
|------|--------|
| Username uniqueness | Case-insensitive; `Ali` and `ali` are the same |
| Password hashing | bcrypt with 12 rounds; never stored plain |
| Self-protection | Admin cannot deactivate or demote their own account |
| Static RBAC | Permissions are hardcoded in `app/core/dependencies.py`. No DB table. No runtime editing. |
| Login audit | Every successful and failed login is logged |
| Token rotation | Refresh tokens are single-use; each refresh issues a new pair |

---

## 8. Static Permission Matrix

Permissions are hardcoded in `app/core/dependencies.py`. The `require_permission(module, action)` dependency resolves access purely from the user's `role` enum value — no database lookup is performed.

```python
# app/core/dependencies.py
PERMISSION_MATRIX = {
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
```

To change permissions in v1, edit this dict and redeploy. No migration required. If runtime-configurable permissions are needed in v2, this dict can be migrated to a `roles_permissions` table without any API contract changes.

---

## 9. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Wrong credentials | `InvalidCredentialsError` | 401 |
| Expired token | `TokenExpiredError` | 401 |
| Blacklisted token | `TokenInvalidError` | 401 |
| Inactive user | `TokenInvalidError` | 401 |
| Insufficient role | `ForbiddenException` | 403 |
| Username taken | `ConflictException` | 409 |
| Email taken | `ConflictException` | 409 |
| Reused password | `ValidationException` | 422 |

---

## 10. Security Notes

- Same 401 message for both "user not found" and "wrong password" — prevents user enumeration
- Brute force: after 5 failed logins from same IP, block for 15 minutes (Redis TTL)
- `hashed_password` is excluded from all SQLAlchemy `select()` when returning `UserOut`
- Token JTI stored in Redis on blacklist (not DB) for O(1) lookup performance

### Redis Unavailability — Fail-Open Policy

If Redis is unreachable during `get_current_user()`, the system **fails open**: the blacklist check is skipped and the request proceeds based on token signature and expiry alone. Rate limiting is also suspended.

**Rationale:** Access tokens expire in 15 minutes. The exploitable window (a legitimately-logged-out token being reused) is bounded by that TTL. Total API downtime during a Redis outage is a worse outcome than the bounded security risk of fail-open.

**Implementation requirement:** `get_current_user()` must wrap the Redis blacklist check in a `try/except` for `ConnectionError` / `TimeoutError` and log a warning rather than propagating the exception as a 503.

```python
# app/core/dependencies.py
async def get_current_user(token: str = ..., redis: Redis = Depends(get_redis)) -> User:
    payload = decode_jwt(token)              # raises 401 if invalid/expired
    try:
        if await redis.get(f"blacklist:jti:{payload['jti']}"):
            raise TokenInvalidError()
    except (RedisConnectionError, RedisTimeoutError):
        logger.warning("redis_unavailable_blacklist_check_skipped", jti=payload["jti"])
        # fail-open: proceed without blacklist check
    user = await user_repo.get_or_404(db, int(payload["sub"]))
    if not user.is_active:
        raise TokenInvalidError()
    return user
```
