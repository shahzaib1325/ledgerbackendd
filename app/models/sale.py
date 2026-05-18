from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    NotificationType,
    PaymentMode,
    PaymentType,
    ReturnStatus,
    SaleStatus,
)


class SaleInvoice(TimestampMixin, Base):
    __tablename__ = "sale_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True
    )
    customer_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="regular", server_default="regular"
    )
    walking_customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    walking_customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    walking_customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    walking_customer_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    walking_customer_tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    invoice_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_type: Mapped[PaymentType] = mapped_column(
        Enum(PaymentType, name="payment_type", native_enum=True, create_type=False),
        nullable=False,
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    discount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    tax: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    due_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        Computed("total_amount - paid_amount", persisted=True),
        nullable=False,
    )
    status: Mapped[SaleStatus] = mapped_column(
        Enum(SaleStatus, name="sale_status", native_enum=True),
        nullable=False,
        default=SaleStatus.draft,
        server_default=SaleStatus.draft.value,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    customer: Mapped["Customer | None"] = relationship(  # type: ignore[name-defined]
        back_populates="invoices", foreign_keys=[customer_id]
    )

    @property
    def customer_name(self) -> str:
        if self.customer:
            return self.customer.name
        return self.walking_customer_name or "Walk-in"
    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    payments: Mapped[list["SalePayment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    returns: Mapped[list["SaleReturn"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_sales_customer", "customer_id"),
        Index("idx_sales_invoice_no", "invoice_no"),
        Index("idx_sales_date", "invoice_date"),
        Index("idx_sales_status", "status"),
        Index("idx_sales_due_date", "due_date"),
    )


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sale_invoices.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    invoice: Mapped["SaleInvoice"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(foreign_keys=[item_id])  # type: ignore[name-defined]
    unit: Mapped["Unit"] = relationship(foreign_keys=[unit_id])  # type: ignore[name-defined]


class SalePayment(Base):
    __tablename__ = "sale_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sale_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_mode: Mapped[PaymentMode] = mapped_column(
        Enum(PaymentMode, name="payment_mode", native_enum=True, create_type=False),
        nullable=False,
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    invoice: Mapped["SaleInvoice"] = relationship(back_populates="payments")
    account: Mapped["Account"] = relationship(foreign_keys=[account_id])  # type: ignore[name-defined]


class SaleReturn(Base):
    __tablename__ = "sale_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sale_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    return_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    penalty: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    return_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="partial", server_default="partial"
    )
    status: Mapped[ReturnStatus] = mapped_column(
        Enum(ReturnStatus, name="return_status", native_enum=True, create_type=False),
        nullable=False,
        default=ReturnStatus.pending,
        server_default=ReturnStatus.pending.value,
    )
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    received_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    settlement_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="unsettled", server_default="unsettled"
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    invoice: Mapped["SaleInvoice"] = relationship(back_populates="returns")
    return_items: Mapped[list["SaleReturnItem"]] = relationship(
        back_populates="sale_return", cascade="all, delete-orphan"
    )
    payments: Mapped[list["SaleReturnPayment"]] = relationship(
        back_populates="sale_return", cascade="all, delete-orphan"
    )


class SaleReturnItem(Base):
    __tablename__ = "sale_return_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    sale_return: Mapped["SaleReturn"] = relationship(back_populates="return_items")
    item: Mapped["Item"] = relationship(foreign_keys=[item_id])  # type: ignore[name-defined]


class SaleReturnPayment(Base):
    __tablename__ = "sale_return_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    sale_return: Mapped["SaleReturn"] = relationship(back_populates="payments")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("sale_invoices.id", ondelete="SET NULL"), nullable=True
    )
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type", native_enum=True),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    invoice: Mapped["SaleInvoice | None"] = relationship(
        back_populates="notifications", foreign_keys=[invoice_id]
    )
