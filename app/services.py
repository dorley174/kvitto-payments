from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Payment, PaymentStatus, Tariff
from app.schemas import PaymentCreate


class NotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


def installment_schedule(amount: int, months: int) -> list[int]:
    base, remainder = divmod(amount, months)
    return [base + (1 if index < remainder else 0) for index in range(months)]


def list_tariffs(session: Session) -> list[Tariff]:
    with session.begin():
        return list(session.scalars(select(Tariff).order_by(Tariff.price, Tariff.id)))


def create_payment(
    session: Session, data: PaymentCreate, idempotency_key: str | None
) -> tuple[Payment, bool]:
    with session.begin():
        if idempotency_key is not None:
            existing = session.scalar(
                select(Payment).where(Payment.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing, False
        tariff = session.get(Tariff, data.tariff_id)
        if tariff is None:
            raise NotFoundError("Тариф не найден")
        price = tariff.price

    # Чтение завершено до INSERT: SQLite не приходится повышать блокировку чтения.
    discount = price // 10 if data.promo_code is not None else 0
    amount = price - discount
    payment = Payment(
        tariff_id=data.tariff_id,
        email=str(data.email),
        method=data.method,
        installment_months=data.installment_months,
        amount=amount,
        discount=discount,
        schedule=(
            installment_schedule(amount, data.installment_months)
            if data.installment_months is not None
            else None
        ),
        idempotency_key=idempotency_key,
    )
    try:
        with session.begin():
            session.add(payment)
            session.flush()
    except IntegrityError:
        if idempotency_key is None:
            raise
        with session.begin():
            existing = session.scalar(
                select(Payment).where(Payment.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing, False
        raise
    return payment, True


def get_payment(session: Session, payment_id: str) -> Payment:
    with session.begin():
        payment = session.get(Payment, payment_id)
        if payment is None:
            raise NotFoundError("Платёж не найден")
        return payment


def list_payments(
    session: Session, email: str | None = None, status: PaymentStatus | None = None
) -> list[Payment]:
    query = select(Payment).order_by(Payment.created_at, Payment.id)
    if email is not None:
        query = query.where(Payment.email == email)
    if status is not None:
        query = query.where(Payment.status == status)
    with session.begin():
        return list(session.scalars(query))


def change_payment_status(session: Session, payment_id: str, status: PaymentStatus) -> None:
    predecessors = {
        PaymentStatus.SUCCEEDED: PaymentStatus.PENDING,
        PaymentStatus.FAILED: PaymentStatus.PENDING,
        PaymentStatus.REFUNDED: PaymentStatus.SUCCEEDED,
    }
    previous_status = predecessors.get(status)
    with session.begin():
        if previous_status is not None:
            updated_id = session.scalar(
                update(Payment)
                .where(Payment.id == payment_id, Payment.status == previous_status)
                .values(status=status)
                .returning(Payment.id)
            )
            if updated_id is not None:
                return
        if session.scalar(select(Payment.id).where(Payment.id == payment_id)) is None:
            raise NotFoundError("Платёж не найден")
        raise InvalidTransitionError
