from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.models import Payment
from tests.helpers import PUBLIC_PAYMENT_FIELDS, create_payment, move_to_status


@pytest.fixture
def payments(client: httpx.Client) -> list[dict[str, Any]]:
    result = []
    for email, status in [
        ("alice@example.com", "pending"),
        ("alice@example.com", "succeeded"),
        ("alice@example.com", "refunded"),
        ("bob@example.com", "failed"),
        ("bob@example.com", "succeeded"),
    ]:
        payment = create_payment(client, email=email)
        move_to_status(client, payment["id"], status)
        result.append({**payment, "status": status})
    return result


@pytest.mark.parametrize(
    ("params", "indices"),
    [
        ({}, [0, 1, 2, 3, 4]),
        ({"email": "alice@example.com"}, [0, 1, 2]),
        ({"status": "succeeded"}, [1, 4]),
        ({"status": "pending"}, [0]),
        ({"status": "failed"}, [3]),
        ({"status": "refunded"}, [2]),
        ({"email": "alice@example.com", "status": "succeeded"}, [1]),
        ({"email": "bob@example.com", "status": "failed"}, [3]),
        ({"email": "alice@example.com", "status": "failed"}, []),
        ({"email": "nobody@example.com"}, []),
    ],
)
def test_payment_filters_and_public_fields(
    client: httpx.Client,
    payments: list[dict[str, Any]],
    params: dict[str, str],
    indices: list[int],
) -> None:
    response = client.get("/payments", params=params)
    expected = sorted(
        [payments[index] for index in indices],
        key=lambda payment: (payment["created_at"], payment["id"]),
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert all(set(payment) == PUBLIC_PAYMENT_FIELDS for payment in response.json())


def test_empty_payment_list(client: httpx.Client) -> None:
    response = client.get("/payments")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params", [{"email": "invalid-email"}, {"status": "paid"}, {"status": "SUCCEEDED"}]
)
def test_invalid_payment_filters_return_422(client: httpx.Client, params: dict[str, str]) -> None:
    response = client.get("/payments", params=params)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_payment_order_uses_id_when_timestamps_match(client: httpx.Client, engine: Engine) -> None:
    payments = [create_payment(client) for _ in range(3)]
    with Session(engine) as session, session.begin():
        session.execute(update(Payment).values(created_at=datetime(2026, 1, 1, tzinfo=UTC)))

    response = client.get("/payments")

    assert response.status_code == 200
    assert [payment["id"] for payment in response.json()] == sorted(
        payment["id"] for payment in payments
    )


def test_email_domain_normalization_is_consistent_with_filter(client: httpx.Client) -> None:
    payment = create_payment(client, email="student@EXAMPLE.COM")

    assert payment["email"] == "student@example.com"
    response = client.get("/payments", params={"email": "student@EXAMPLE.COM"})
    assert response.status_code == 200
    assert response.json() == [payment]
