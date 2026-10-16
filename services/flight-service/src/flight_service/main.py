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

from flight_service.application.service import FlightService
from flight_service.config import Settings
from flight_service.domain.errors import FlightNotFound, InvalidInput
from flight_service.infrastructure.orm import FlightRow
from flight_service.infrastructure.postgres import PostgresFlightReader
from flight_service.presentation.api import create_router
from flight_service.presentation.schemas import (
    ErrorDescription,
    ErrorResponse,
    ValidationErrorResponse,
)

logger = logging.getLogger(__name__)


def create_app(service: FlightService | None = None) -> FastAPI:
    engine = None
    health_check = None
    if service is None:
        settings = Settings()
        engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            isolation_level="REPEATABLE READ",
            connect_args={"timeout": 5, "command_timeout": 10},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        service = FlightService(PostgresFlightReader(sessions))

        async def database_health() -> None:
            async with sessions() as session:
                await session.execute(select(FlightRow.id).limit(1))

        health_check = database_health

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title="Flight Service", version="0.1.0", lifespan=lifespan)
    app.include_router(create_router(service, health_check))

    async def database_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("Flight database unavailable", exc_info=error)
        return JSONResponse(
            status_code=503, content=ErrorResponse(message="Service unavailable").model_dump()
        )

    for error_type in (OperationalError, InterfaceError, PoolTimeoutError, OSError, TimeoutError):
        app.add_exception_handler(error_type, database_error)

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

    @app.exception_handler(InvalidInput)
    async def invalid_input(request: Request, error: InvalidInput) -> JSONResponse:
        body = ValidationErrorResponse(
            message="Validation failed",
            errors=[ErrorDescription(field=error.field, error=str(error))],
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(FlightNotFound)
    async def not_found(request: Request, error: FlightNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=ErrorResponse(message=str(error)).model_dump())

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled Flight Service error", exc_info=error)
        return JSONResponse(
            status_code=500, content=ErrorResponse(message="Internal server error").model_dump()
        )

    schema = app.openapi()
    for path in schema["paths"].values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)
    return app


def run() -> None:
    settings = Settings()
    uvicorn.run(create_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
