import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from flight_service.application.service import FlightService
from flight_service.domain.errors import FlightNotFound
from flight_service.infrastructure.orm import FlightRow
from flight_service.infrastructure.postgres import PostgresFlightReader, PostgresRepository
from flight_service.presentation.schemas import FlightResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("FLIGHT_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("Set FLIGHT_TEST_DATABASE_URL to a migrated test database")
    engine = create_async_engine(url, isolation_level="REPEATABLE READ")
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_seeded_flight_and_airports_are_read_from_postgres(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service = FlightService(PostgresFlightReader(sessions))
    flight = await service.get_flight("AFL031")
    assert FlightResponse.from_domain(flight).model_dump(by_alias=True) == {
        "flightNumber": "AFL031",
        "fromAirport": "Санкт-Петербург Пулково",
        "toAirport": "Москва Шереметьево",
        "date": "2021-10-08 20:00",
        "price": 1500,
    }
    with pytest.raises(FlightNotFound):
        await service.get_flight(str(uuid4())[:20])
    assert await FlightService(PostgresFlightReader(sessions)).get_flight("AFL031") == flight


async def test_sql_pagination_orders_by_id_and_rollback_preserves_catalog(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    reader = PostgresFlightReader(sessions)
    baseline = await reader.list_flights(1, 100)
    async with sessions() as session:
        try:
            rows = [
                FlightRow(
                    flight_number=str(uuid4())[:20],
                    datetime=datetime(2030, 1, 1, tzinfo=UTC),
                    from_airport_id=2,
                    to_airport_id=1,
                    price=1000,
                )
                for _ in range(3)
            ]
            session.add_all(rows)
            await session.flush()
            repository = PostgresRepository(session)
            page = await repository.list_flights(baseline.total_elements + 2, 1)
            assert page.total_elements == baseline.total_elements + 3
            assert page.items[0].flight_number == rows[1].flight_number
            assert (await repository.list_flights(page.total_elements + 1, 1)).items == ()
        finally:
            await session.rollback()
    assert (await reader.list_flights(1, 100)) == baseline
