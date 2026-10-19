import hashlib
import hmac
import json
from typing import Any

import httpx

WEBHOOK_SECRET = "test-only-webhook-secret"
PUBLIC_PAYMENT_FIELDS = {
    "id",
    "status",
    "tariff_id",
    "amount",
    "discount",
    "method",
    "installment_months",
    "schedule",
    "email",
    "created_at",
}
TARIFFS = {
    "basic": {"id": "basic", "title": "Basic", "price": 990_000},
    "standard": {"id": "standard", "title": "Standard", "price": 1_990_000},
    "premium": {"id": "premium", "title": "Premium", "price": 2_990_000},
}


def payment_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "tariff_id": "standard",
        "email": "student@example.com",
        "method": "card",
        **overrides,
    }


def create_payment(client: httpx.Client, **overrides: Any) -> dict[str, Any]:
    response = client.post("/payments", json=payment_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def signature(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def send_webhook(client: httpx.Client, payment_id: str, status: str) -> httpx.Response:
    body = json.dumps({"payment_id": payment_id, "status": status}).encode()
    return client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature(body)},
    )


def move_to_status(client: httpx.Client, payment_id: str, status: str) -> None:
    transitions = {
        "pending": (),
        "succeeded": ("succeeded",),
        "failed": ("failed",),
        "refunded": ("succeeded", "refunded"),
    }
    for next_status in transitions[status]:
        response = send_webhook(client, payment_id, next_status)
        assert response.status_code == 200, response.text
        assert response.json() == {"result": "ok"}
