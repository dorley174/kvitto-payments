from fastapi import APIRouter

from app import services
from app.database import SessionDependency
from app.models import Tariff
from app.schemas import TariffResponse

router = APIRouter(prefix="/tariffs", tags=["Тарифы"])


@router.get("", response_model=list[TariffResponse], summary="Список тарифов")
def get_tariffs(session: SessionDependency) -> list[Tariff]:
    return services.list_tariffs(session)
