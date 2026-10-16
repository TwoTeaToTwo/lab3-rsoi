from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel

from flight_service.application.service import FlightService
from flight_service.presentation.schemas import (
    ErrorResponse,
    FlightPageResponse,
    FlightResponse,
    ValidationErrorResponse,
)


class HealthResponse(BaseModel):
    status: Literal["UP"] = "UP"


def create_router(
    service: FlightService, health_check: Callable[[], Awaitable[None]] | None = None
) -> APIRouter:
    router = APIRouter()

    @router.get("/manage/health", operation_id="getHealth", tags=["Management"])
    async def health() -> HealthResponse:
        if health_check is not None:
            await health_check()
        return HealthResponse()

    @router.get(
        "/internal/v1/flights",
        operation_id="internalListFlights",
        tags=["Flight Internal"],
        responses={400: {"model": ValidationErrorResponse}, 500: {"model": ErrorResponse}},
    )
    async def list_flights(
        page: Annotated[int, Query(ge=1)] = 1,
        size: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> FlightPageResponse:
        return FlightPageResponse.from_domain(await service.list_flights(page, size))

    @router.get(
        "/internal/v1/flights/{flightNumber}",
        operation_id="internalGetFlight",
        tags=["Flight Internal"],
        responses={
            400: {"model": ValidationErrorResponse},
            404: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    async def get_flight(
        flight_number: Annotated[
            str, Path(alias="flightNumber", min_length=1, max_length=20, pattern=r".*\S.*")
        ],
    ) -> FlightResponse:
        return FlightResponse.from_domain(await service.get_flight(flight_number))

    return router
