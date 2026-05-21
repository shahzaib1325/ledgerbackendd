"""
JWT utilities and password security for SmartLedger.

Token payload spec (SECURITY.md §1.1):
    Access : { sub, username, role, jti, iat, exp, type="access" }
    Refresh: { sub, jti, exp, type="refresh" }

bcrypt work factor: 12 rounds (SECURITY.md §3.1)
Password policy    (SECURITY.md §3.2):
    - 8–128 characters
    - at least one letter AND one digit
    - not the same as username
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

ALGORITHM = "HS256"

# bcrypt with explicitly enforced work factor of 12 rounds.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)

# Top-1,000 common passwords (abbreviated list; extend as needed).
_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password", "password1", "12345678", "123456789", "1234567890",
        "qwerty123", "iloveyou", "admin123", "letmein1", "welcome1",
        "monkey123", "dragon123", "master123", "sunshine1", "princess1",
        "shadow123", "superman1", "michael1", "football", "baseball1",
    }
)


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def validate_password_policy(password: str, *, username: str = "") -> None:
    """
    Enforce the password policy from SECURITY.md §3.2.
    Raises ValueError with a descriptive message on failure.
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(password) > 128:
        raise ValueError("Password must not exceed 128 characters.")
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        raise ValueError("Password must contain at least one letter and one digit.")
    if username and password.lower() == username.lower():
        raise ValueError("Password must not be the same as the username.")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common. Please choose a stronger password.")


def generate_temp_password(length: int = 16) -> str:
    """Generate a cryptographically secure temporary password for admin resets."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        try:
            validate_password_policy(pw)
            return pw
        except ValueError:
            continue  # retry on the rare case constraints aren't met


# ── JWT token creation ────────────────────────────────────────────────────────

def create_access_token(
    *,
    subject: str | int,
    username: str,
) -> tuple[str, str]:
    """
    Returns (encoded_jwt, jti).
    The JTI is returned so callers can store it in Redis on logout.

    The token identifies the user only. Permissions are NEVER embedded —
    they are resolved server-side per request (see app/core/rbac.py) so a
    role change takes effect immediately without waiting for token expiry.
    """
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {
        "sub": str(subject),
        "username": username,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    return _encode(claims), jti


def create_refresh_token(*, subject: str | int) -> tuple[str, str]:
    """
    Returns (encoded_jwt, jti).
    Refresh tokens carry sub, jti, iat, exp (no role/username — always re-load from DB).
    """
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    claims = {
        "sub": str(subject),
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    return _encode(claims), jti


def create_token_pair(
    *,
    subject: str | int,
    username: str,
) -> tuple[str, str, str, str]:
    """
    Convenience helper — returns (access_token, access_jti, refresh_token, refresh_jti).
    """
    access_token, access_jti = create_access_token(
        subject=subject, username=username
    )
    refresh_token, refresh_jti = create_refresh_token(subject=subject)
    return access_token, access_jti, refresh_token, refresh_jti


# ── JWT decoding ──────────────────────────────────────────────────────────────

def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT (signature + expiry).

    Raises jose.ExpiredSignatureError on expiry; jose.JWTError on any other
    decode failure.  Callers import those from jose and map them to domain
    exceptions (TokenExpiredError / TokenInvalidError).
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


# ── Internals ─────────────────────────────────────────────────────────────────

def _encode(claims: dict) -> str:
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=ALGORITHM)
