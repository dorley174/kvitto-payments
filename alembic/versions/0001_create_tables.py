"""Тарифы, платежи и ограничения целостности."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tariffs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(64), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("price > 0", name="ck_tariffs_price_positive"),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "succeeded",
                "failed",
                "refunded",
                name="payment_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("tariff_id", sa.String(32), sa.ForeignKey("tariffs.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("discount", sa.BigInteger(), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "card",
                "sbp",
                "installment",
                name="payment_method",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("installment_months", sa.Integer(), nullable=True),
        sa.Column("schedule", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint("discount >= 0", name="ck_payments_discount_nonnegative"),
        sa.CheckConstraint(
            "(method = 'installment' AND installment_months IS NOT NULL "
            "AND installment_months IN (3, 6, 12) AND schedule IS NOT NULL) "
            "OR (method IN ('card', 'sbp') AND installment_months IS NULL AND schedule IS NULL)",
            name="ck_payments_installment_fields",
        ),
    )
    op.create_index("ix_payments_email", "payments", ["email"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_created_at_id", "payments", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_payments_created_at_id", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_email", table_name="payments")
    op.drop_table("payments")
    op.drop_table("tariffs")
