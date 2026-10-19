from typing import Annotated

from fastapi import APIRouter, Header, Query, Response
from pydantic import EmailStr

from app import services
from app.database import SessionDependency
from app.models import Payment, PaymentStatus
from app.schemas import PaymentCreate, PaymentResponse

router = APIRouter(prefix="/payments", tags=["Платежи"])


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=201,
    responses={
        200: {"model": PaymentResponse, "description": "Платёж с таким ключом уже существует"}
    },
    summary="Создать платёж",
)
def post_payment(
    data: PaymentCreate,
    response: Response,
    session: SessionDependency,
    idempotency_key: Annotated[
        str | None, Header(min_length=1, max_length=255, pattern=r"\S")
    ] = None,
) -> Payment:
    payment, created = services.create_payment(session, data, idempotency_key)
    response.status_code = 201 if created else 200
    return payment


@router.get("", response_model=list[PaymentResponse], summary="Список платежей с фильтрами")
def get_payments(
    session: SessionDependency,
    email: Annotated[EmailStr | None, Query()] = None,
    status: Annotated[PaymentStatus | None, Query()] = None,
) -> list[Payment]:
    return services.list_payments(session, email, status)


@router.get("/{payment_id}", response_model=PaymentResponse, summary="Получить платёж")
def get_payment(payment_id: str, session: SessionDependency) -> Payment:
    return services.get_payment(session, payment_id)
