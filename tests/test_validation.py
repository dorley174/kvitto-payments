from typing import Any

import httpx
import pytest

from tests.helpers import create_payment, payment_payload


@pytest.mark.parametrize("field", ["tariff_id", "email", "method"])
def test_required_payment_fields(client: httpx.Client, field: str) -> None:
    payload = payment_payload()
    del payload[field]

    response = client.post("/payments", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get("/payments").json() == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tariff_id", None),
        ("tariff_id", 123),
        ("tariff_id", True),
        ("tariff_id", ["standard"]),
        ("email", "invalid-email"),
        ("email", ""),
        ("email", "user@"),
        ("email", None),
        ("email", 123),
        ("email", False),
        ("email", ["user@example.com"]),
        ("method", "cash"),
        ("method", "CARD"),
        ("method", ""),
        ("method", None),
        ("method", 1),
        ("method", True),
        ("method", ["card"]),
        ("promo_code", "UNKNOWN"),
        ("promo_code", ""),
        ("promo_code", " KVITTO10 "),
        ("promo_code", 123),
        ("promo_code", True),
        ("promo_code", ["KVITTO10"]),
    ],
)
def test_invalid_payment_values_are_not_silently_coerced(
    client: httpx.Client, field: str, value: Any
) -> None:
    response = client.post("/payments", json=payment_payload(**{field: value}))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get("/payments").json() == []


@pytest.mark.parametrize(
    "months", [None, 0, -3, 1, 2, 4, 7, 24, "3", "6", "12", 3.0, True, False, [3], {}]
)
def test_installment_months_are_strict_allowed_integers(client: httpx.Client, months: Any) -> None:
    response = client.post(
        "/payments",
        json=payment_payload(method="installment", installment_months=months),
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get("/payments").json() == []


def test_installment_requires_months(client: httpx.Client) -> None:
    response = client.post("/payments", json=payment_payload(method="installment"))

    assert response.status_code == 422
    assert client.get("/payments").json() == []


@pytest.mark.parametrize("method", ["card", "sbp"])
@pytest.mark.parametrize("months", [3, 6, 12])
def test_non_installment_methods_reject_months(
    client: httpx.Client, method: str, months: int
) -> None:
    response = client.post(
        "/payments", json=payment_payload(method=method, installment_months=months)
    )

    assert response.status_code == 422
    assert client.get("/payments").json() == []


@pytest.mark.parametrize("method", ["card", "sbp"])
def test_non_installment_methods_accept_explicit_null_months(
    client: httpx.Client, method: str
) -> None:
    payment = create_payment(client, method=method, installment_months=None)

    assert payment["installment_months"] is None
    assert payment["schedule"] is None


def test_explicit_null_promotion_means_full_price(client: httpx.Client) -> None:
    payment = create_payment(client, promo_code=None)

    assert payment["amount"] == 1_990_000
    assert payment["discount"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("amount", 1), ("discount", 1_000_000), ("status", "succeeded"), ("id", "custom")],
)
def test_server_owned_fields_cannot_be_set_by_client(
    client: httpx.Client, field: str, value: Any
) -> None:
    response = client.post("/payments", json=payment_payload(**{field: value}))

    assert response.status_code == 422
    assert client.get("/payments").json() == []


@pytest.mark.parametrize("key", ["", " ", "\t", "x" * 256])
def test_invalid_idempotency_keys_are_rejected(client: httpx.Client, key: str) -> None:
    response = client.post("/payments", json=payment_payload(), headers={"Idempotency-Key": key})

    assert response.status_code == 422
    assert client.get("/payments").json() == []


def test_existing_idempotency_key_does_not_bypass_body_validation(
    client: httpx.Client,
) -> None:
    headers = {"Idempotency-Key": "validate-first"}
    original = client.post("/payments", json=payment_payload(), headers=headers)
    invalid = client.post("/payments", json=payment_payload(promo_code="UNKNOWN"), headers=headers)

    assert original.status_code == 201
    assert invalid.status_code == 422
    assert client.get("/payments").json() == [original.json()]


def test_maximum_idempotency_key_length_is_supported(client: httpx.Client) -> None:
    headers = {"Idempotency-Key": "x" * 255}
    created = client.post("/payments", json=payment_payload(), headers=headers)
    repeated = client.post("/payments", json=payment_payload(), headers=headers)

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert created.json() == repeated.json()


@pytest.mark.parametrize("body", [b"{", b"[]", b"null", b'"card"'])
def test_invalid_payment_json(client: httpx.Client, body: bytes) -> None:
    response = client.post("/payments", content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get("/payments").json() == []


@pytest.mark.parametrize(
    "fields",
    [
        b'"method":"installment","installment_months":1e400',
        b'"method":"installment","installment_months":Infinity',
        b'"method":NaN',
        b'"method":"card","amount":NaN',
    ],
)
def test_nonfinite_numbers_return_serializable_validation_errors(
    client: httpx.Client, fields: bytes
) -> None:
    body = b'{"tariff_id":"standard","email":"student@example.com",' + fields + b"}"

    response = client.post("/payments", content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get("/payments").json() == []
