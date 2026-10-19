from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tariff

INITIAL_TARIFFS = (
    {"id": "basic", "title": "Basic", "price": 990_000},
    {"id": "standard", "title": "Standard", "price": 1_990_000},
    {"id": "premium", "title": "Premium", "price": 2_990_000},
)


def seed_tariffs(session: Session) -> None:
    for tariff in INITIAL_TARIFFS:
        try:
            with session.begin():
                session.add(Tariff(**tariff))
        except IntegrityError:
            with session.begin():
                if session.get(Tariff, tariff["id"]) is None:
                    raise
