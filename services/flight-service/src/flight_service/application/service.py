from flight_service.application.ports import FlightRepository
from flight_service.domain.errors import FlightNotFound, InvalidInput
from flight_service.domain.models import Flight, FlightPage


class FlightService:
    def __init__(self, repository: FlightRepository) -> None:
        self._repository = repository

    async def list_flights(self, page: int = 1, size: int = 10) -> FlightPage:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise InvalidInput("page", "Page must be a positive integer")
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 100:
            raise InvalidInput("size", "Size must be an integer from 1 to 100")
        return await self._repository.list_flights(page, size)

    async def get_flight(self, flight_number: str) -> Flight:
        if not flight_number.strip() or len(flight_number) > 20:
            raise InvalidInput("flightNumber", "Flight number must contain 1 to 20 characters")
        flight = await self._repository.get_flight(flight_number)
        if flight is None:
            raise FlightNotFound("Flight not found")
        return flight
