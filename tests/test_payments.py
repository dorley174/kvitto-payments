from datetime import datetime
from uuid import UUID, uuid4

import httpx
import pytest

from tests.helpers import (
    PUBLIC_PAYMENT_FIELDS,
    TARIFFS,
    create_payment,
    payment_payload,
    send_webhook,
)


def test_tariffs_have_exact_prices_and_public_fields(client: httpx.Client) -> None:
    response = client.get("/tariffs")

    assert response.status_code == 200
    assert {item["id"]: item for item in response.json()} == TARIFFS
    assert len(response.json()) == 3
    assert all(type(item["price"]) is int for item in response.json())


@pytest.mark.parametrize("tariff_id", TARIFFS)
@pytest.mark.parametrize("method", ["card", "sbp"])
def test_create_and_read_payment(client: httpx.Client, tariff_id: str, method: str) -> None:
    response = client.post("/payments", json=payment_payload(tariff_id=tariff_id, method=method))

    assert response.status_code == 201
    payment = response.json()
    assert set(payment) == PUBLIC_PAYMENT_FIELDS
    assert str(UUID(payment["id"])) == payment["id"]
    assert datetime.fromisoformat(payment["created_at"].replace("Z", "+00:00"))
    assert payment["status"] == "pending"
    assert payment["tariff_id"] == tariff_id
    assert payment["amount"] == TARIFFS[tariff_id]["price"]
    assert type(payment["amount"]) is int
    assert payment["discount"] == 0
    assert type(payment["discount"]) is int
    assert payment["method"] == method
    assert payment["email"] == "student@example.com"
    assert payment["installment_months"] is None
    assert payment["schedule"] is None

    stored = client.get(f"/payments/{payment['id']}")
    assert stored.status_code == 200
    assert stored.json() == payment


@pytest.mark.parametrize("tariff_id", TARIFFS)
@pytest.mark.parametrize("promo_code", ["KVITTO10", "kvitto10", "Kvitto10"])
def test_promotion_is_case_insensitive_and_persists_exact_money(
    client: httpx.Client, tariff_id: str, promo_code: str
) -> None:
    payment = create_payment(client, tariff_id=tariff_id, promo_code=promo_code)
    price = TARIFFS[tariff_id]["price"]

    assert payment["discount"] == price // 10
    assert payment["amount"] == price - price // 10
    assert type(payment["discount"]) is int
    assert type(payment["amount"]) is int
    assert client.get(f"/payments/{payment['id']}").json() == payment


@pytest.mark.parametrize("tariff_id", TARIFFS)
@pytest.mark.parametrize("months", [3, 6, 12])
@pytest.mark.parametrize("promo_code", [None, "kvitto10"])
def test_installment_schedule_preserves_every_kopeck(
    client: httpx.Client, tariff_id: str, months: int, promo_code: str | None
) -> None:
    payment = create_payment(
        client,
        tariff_id=tariff_id,
        method="installment",
        installment_months=months,
        promo_code=promo_code,
    )
    price = TARIFFS[tariff_id]["price"]
    discount = price // 10 if promo_code else 0
    schedule = payment["schedule"]

    assert payment["amount"] == price - discount
    assert payment["discount"] == discount
    assert payment["installment_months"] == months
    assert len(schedule) == months
    assert all(type(amount) is int and amount > 0 for amount in schedule)
    assert sum(schedule) == payment["amount"]
    assert schedule == sorted(schedule, reverse=True)
    assert max(schedule) - min(schedule) <= 1
    assert schedule.count(payment["amount"] // months + 1) == payment["amount"] % months
    assert client.get(f"/payments/{payment['id']}").json() == payment


def test_original_installment_example(client: httpx.Client) -> None:
    payment = create_payment(client, method="installment", installment_months=3)

    assert payment["schedule"] == [663_334, 663_333, 663_333]


def test_unknown_tariff_does_not_create_payment(client: httpx.Client) -> None:
    response = client.post("/payments", json=payment_payload(tariff_id="missing"))

    assert response.status_code == 404
    assert client.get("/payments").json() == []


def test_unknown_payment_returns_404(client: httpx.Client) -> None:
    assert client.get(f"/payments/{uuid4()}").status_code == 404


def test_idempotency_returns_original_payment_and_one_record(client: httpx.Client) -> None:
    headers = {"Idempotency-Key": "repeat-payment"}
    payload = payment_payload(method="installment", installment_months=3)

    first = client.post("/payments", json=payload, headers=headers)
    repeated = client.post("/payments", json=payload, headers=headers)

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert client.get("/payments").json() == [first.json()]


def test_idempotency_preserves_original_with_different_parameters(
    client: httpx.Client,
) -> None:
    headers = {"Idempotency-Key": "immutable-payment"}
    original = client.post("/payments", json=payment_payload(), headers=headers)
    repeated = client.post(
        "/payments",
        json=payment_payload(
            tariff_id="premium",
            email="changed@example.com",
            method="installment",
            installment_months=12,
            promo_code="KVITTO10",
        ),
        headers=headers,
    )

    assert original.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == original.json()
    assert client.get("/payments").json() == [original.json()]


def test_idempotency_returns_current_status_without_resetting_it(
    client: httpx.Client,
) -> None:
    headers = {"Idempotency-Key": "already-paid"}
    first = client.post("/payments", json=payment_payload(), headers=headers)
    assert first.status_code == 201
    payment_id = first.json()["id"]
    assert send_webhook(client, payment_id, "succeeded").status_code == 200

    repeated = client.post("/payments", json=payment_payload(), headers=headers)

    assert repeated.status_code == 200
    assert repeated.json() == {**first.json(), "status": "succeeded"}
    assert len(client.get("/payments").json()) == 1


def test_requests_without_idempotency_key_create_distinct_payments(
    client: httpx.Client,
) -> None:
    first = create_payment(client)
    second = create_payment(client)

    assert first["id"] != second["id"]
    assert len(client.get("/payments").json()) == 2


def test_different_idempotency_keys_create_distinct_payments(client: httpx.Client) -> None:
    responses = [
        client.post(
            "/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": key},
        )
        for key in ("first", "second")
    ]

    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["id"] != responses[1].json()["id"]
    assert len(client.get("/payments").json()) == 2
