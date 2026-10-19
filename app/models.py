from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class PaymentMethod(StrEnum):
    CARD = "card"
    SBP = "sbp"
    INSTALLMENT = "installment"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class Base(DeclarativeBase):
    pass


class Tariff(Base):
    __tablename__ = "tariffs"
    __table_args__ = (CheckConstraint("price > 0", name="ck_tariffs_price_positive"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    price: Mapped[int] = mapped_column(BigInteger)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("discount >= 0", name="ck_payments_discount_nonnegative"),
        CheckConstraint(
            "(method = 'installment' AND installment_months IS NOT NULL "
            "AND installment_months IN (3, 6, 12) AND schedule IS NOT NULL) "
            "OR (method IN ('card', 'sbp') AND installment_months IS NULL AND schedule IS NULL)",
            name="ck_payments_installment_fields",
        ),
        Index("ix_payments_email", "email"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_created_at_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            values_callable=lambda values: [item.value for item in values],
            name="payment_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=PaymentStatus.PENDING,
    )
    tariff_id: Mapped[str] = mapped_column(ForeignKey("tariffs.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    discount: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(
            PaymentMethod,
            values_callable=lambda values: [item.value for item in values],
            name="payment_method",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    installment_months: Mapped[int | None]
    schedule: Mapped[list[int] | None] = mapped_column(JSON(none_as_null=True))
    email: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
