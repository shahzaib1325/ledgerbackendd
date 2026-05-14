"""
Custom exception hierarchy for SmartLedger.

All domain exceptions extend AppException.  A global handler in main.py
converts them to the standard error response envelope.

    {
        "success": false,
        "error": {
            "code":    "INSUFFICIENT_STOCK",
            "message": "Item 'Rice 1kg' only has 5 units, requested 20.",
            "field":   "quantity"          # optional
        }
    }
"""

from __future__ import annotations


class AppException(Exception):
    """Base for all application-level exceptions."""

    status_code: int = 500
    default_code: str = "INTERNAL_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        field: str | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.field = field
        super().__init__(self.message)


# ── 404 ───────────────────────────────────────────────────────────────────────

class NotFoundException(AppException):
    status_code = 404
    default_code = "NOT_FOUND"
    default_message = "The requested resource was not found."


# ── 403 ───────────────────────────────────────────────────────────────────────

class ForbiddenException(AppException):
    status_code = 403
    default_code = "FORBIDDEN"
    default_message = "You do not have permission to perform this action."


# ── 401 ───────────────────────────────────────────────────────────────────────

class UnauthorizedException(AppException):
    status_code = 401
    default_code = "UNAUTHORIZED"
    default_message = "Authentication is required."


# ── 409 ───────────────────────────────────────────────────────────────────────

class ConflictException(AppException):
    """State conflict — e.g. editing a confirmed purchase."""

    status_code = 409
    default_code = "CONFLICT"
    default_message = "The operation conflicts with the current resource state."


# ── 422 ───────────────────────────────────────────────────────────────────────

class ValidationException(AppException):
    """Business-rule violation (not Pydantic schema validation)."""

    status_code = 422
    default_code = "VALIDATION_ERROR"
    default_message = "The request failed a business validation rule."


class InsufficientStockError(ValidationException):
    default_code = "INSUFFICIENT_STOCK"
    default_message = "Insufficient stock to complete the operation."


class CreditLimitExceededError(ValidationException):
    default_code = "CREDIT_LIMIT_EXCEEDED"
    default_message = "This operation would exceed the customer's credit limit."


class DuplicateInvoiceError(ValidationException):
    default_code = "DUPLICATE_INVOICE"
    default_message = "An invoice with this number already exists."


# ── Auth-specific 401 / 403 ───────────────────────────────────────────────────

class InvalidCredentialsError(AppException):
    """Wrong username or password.  Same message for both to prevent enumeration."""

    status_code = 401
    default_code = "INVALID_CREDENTIALS"
    default_message = "Invalid username or password."


class TokenExpiredError(AppException):
    """JWT access or refresh token has passed its expiry time."""

    status_code = 401
    default_code = "TOKEN_EXPIRED"
    default_message = "Your session has expired. Please log in again."


class TokenInvalidError(AppException):
    """JWT is malformed, has an invalid signature, or has been blacklisted."""

    status_code = 401
    default_code = "TOKEN_INVALID"
    default_message = "Invalid or revoked token."


class PermissionDeniedError(AppException):
    """Authenticated user's role lacks the required permission for this action."""

    status_code = 403
    default_code = "PERMISSION_DENIED"
    default_message = "You do not have permission to perform this action."
