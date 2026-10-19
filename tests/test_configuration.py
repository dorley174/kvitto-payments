import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.helpers import WEBHOOK_SECRET


def test_webhook_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    with pytest.raises(ValidationError):
        Settings(database_url="sqlite://", _env_file=None)


@pytest.mark.parametrize("secret", ["", " ", "\t"])
def test_webhook_secret_cannot_be_blank(secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite://", webhook_secret=secret, _env_file=None)


@pytest.mark.parametrize(
    "database_url",
    [
        "not-a-database-url",
        "",
        "mysql+pymysql://localhost/kvitto",
        "sqlite+aiosqlite:///:memory:",
        "postgresql+asyncpg://localhost/kvitto",
    ],
)
def test_invalid_database_url_returns_settings_validation_error(database_url: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(database_url=database_url, webhook_secret=WEBHOOK_SECRET, _env_file=None)

    assert error.value.errors()[0]["loc"] == ("database_url",)


def test_postgresql_url_uses_supported_psycopg_driver() -> None:
    settings = Settings(
        database_url="postgresql://localhost/kvitto",
        webhook_secret=WEBHOOK_SECRET,
        _env_file=None,
    )

    assert settings.database_url == "postgresql+psycopg://localhost/kvitto"
