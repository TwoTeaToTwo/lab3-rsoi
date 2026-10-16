from __future__ import annotations

from types import TracebackType
from typing import Protocol

from flight_service.domain.models import Flight, FlightPage


class FlightRepository(Protocol):
    async def list_flights(self, page: int, size: int) -> FlightPage: ...

    async def get_flight(self, flight_number: str) -> Flight | None: ...


class UnitOfWork(Protocol):
    @property
    def repository(self) -> FlightRepository: ...

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...
