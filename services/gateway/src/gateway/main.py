import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from gateway.application.service import GatewayService
from gateway.config import Settings
from gateway.domain.errors import GatewayError, InvalidInput, NotFound
from gateway.infrastructure.http import HttpBonusClient, HttpFlightClient, HttpTicketClient
from gateway.presentation.api import ErrorDescription, ErrorDTO, ValidationErrorDTO, create_router

logger = logging.getLogger(__name__)


def create_app(service: GatewayService | None = None) -> FastAPI:
    clients: list[httpx.AsyncClient] = []
    if service is None:
        settings = Settings()
        timeout = httpx.Timeout(
            connect=settings.connect_timeout,
            read=settings.read_timeout,
            write=settings.write_timeout,
            pool=settings.pool_timeout,
        )
        clients = [
            httpx.AsyncClient(base_url=url, timeout=timeout)
            for url in (settings.flight_url, settings.ticket_url, settings.bonus_url)
        ]
        service = GatewayService(
            HttpFlightClient(clients[0], settings.retries),
            HttpTicketClient(clients[1], settings.retries),
            HttpBonusClient(clients[2], settings.retries),
        )
    gateway_service = service

    async def recovery_loop() -> None:
        while True:
            await asyncio.sleep(1)
            try:
                await gateway_service.recover_pending()
            except Exception:
                logger.exception("Gateway recovery failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(recovery_loop())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            for client in clients:
                await client.aclose()

    app = FastAPI(title="Flight Booking Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(create_router(service))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        body = ValidationErrorDTO(
            message="Validation failed",
            errors=[
                ErrorDescription(
                    field=".".join(str(part) for part in item["loc"][1:]), error=str(item["msg"])
                )
                for item in error.errors()
            ],
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(GatewayError)
    async def business_error(request: Request, error: GatewayError) -> JSONResponse:
        if isinstance(error, InvalidInput):
            body = ValidationErrorDTO(
                message="Validation failed",
                errors=[ErrorDescription(field=error.field, error=str(error))],
            )
            return JSONResponse(status_code=400, content=body.model_dump())
        return JSONResponse(
            status_code=404 if isinstance(error, NotFound) else 503,
            content=ErrorDTO(message=str(error)).model_dump(),
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled Gateway error", exc_info=error)
        return JSONResponse(status_code=500, content={"message": "Internal server error"})

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
