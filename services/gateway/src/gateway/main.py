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
from gateway.domain.errors import (
    GatewayError,
    InvalidInput,
    NotFound,
    ServiceName,
    UpstreamRejected,
    UpstreamUnavailable,
)
from gateway.infrastructure.circuit_breaker import CircuitBreaker
from gateway.infrastructure.http import HttpBonusClient, HttpFlightClient, HttpTicketClient
from gateway.infrastructure.rabbitmq import RabbitRefundQueue
from gateway.presentation.api import create_router
from gateway.presentation.schemas import ErrorDescription, ErrorDTO, ValidationErrorDTO

logger = logging.getLogger(__name__)


def create_app(service: GatewayService | None = None) -> FastAPI:
    clients: list[httpx.AsyncClient] = []
    breakers: dict[ServiceName, CircuitBreaker] = {}
    refund_queue: RabbitRefundQueue | None = None
    if service is None:
        settings = Settings()
        breakers = {
            name: CircuitBreaker(
                name, settings.circuit_breaker_n, settings.circuit_breaker_recovery_timeout
            )
            for name in ("Flight", "Ticket", "Bonus")
        }
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
        refund_queue = RabbitRefundQueue(
            settings.rabbitmq_url,
            settings.refund_queue,
            settings.refund_error_queue,
            retry_interval=settings.refund_retry_interval,
            timeout=settings.rabbitmq_timeout,
        )
        service = GatewayService(
            HttpFlightClient(clients[0], settings.retries, breaker=breakers["Flight"]),
            HttpTicketClient(clients[1], settings.retries, breaker=breakers["Ticket"]),
            HttpBonusClient(clients[2], settings.retries, breaker=breakers["Bonus"]),
            refund_queue,
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
        task: asyncio.Task[None] | None = None
        try:
            if refund_queue is not None:
                await refund_queue.start(gateway_service.process_refund)
            task = asyncio.create_task(recovery_loop())
            yield
        finally:
            try:
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                if refund_queue is not None:
                    await refund_queue.close()
            finally:
                for client in clients:
                    await client.aclose()

    app = FastAPI(title="Flight Booking Gateway", version="2.0.0", lifespan=lifespan)
    app.state.circuit_breakers = breakers
    app.state.refund_queue = refund_queue
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
        if isinstance(error, UpstreamRejected):
            if error.status_code == 400:
                validation = ValidationErrorDTO(
                    message="Validation failed",
                    errors=[ErrorDescription(field="request", error=str(error))],
                )
                return JSONResponse(status_code=400, content=validation.model_dump())
            return JSONResponse(
                status_code=error.status_code, content=ErrorDTO(message=str(error)).model_dump()
            )
        if isinstance(error, InvalidInput):
            body = ValidationErrorDTO(
                message="Validation failed",
                errors=[ErrorDescription(field=error.field, error=str(error))],
            )
            return JSONResponse(status_code=400, content=body.model_dump())
        status_code = 404 if isinstance(error, NotFound) else 503
        if isinstance(error, UpstreamUnavailable) and error.service != "Bonus":
            status_code = 500
        return JSONResponse(
            status_code=status_code,
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
