from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from flight_service.domain.models import Airport, Flight, FlightPage


class InMemoryFlightRepository:
    def __init__(self, flights: Iterable[Flight]) -> None:
        self._flights = tuple(sorted(flights, key=lambda flight: flight.id))
        self._by_number = {flight.flight_number: flight for flight in self._flights}
        if len(self._by_number) != len(self._flights):
            raise ValueError("Flight numbers must be unique")

    async def list_flights(self, page: int, size: int) -> FlightPage:
        start = (page - 1) * size
        return FlightPage(page, size, len(self._flights), self._flights[start : start + size])

    async def get_flight(self, flight_number: str) -> Flight | None:
        return self._by_number.get(flight_number)


def create_seeded_repository() -> InMemoryFlightRepository:
    sheremetyevo = Airport(1, "Шереметьево", "Москва", "Россия")
    pulkovo = Airport(2, "Пулково", "Санкт-Петербург", "Россия")
    return InMemoryFlightRepository(
        (
            Flight(
                id=1,
                flight_number="AFL031",
                datetime=datetime(2021, 10, 8, 20, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                from_airport=pulkovo,
                to_airport=sheremetyevo,
                price=1500,
            ),
        )
    )
