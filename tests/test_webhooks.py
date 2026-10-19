import json
from itertools import product
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.helpers import create_payment, move_to_status, send_webhook, signature

STATUSES = ["pending", "succeeded", "failed", "refunded"]
ALLOWED_TRANSITIONS = {
    ("pending", "succeeded"),
    ("pending", "failed"),
    ("succeeded", "refunded"),
}


@pytest.mark.parametrize(("initial", "target"), list(product(STATUSES, repeat=2)))
def test_complete_status_transition_matrix(client: httpx.Client, initial: str, target: str) -> None:
    payment = create_payment(client)
    payment_id = payment["id"]
    move_to_status(client, payment_id, initial)

    response = send_webhook(client, payment_id, target)
    stored = client.get(f"/payments/{payment_id}")

    assert stored.status_code == 200
    if (initial, target) in ALLOWED_TRANSITIONS:
        assert response.status_code == 200
        assert response.json() == {"result": "ok"}
        assert stored.json() == {**payment, "status": target}
    else:
        assert response.status_code == 409
        assert response.json() == {"error": "invalid_transition"}
        assert stored.json() == {**payment, "status": initial}


def test_signed_webhook_for_missing_payment_returns_404(client: httpx.Client) -> None:
    response = send_webhook(client, str(uuid4()), "succeeded")

    assert response.status_code == 404
    assert client.get("/payments").json() == []


@pytest.mark.parametrize("provided_signature", [None, "", "wrong", "0" * 64, "é" * 64])
def test_invalid_signature_does_not_change_payment(
    client: httpx.Client, provided_signature: str | None
) -> None:
    payment = create_payment(client)
    body = json.dumps({"payment_id": payment["id"], "status": "succeeded"}).encode()
    headers: dict[str | bytes, str | bytes] = {"Content-Type": "application/json"}
    if provided_signature is not None:
        headers[b"X-Signature"] = provided_signature.encode("utf-8")

    response = client.post("/webhooks/bank", content=body, headers=headers)

    assert response.status_code == 401
    assert client.get(f"/payments/{payment['id']}").json() == payment


@pytest.mark.parametrize("uppercase_signature", [False, True])
def test_signature_uses_original_json_bytes(
    client: httpx.Client, uppercase_signature: bool
) -> None:
    payment = create_payment(client)
    body = (f'{{\n  "status": "succeeded",\n  "payment_id" : "{payment["id"]}"\n}}\n').encode()
    signed_header = signature(body)
    if uppercase_signature:
        signed_header = signed_header.upper()

    response = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signed_header},
    )

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert client.get(f"/payments/{payment['id']}").json()["status"] == "succeeded"


def test_signature_rejects_reserialized_equivalent_json(client: httpx.Client) -> None:
    payment = create_payment(client)
    payload = {"payment_id": payment["id"], "status": "succeeded"}
    signed_body = json.dumps(payload, separators=(",", ":")).encode()
    transmitted_body = json.dumps(payload, indent=2).encode()

    response = client.post(
        "/webhooks/bank",
        content=transmitted_body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": signature(signed_body),
        },
    )

    assert response.status_code == 401
    assert client.get(f"/payments/{payment['id']}").json() == payment


def test_signature_rejects_changed_status(client: httpx.Client) -> None:
    payment = create_payment(client)
    signed_body = json.dumps({"payment_id": payment["id"], "status": "failed"}).encode()
    transmitted_body = signed_body.replace(b"failed", b"succeeded")

    response = client.post(
        "/webhooks/bank",
        content=transmitted_body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": signature(signed_body),
        },
    )

    assert response.status_code == 401
    assert client.get(f"/payments/{payment['id']}").json() == payment


@pytest.mark.parametrize("body", [b"{", b"[]", b"null", b'"succeeded"'])
def test_signed_invalid_json_returns_validation_error(client: httpx.Client, body: bytes) -> None:
    payment = create_payment(client)

    response = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature(body)},
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get(f"/payments/{payment['id']}").json() == payment


def test_signature_is_checked_before_parsing_malformed_json(client: httpx.Client) -> None:
    response = client.post(
        "/webhooks/bank", content=b"{", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 401


def test_bad_signature_does_not_reveal_payment_existence(client: httpx.Client) -> None:
    response = client.post(
        "/webhooks/bank",
        json={"payment_id": str(uuid4()), "status": "succeeded"},
        headers={"X-Signature": "0" * 64},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "paid"),
        ("status", "SUCCEEDED"),
        ("status", 1),
        ("status", True),
        ("status", None),
        ("payment_id", 123),
        ("payment_id", True),
        ("payment_id", None),
    ],
)
def test_webhook_rejects_invalid_field_values(client: httpx.Client, field: str, value: Any) -> None:
    payment = create_payment(client)
    payload = {"payment_id": payment["id"], "status": "succeeded", field: value}
    body = json.dumps(payload).encode()

    response = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature(body)},
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get(f"/payments/{payment['id']}").json() == payment


@pytest.mark.parametrize("field", ["payment_id", "status"])
def test_webhook_requires_both_fields(client: httpx.Client, field: str) -> None:
    payment = create_payment(client)
    payload = {"payment_id": payment["id"], "status": "succeeded"}
    del payload[field]
    body = json.dumps(payload).encode()

    response = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature(body)},
    )

    assert response.status_code == 422
    assert client.get(f"/payments/{payment['id']}").json() == payment


def test_signed_nonfinite_status_returns_422_without_changing_payment(
    client: httpx.Client,
) -> None:
    payment = create_payment(client)
    body = f'{{"payment_id":"{payment["id"]}","status":NaN}}'.encode()

    response = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature(body)},
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get(f"/payments/{payment['id']}").json() == payment
