import hashlib
import hmac
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.routing import APIRoute

from app import services
from app.database import SessionDependency
from app.schemas import BankWebhook, TransitionErrorResponse, WebhookResponse


class SignedWebhookRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original_handler = super().get_route_handler()

        async def signed_handler(request: Request) -> Response:
            body = await request.body()
            secret = request.app.state.settings.webhook_secret.get_secret_value()
            expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            signature = request.headers.get("X-Signature", "")
            if not hmac.compare_digest(signature.lower().encode("utf-8"), expected.encode("ascii")):
                raise HTTPException(status_code=401, detail="Недействительная подпись")
            return await original_handler(request)

        return signed_handler


router = APIRouter(prefix="/webhooks", tags=["Уведомления банка"], route_class=SignedWebhookRoute)


@router.post(
    "/bank",
    response_model=WebhookResponse,
    responses={
        401: {"description": "Подпись отсутствует или неверна"},
        404: {"description": "Платёж не найден"},
        409: {"model": TransitionErrorResponse, "description": "Запрещённый переход статуса"},
    },
    openapi_extra={
        "parameters": [
            {
                "name": "X-Signature",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
                "description": "HMAC-SHA256 исходного тела запроса, 64 hex-символа",
            }
        ]
    },
    summary="Принять уведомление банка",
)
def bank_webhook(data: BankWebhook, session: SessionDependency) -> WebhookResponse:
    services.change_payment_status(session, data.payment_id, data.status)
    return WebhookResponse()
