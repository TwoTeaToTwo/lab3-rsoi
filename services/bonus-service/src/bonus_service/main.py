import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bonus_service.application.service import BonusService
from bonus_service.config import Settings
from bonus_service.domain.errors import BonusError, InvalidInput, OperationConflict
from bonus_service.infrastructure.clock import SystemClock
from bonus_service.infrastructure.orm import PrivilegeRow
from bonus_service.infrastructure.postgres import PostgresUnitOfWork
from bonus_service.presentation.api import create_router
from bonus_service.presentation.schemas import (
    ErrorDescription,
    ErrorResponse,
    ValidationErrorResponse,
)

logger = logging.getLogger(__name__)


def create_app(service: BonusService | None = None) -> FastAPI:
    """Composition root. Tests may inject a use case backed by a separate store."""
    engine = None
    health_check = None
    if service is None:
        settings = Settings()
        engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            connect_args={"timeout": 5, "command_timeout": 10},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        service = BonusService(lambda: PostgresUnitOfWork(sessions), SystemClock())

        async def database_health() -> None:
            async with sessions() as session:
                await session.execute(select(PrivilegeRow.id).limit(1))

        health_check = database_health

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title="Bonus Service", version="0.1.0", lifespan=lifespan)
    app.include_router(create_router(service, health_check))

    async def database_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("Bonus database unavailable", exc_info=error)
        return JSONResponse(
            status_code=503, content=ErrorResponse(message="Service unavailable").model_dump()
        )

    for error_type in (OperationalError, InterfaceError, PoolTimeoutError, OSError, TimeoutError):
        app.add_exception_handler(error_type, database_error)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled Bonus Service error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(message="Internal server error").model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        body = ValidationErrorResponse(
            message="Validation failed",
            errors=[
                ErrorDescription(
                    field=".".join(str(part) for part in item["loc"][1:]), error=str(item["msg"])
                )
                for item in error.errors()
            ],
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(BonusError)
    async def business_error(request: Request, error: BonusError) -> JSONResponse:
        if isinstance(error, InvalidInput):
            body = ValidationErrorResponse(
                message="Validation failed",
                errors=[ErrorDescription(field=error.field, error=str(error))],
            )
            return JSONResponse(status_code=400, content=body.model_dump())
        code = 409 if isinstance(error, OperationConflict) else 404
        return JSONResponse(
            status_code=code, content=ErrorResponse(message=str(error)).model_dump()
        )

    # FastAPI normally documents 422; our contract maps request validation to 400.
    schema = app.openapi()
    for path in schema["paths"].values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)
    return app


def run() -> None:
    settings = Settings()
    uvicorn.run(create_app(), host=settings.host, port=settings.port, workers=1)


if __name__ == "__main__":
    run()
