"""
PostgreSQL native ENUM types for SmartLedger.

All enums map 1-to-1 with the CREATE TYPE statements in DATABASE_SCHEMA.md.
SQLAlchemy will emit CREATE TYPE ... AS ENUM (...) during table creation /
Alembic migrations when native_enum=True (the default).
"""

import enum


class PaymentMode(str, enum.Enum):
    cash = "cash"
    bank = "bank"
    digital = "digital"


class PaymentType(str, enum.Enum):
    cash = "cash"
    credit = "credit"
    partial = "partial"


class BalanceType(str, enum.Enum):
    payable = "payable"
    receivable = "receivable"


class ItemType(str, enum.Enum):
    purchased = "purchased"
    produced = "produced"


class MovementType(str, enum.Enum):
    purchase_in = "purchase_in"
    sale_out = "sale_out"
    production_in = "production_in"
    production_out = "production_out"
    return_in = "return_in"
    return_out = "return_out"
    adjustment = "adjustment"


class PurchaseStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    returned = "returned"
    void = "void"


class SaleStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    partially_paid = "partially_paid"
    paid = "paid"
    returned = "returned"
    void = "void"


class ReturnStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class StaffType(str, enum.Enum):
    permanent = "permanent"
    temporary = "temporary"


class CompensationType(str, enum.Enum):
    salary_based = "salary_based"
    per_unit = "per_unit"


class SalaryPeriod(str, enum.Enum):
    monthly = "monthly"
    weekly = "weekly"


class AttendanceStatus(str, enum.Enum):
    present = "present"
    absent = "absent"
    half_day = "half_day"
    leave = "leave"


class AccountType(str, enum.Enum):
    cash = "cash"
    bank = "bank"
    digital = "digital"


class TransactionType(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class ReferenceType(str, enum.Enum):
    purchase = "purchase"
    sale = "sale"
    purchase_payment = "purchase_payment"
    sale_payment = "sale_payment"
    sale_return = "sale_return"
    salary = "salary"
    advance = "advance"
    transfer = "transfer"
    expense = "expense"
    adjustment = "adjustment"


class ProductionStatus(str, enum.Enum):
    planned = "planned"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class NotificationType(str, enum.Enum):
    due = "due"
    overdue = "overdue"
    credit_limit = "credit_limit"
    low_stock = "low_stock"


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
