from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select, update
from sqlalchemy.orm import Session

from app.database import build_engine
from app.main import create_app
from app.models import Payment, Tariff
from tests.helpers import TARIFFS, create_payment, payment_payload, send_webhook


@pytest.mark.parametrize("price", [9_007_199_254_741_099, 9_223_372_036_854_775_799])
@pytest.mark.parametrize("promo_code", [None, "KVITTO10"])
def test_large_integer_money_never_passes_through_float(
    client: httpx.Client, engine: Engine, price: int, promo_code: str | None
) -> None:
    with Session(engine) as session, session.begin():
        session.execute(update(Tariff).where(Tariff.id == "standard").values(price=price))

    payment = create_payment(
        client, method="installment", installment_months=12, promo_code=promo_code
    )
    discount = price // 10 if promo_code else 0

    assert payment["amount"] == price - discount
    assert payment["discount"] == discount
    assert type(payment["amount"]) is int
    assert type(payment["discount"]) is int
    assert sum(payment["schedule"]) == price - discount
    assert max(payment["schedule"]) - min(payment["schedule"]) <= 1
    assert client.get(f"/payments/{payment['id']}").json() == payment
    with Session(engine) as session:
        stored = session.get(Payment, payment["id"])
        assert stored is not None
        assert stored.amount == price - discount
        assert stored.discount == discount
        assert type(stored.amount) is int
        assert type(stored.discount) is int
        assert stored.schedule == payment["schedule"]


def test_idempotency_does_not_reprice_stored_payment(client: httpx.Client, engine: Engine) -> None:
    headers = {"Idempotency-Key": "stable-price"}
    payload = payment_payload(promo_code="KVITTO10")
    original = client.post("/payments", json=payload, headers=headers)
    assert original.status_code == 201
    with Session(engine) as session, session.begin():
        session.execute(update(Tariff).where(Tariff.id == "standard").values(price=1))

    repeated = client.post("/payments", json=payload, headers=headers)

    assert repeated.status_code == 200
    assert repeated.json() == original.json()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1


def test_new_application_lifespan_preserves_payments_and_seed_is_idempotent(
    client: httpx.Client, application: FastAPI
) -> None:
    payment = create_payment(client, promo_code="KVITTO10")
    assert send_webhook(client, payment["id"], "succeeded").status_code == 200
    restarted = create_app(application.state.settings)

    with TestClient(restarted) as second_client:
        tariffs = second_client.get("/tariffs")
        assert tariffs.status_code == 200
        assert len(tariffs.json()) == 3
        assert {item["id"]: item for item in tariffs.json()} == TARIFFS
        assert second_client.get(f"/payments/{payment['id']}").json() == {
            **payment,
            "status": "succeeded",
        }
        assert len(second_client.get("/payments").json()) == 1


def test_migrations_create_schema_and_database_unique_key(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {"tariffs", "payments", "alembic_version"} <= set(inspector.get_table_names())
    unique_columns = [
        constraint["column_names"] for constraint in inspector.get_unique_constraints("payments")
    ] + [index["column_names"] for index in inspector.get_indexes("payments") if index["unique"]]
    assert ["idempotency_key"] in unique_columns


@pytest.mark.integration
def test_migrations_can_upgrade_downgrade_and_upgrade_clean_database(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    engine = build_engine(f"sqlite:///{tmp_path / 'migration-roundtrip.db'}")
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            assert {"tariffs", "payments"} <= set(inspect(connection).get_table_names())
            command.downgrade(config, "base")
            assert not {"tariffs", "payments"} & set(inspect(connection).get_table_names())
            command.upgrade(config, "head")
            assert {"tariffs", "payments"} <= set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
