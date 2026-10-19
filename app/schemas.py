from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.models import PaymentMethod, PaymentStatus

PositiveKopecks = Annotated[int, Field(strict=True, gt=0)]
NonnegativeKopecks = Annotated[int, Field(strict=True, ge=0)]


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tariff_id: Annotated[StrictStr, Field(min_length=1, max_length=32)]
    email: Annotated[EmailStr, Field(max_length=254)]
    method: PaymentMethod
    installment_months: (
        Annotated[StrictInt, Field(json_schema_extra={"enum": [3, 6, 12]})] | None
    ) = None
    promo_code: Annotated[StrictStr, Field(max_length=32)] | None = None

    @field_validator("promo_code")
    @classmethod
    def validate_promo_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.upper() != "KVITTO10":
            raise ValueError("Неизвестный промокод")
        return "KVITTO10"

    @field_validator("installment_months")
    @classmethod
    def validate_installment_months(cls, value: int | None) -> int | None:
        if value is not None and value not in {3, 6, 12}:
            raise ValueError("Допустимый срок рассрочки: 3, 6 или 12 месяцев")
        return value

    @model_validator(mode="after")
    def validate_method_and_months(self) -> Self:
        if self.method == PaymentMethod.INSTALLMENT and self.installment_months is None:
            raise ValueError("Для рассрочки обязателен installment_months")
        if self.method != PaymentMethod.INSTALLMENT and self.installment_months is not None:
            raise ValueError("installment_months разрешён только для рассрочки")
        return self


class TariffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    price: PositiveKopecks


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: PaymentStatus
    tariff_id: str
    amount: PositiveKopecks
    discount: NonnegativeKopecks
    method: PaymentMethod
    installment_months: int | None
    schedule: list[PositiveKopecks] | None
    email: EmailStr
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        # SQLite не сохраняет tzinfo; все даты создаются в UTC.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class BankWebhook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: Annotated[StrictStr, Field(min_length=1, max_length=36)]
    status: PaymentStatus


class WebhookResponse(BaseModel):
    result: Literal["ok"] = "ok"


class TransitionErrorResponse(BaseModel):
    error: Literal["invalid_transition"] = "invalid_transition"
