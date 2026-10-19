from collections.abc import Iterator
from pathlib import Path
from shutil import copyfile

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from app.config import Settings
from app.database import build_engine
from app.main import create_app
from tests.helpers import WEBHOOK_SECRET

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Каждый тест получает файловую копию схемы, созданной настоящими миграциями."""
    database = tmp_path_factory.mktemp("schema") / "template.db"
    engine = build_engine(f"sqlite:///{database}")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    engine.dispose()
    return database


@pytest.fixture
def database_url(tmp_path: Path, migrated_database: Path) -> str:
    database = tmp_path / "payments.db"
    copyfile(migrated_database, database)
    return f"sqlite:///{database}"


@pytest.fixture
def application(database_url: str) -> FastAPI:
    settings = Settings(
        database_url=database_url,
        webhook_secret=SecretStr(WEBHOOK_SECRET),
        _env_file=None,
    )
    return create_app(settings)


@pytest.fixture
def client(application: FastAPI) -> Iterator[httpx.Client]:
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def engine(client: httpx.Client, application: FastAPI) -> Engine:
    return application.state.engine
