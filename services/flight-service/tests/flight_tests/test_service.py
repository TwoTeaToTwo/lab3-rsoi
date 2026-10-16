from dataclasses import replace

import pytest
from flight_service.application.service import FlightService
from flight_service.domain.errors import FlightNotFound, InvalidInput
from flight_service.infrastructure.memory import InMemoryFlightRepository, create_seeded_repository


@pytest.fixture
def service() -> FlightService:
    return FlightService(create_seeded_repository())


async def test_default_page_contains_seeded_flight(service: FlightService) -> None:
    page = await service.list_flights()
    assert (page.page, page.page_size, page.total_elements) == (1, 10, 1)
    flight = page.items[0]
    assert flight.flight_number == "AFL031"
    assert flight.price == 1500
    assert flight.from_airport.city == "Санкт-Петербург"
    assert flight.to_airport.city == "Москва"


async def test_pagination_sorts_by_id(service: FlightService) -> None:
    first = await service.get_flight("AFL031")
    second = replace(first, id=2, flight_number="AFL032")
    third = replace(first, id=3, flight_number="AFL033")
    catalog = FlightService(InMemoryFlightRepository((third, first, second)))
    page = await catalog.list_flights(page=2, size=1)
    assert page.items == (second,)
    assert (page.page, page.page_size, page.total_elements) == (2, 1, 3)


async def test_page_beyond_catalog_is_empty(service: FlightService) -> None:
    page = await service.list_flights(page=2)
    assert page.items == ()
    assert page.total_elements == 1


async def test_invalid_page_is_rejected(service: FlightService) -> None:
    with pytest.raises(InvalidInput) as error:
        await service.list_flights(page=0)
    assert error.value.field == "page"


async def test_invalid_size_is_rejected(service: FlightService) -> None:
    with pytest.raises(InvalidInput) as error:
        await service.list_flights(size=101)
    assert error.value.field == "size"


async def test_get_flight_by_number(service: FlightService) -> None:
    flight = await service.get_flight("AFL031")
    assert flight == (await service.list_flights()).items[0]
    assert flight.datetime.isoformat() == "2021-10-08T20:00:00+03:00"


async def test_unknown_flight_is_not_found(service: FlightService) -> None:
    with pytest.raises(FlightNotFound):
        await service.get_flight("UNKNOWN")
