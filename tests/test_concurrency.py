from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Lock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, event, func, select
from sqlalchemy.engine import ExecutionContext
from sqlalchemy.orm import Session

from app.models import Payment
from tests.helpers import create_payment, payment_payload, send_webhook

pytestmark = pytest.mark.integration


@contextmanager
def synchronize_payment_statements(
    engine: Engine, operation: str, parties: int = 2
) -> Iterator[None]:
    """Оба запроса доходят до записи до того, как любой из них изменит базу."""
    barrier = Barrier(parties)
    lock = Lock()
    arrivals = 0

    def wait_before_statement(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        nonlocal arrivals
        normalized = statement.lstrip().lower()
        if not normalized.startswith(f"{operation} payments"):
            return
        with lock:
            if arrivals >= parties:
                return
            arrivals += 1
        barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", wait_before_statement)
    try:
        yield
        assert arrivals == parties
    finally:
        event.remove(engine, "before_cursor_execute", wait_before_statement)


def concurrent_requests(
    application: FastAPI,
    actions: list[Callable[[httpx.Client], httpx.Response]],
) -> list[httpx.Response]:
    start = Barrier(len(actions))

    def execute(action: Callable[[httpx.Client], httpx.Response]) -> httpx.Response:
        worker_client = TestClient(application)
        try:
            start.wait(timeout=10)
            return action(worker_client)
        finally:
            worker_client.close()

    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        futures = [executor.submit(execute, action) for action in actions]
        return [future.result(timeout=20) for future in futures]


@pytest.mark.parametrize("different_parameters", [False, True])
def test_concurrent_idempotency_inserts_leave_exactly_one_payment(
    client: httpx.Client,
    application: FastAPI,
    engine: Engine,
    different_parameters: bool,
) -> None:
    first_payload = payment_payload()
    second_payload = (
        payment_payload(tariff_id="premium", email="second@example.com", method="sbp")
        if different_parameters
        else first_payload
    )
    headers = {"Idempotency-Key": "simultaneous-payment"}

    with synchronize_payment_statements(engine, "insert into"):
        responses = concurrent_requests(
            application,
            [
                lambda worker: worker.post("/payments", json=first_payload, headers=headers),
                lambda worker: worker.post("/payments", json=second_payload, headers=headers),
            ],
        )

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()
    assert client.get("/payments").json() == [responses[0].json()]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1


@pytest.mark.parametrize(
    ("first_target", "second_target"),
    [("succeeded", "failed"), ("succeeded", "succeeded"), ("failed", "failed")],
)
def test_concurrent_pending_transitions_have_only_one_winner(
    client: httpx.Client,
    application: FastAPI,
    engine: Engine,
    first_target: str,
    second_target: str,
) -> None:
    payment = create_payment(client)

    with synchronize_payment_statements(engine, "update"):
        responses = concurrent_requests(
            application,
            [
                lambda worker: send_webhook(worker, payment["id"], first_target),
                lambda worker: send_webhook(worker, payment["id"], second_target),
            ],
        )

    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
    assert responses[winner].json() == {"result": "ok"}
    assert responses[1 - winner].json() == {"error": "invalid_transition"}
    expected_status = (first_target, second_target)[winner]
    assert client.get(f"/payments/{payment['id']}").json() == {
        **payment,
        "status": expected_status,
    }
    with Session(engine) as session:
        stored = session.get(Payment, payment["id"])
        assert stored is not None
        assert stored.status == expected_status


def test_concurrent_refunds_succeed_only_once(
    client: httpx.Client, application: FastAPI, engine: Engine
) -> None:
    payment = create_payment(client)
    assert send_webhook(client, payment["id"], "succeeded").status_code == 200

    with synchronize_payment_statements(engine, "update"):
        responses = concurrent_requests(
            application,
            [
                lambda worker: send_webhook(worker, payment["id"], "refunded"),
                lambda worker: send_webhook(worker, payment["id"], "refunded"),
            ],
        )

    assert sorted(response.status_code for response in responses) == [200, 409]
    for response in responses:
        expected = (
            {"result": "ok"} if response.status_code == 200 else {"error": "invalid_transition"}
        )
        assert response.json() == expected
    assert client.get(f"/payments/{payment['id']}").json() == {
        **payment,
        "status": "refunded",
    }


def test_concurrent_requests_without_key_each_create_payment(
    client: httpx.Client, application: FastAPI, engine: Engine
) -> None:
    with synchronize_payment_statements(engine, "insert into"):
        responses = concurrent_requests(
            application,
            [
                lambda worker: worker.post("/payments", json=payment_payload()),
                lambda worker: worker.post("/payments", json=payment_payload()),
            ],
        )

    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["id"] != responses[1].json()["id"]
    assert len(client.get("/payments").json()) == 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 2
