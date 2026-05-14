# SmartLedger — Security Specification

## 1. Authentication

### 1.1 JWT Token Strategy

SmartLedger uses a dual-token JWT strategy:

| Token | Lifetime | Storage | Purpose |
|-------|----------|---------|---------|
| Access Token | 15 minutes | Client memory (not localStorage) | Authenticate API requests |
| Refresh Token | 7 days | HttpOnly cookie or secure client storage | Obtain new access tokens |

**Access Token Payload:**
```json
{
  "sub": "42",
  "username": "ali_manager",
  "role": "manager",
  "jti": "550e8400-e29b-41d4-a716-446655440000",
  "iat": 1713261200,
  "exp": 1713262100
}
```

**Signing Algorithm:** `HS256` with a secret key of minimum 32 characters (recommended 64+ char random string).

### 1.2 Login Flow

```
1. Client sends POST /auth/login { username, password }
2. Server fetches user by username
3. Server verifies password against bcrypt hash (passlib)
4. If invalid → 401 with INVALID_CREDENTIALS (same message for both wrong user and wrong pass — no enumeration)
5. If valid → generate access token + refresh token
6. Log successful login (update users.last_login)
7. Return tokens
```

**Brute Force Protection:**
- Login endpoint rate-limited to 10 requests/minute per IP (slowapi)
- After 5 consecutive failed attempts from same IP → 15-minute block (tracked in Redis)

### 1.3 Token Refresh Flow

```
1. Client sends POST /auth/refresh { refresh_token }
2. Server decodes token, extracts JTI
3. Check JTI not in Redis blacklist
4. Check token not expired
5. Issue new access token + new refresh token (rotation)
6. Blacklist old refresh token JTI in Redis (TTL = refresh token lifetime)
7. Return new tokens
```

### 1.4 Logout Flow

```
1. Client sends POST /auth/logout with Authorization header
2. Server extracts JTI from access token
3. Add JTI to Redis blacklist with TTL = remaining token lifetime
4. Return 200 OK
```

### 1.5 Token Validation (Every Request)

```
1. Extract Authorization header → parse Bearer token
2. Decode JWT (verify signature + expiry)
3. Check JTI not in Redis blacklist  ← fail-open if Redis unavailable (see note)
4. Load user from DB by `sub` claim
5. Check user.is_active = true
6. Attach user to request context
→ Any failure returns 401
```

**Redis Unavailability — Fail-Open:** If Redis is unreachable at step 3, the blacklist check is skipped and the request proceeds. This is a deliberate availability-over-security trade-off: the exploitable risk window is bounded by the 15-minute access token TTL. A Redis outage must not cause a complete API outage. The implementation wraps the Redis call in a `try/except (ConnectionError, TimeoutError)` and logs a warning. Rate limiting (step implied before step 1) is also suspended during Redis unavailability.

---

## 2. Authorization (RBAC)

### 2.1 Role Definitions

| Role | Description | Typical User |
|------|-------------|--------------|
| `admin` | Full system access, user management | Business owner |
| `manager` | All operational modules, no user management | Operations manager |
| `staff` | Restricted to assigned modules (read + limited write) | Data entry operator |

### 2.2 Permission Matrix

| Module | Admin | Manager | Staff |
|--------|-------|---------|-------|
| Users | R/W/D | — | — |
| Suppliers | R/W/D | R/W | R |
| Customers | R/W/D | R/W | R |
| Inventory | R/W/D | R/W | R |
| Purchases | R/W/D | R/W | R/W |
| Sales | R/W/D | R/W | R/W |
| Staff | R/W/D | R/W | R |
| Transactions | R/W/D | R/W | R |
| Production | R/W/D | R/W | R/W |
| Reports | R | R | — |

**R** = Read, **W** = Write (create + update), **D** = Delete (soft)

### 2.3 Implementation — Static Hardcoded Matrix (v1)

**Decision: Static enum RBAC. No `roles_permissions` database table.**

The permission matrix is hardcoded in `app/core/dependencies.py` as a Python dict (`PERMISSION_MATRIX`). The `require_permission()` dependency resolves access purely from `current_user.role` — zero database lookups. See `modules/01_AUTH.md` Section 8 for the full matrix.

```python
# app/core/dependencies.py
def require_permission(module: str, action: str):
    async def checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        allowed = PERMISSION_MATRIX.get(current_user.role, {}).get(module, {}).get(action, False)
        if not allowed:
            raise ForbiddenException()
        return current_user
    return checker

# Usage on route:
@router.delete("/suppliers/{id}")
async def delete_supplier(
    id: int,
    current_user = Depends(require_permission("suppliers", "delete")),
    ...
):
```

**Why static over dynamic:** For an SME with three fixed roles, the permission matrix is stable. A DB-backed table adds a query per request (or cache invalidation complexity) with no functional benefit. If runtime configurability is required in v2, `PERMISSION_MATRIX` can be migrated to a `roles_permissions` table without any API contract changes.

### 2.4 Record-Level Restrictions

Beyond module-level RBAC, certain operations have additional restrictions:
- Only `admin` can re-activate soft-deleted records
- Only `admin` can void confirmed invoices
- Only `manager` or above can approve purchase/sale returns
- `staff` cannot edit records created more than 24 hours ago

---

## 3. Password Security

### 3.1 Hashing

- Algorithm: **bcrypt** via `passlib[bcrypt]`
- Work factor: **12 rounds** (balances security and performance)
- Never store plaintext passwords; never log passwords

### 3.2 Password Policy

| Rule | Requirement |
|------|-------------|
| Minimum length | 8 characters |
| Maximum length | 128 characters |
| Must contain | At least one letter AND one digit |
| Common passwords | Rejected against top-1000 list |
| Same as username | Not allowed |

Enforced via Pydantic validator on `UserCreate` and `ChangePassword` schemas.

### 3.3 Password Change

- Users can change their own password via `PUT /users/me/password`
- Admin can reset any user's password via `POST /users/{id}/reset-password` (sends a temp password)
- Password history: last 5 passwords stored (hashed); cannot reuse recent passwords

---

## 4. Input Validation & Injection Prevention

### 4.1 SQL Injection

- **All DB queries use SQLAlchemy ORM or parameterized statements**
- No raw string interpolation in SQL ever
- `text()` queries are only used in report queries and must use `:param` binding

```python
# WRONG — never do this
query = f"SELECT * FROM items WHERE name = '{name}'"

# CORRECT — always use parameters
result = await db.execute(
    select(Item).where(Item.name == name)
)
```

### 4.2 XSS Prevention

- API is JSON-only; no HTML rendering in backend
- `Content-Type: application/json` enforced on all responses
- String fields stored as-is; frontend responsible for escaping on render

### 4.3 Mass Assignment Prevention

- Pydantic schemas explicitly declare which fields are accepted on input
- Internal fields (`id`, `created_at`, `balance`, `status`) are never in Create/Update schemas
- SQLAlchemy models are not passed directly to update from request data

### 4.4 Path Traversal

- No file system operations on user-provided paths
- File exports (CSV/Excel) generated in-memory (BytesIO) and streamed

### 4.5 CORS

```python
# Configured in main.py
CORSMiddleware(
    allow_origins=settings.ALLOWED_ORIGINS,  # e.g., ["https://app.smartledger.com"]
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
```

In production, `*` is never allowed as CORS origin.

---

## 5. Data Security

### 5.1 Sensitive Fields

| Field | Protection |
|-------|-----------|
| `hashed_password` | Never returned in any API response |
| `cnic` (Staff national ID) | Admin-only access |
| Account numbers | Masked in list responses: `****1234` |
| Token secrets | Only in environment variables, never in code |

### 5.2 Database Access

- Application connects with a **least-privilege DB user** (no `CREATE TABLE`, `DROP TABLE`)
- Migrations run as a separate user with DDL permissions
- DB credentials in environment variables only — never in source code

### 5.3 TLS

- Production API must run behind HTTPS (TLS 1.2+)
- Database connections use SSL (`?ssl=require` in DSN)
- Redis connection uses TLS in production

---

## 6. Audit Logging

### 6.1 What is Logged

Every `CREATE`, `UPDATE`, `DELETE` operation on any business table is logged to `audit_logs`:

```json
{
  "user_id": 5,
  "action": "UPDATE",
  "table_name": "sale_invoices",
  "record_id": 123,
  "old_values": { "status": "draft", "total_amount": 50000 },
  "new_values": { "status": "confirmed", "total_amount": 50000 },
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "ip_address": "192.168.1.100",
  "created_at": "2026-04-16T09:30:00Z"
}
```

### 6.2 Implementation

Audit logging is done in the service layer (not DB triggers) so it captures the acting user:

```python
# app/utils/audit.py
async def log_audit(db, user_id, action, table_name, record_id, old_values, new_values, request_id):
    log = AuditLog(
        user_id=user_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        old_values=old_values,
        new_values=new_values,
        request_id=request_id,
    )
    db.add(log)
    # No separate commit — runs in same transaction as the mutation
```

### 6.3 Auth Event Logging

In addition to data audit logs, auth events are logged to structured application logs:
- Successful login (user, IP, timestamp)
- Failed login attempts (IP, attempted username, count)
- Token refresh
- Logout
- Permission denied events

### 6.4 Log Retention

- Audit logs: retained for **2 years** (monthly partitioning for efficient archiving)
- Application logs: 90 days in log aggregation system
- Old partitions: archived to cold storage, not deleted

---

## 7. Security Headers

All API responses include:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
Cache-Control: no-store
```

---

## 8. Secrets Management

| Secret | Storage |
|--------|---------|
| Database password | Environment variable |
| Redis password | Environment variable |
| JWT secret key | Environment variable (min 64 chars random) |
| SMTP credentials | Environment variable |
| Any API keys | Environment variable |

**Never:**
- Hardcode secrets in source code
- Commit `.env` files to git
- Log secrets in application logs
- Expose secrets in error messages

---

## 9. Dependency Security

- Run `pip-audit` or `safety check` in CI/CD pipeline
- Automated Dependabot PRs for dependency updates
- Pin all dependencies to exact versions in `pyproject.toml`
- Review changelogs before upgrading auth-related packages

---

## 10. Production Checklist

Before going to production, verify:

- [ ] `SECRET_KEY` is a cryptographically random 64+ character string
- [ ] `ENVIRONMENT=production` (disables `/docs` and `/redoc`)
- [ ] Database user has minimal privileges (no DDL)
- [ ] CORS `allow_origins` set to specific frontend domain(s)
- [ ] All connections use TLS/SSL
- [ ] Rate limiting enabled and tested
- [ ] Audit logging writing correctly
- [ ] Login brute-force protection active
- [ ] No debug logging enabled (`LOG_LEVEL=INFO` or higher)
- [ ] Secrets not in git history (use `git-secrets` or `gitleaks`)
