from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from math import isfinite

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import build_engine
from app.routers import payments, tariffs, webhooks
from app.seed import seed_tariffs
from app.services import InvalidTransitionError, NotFoundError


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured = settings if settings is not None else Settings()
        engine = build_engine(configured.database_url)
        application.state.settings = configured
        application.state.engine = engine
        application.state.session_factory = sessionmaker(engine, expire_on_commit=False)
        try:
            with application.state.session_factory() as session:
                seed_tariffs(session)
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title="Квитто: API платежей",
        description="Оплата курсов, промокод и рассрочка. Все денежные суммы указаны в копейках.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.include_router(tariffs.router)
    application.include_router(payments.router)
    application.include_router(webhooks.router)

    @application.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(InvalidTransitionError)
    async def invalid_transition(request: Request, exc: InvalidTransitionError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": "invalid_transition"})

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # NaN/Infinity в ошибочном вводе не должны ломать сериализацию стандартного ответа 422.
        errors = jsonable_encoder(
            exc.errors(),
            custom_encoder={float: lambda value: value if isfinite(value) else str(value)},
        )
        return JSONResponse(status_code=422, content={"detail": errors})

    return application


app = create_app()
