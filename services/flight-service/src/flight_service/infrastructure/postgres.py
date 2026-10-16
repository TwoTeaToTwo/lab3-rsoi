from __future__ import annotations

from types import TracebackType

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from flight_service.domain.models import Airport, Flight, FlightPage
from flight_service.infrastructure.orm import AirportRow, FlightRow


def to_airport(row: AirportRow) -> Airport:
    return Airport(row.id, row.name, row.city, row.country)


def to_domain(row: FlightRow) -> Flight:
    return Flight(
        row.id,
        row.flight_number,
        row.datetime,
        to_airport(row.from_airport),
        to_airport(row.to_airport),
        row.price,
    )


class PostgresRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_flights(self, page: int, size: int) -> FlightPage:
        total = (await self._session.scalars(select(func.count()).select_from(FlightRow))).one()
        rows = await self._session.scalars(
            select(FlightRow)
            .options(joinedload(FlightRow.from_airport), joinedload(FlightRow.to_airport))
            .order_by(FlightRow.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        return FlightPage(page, size, total, tuple(to_domain(row) for row in rows))

    async def get_flight(self, flight_number: str) -> Flight | None:
        row = await self._session.scalar(
            select(FlightRow)
            .options(joinedload(FlightRow.from_airport), joinedload(FlightRow.to_airport))
            .where(FlightRow.flight_number == flight_number)
        )
        return None if row is None else to_domain(row)


class PostgresUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._session: AsyncSession | None = None
        self._repository: PostgresRepository | None = None

    @property
    def repository(self) -> PostgresRepository:
        if self._repository is None:
            raise RuntimeError("Transaction is not active")
        return self._repository

    async def __aenter__(self) -> PostgresUnitOfWork:
        self._session = self._sessions()
        await self._session.begin()
        self._repository = PostgresRepository(self._session)
        return self

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Transaction is not active")
        await self._session.commit()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is not None:
            try:
                await self._session.rollback()
            finally:
                await self._session.close()
                self._session = None
                self._repository = None


class PostgresFlightReader:
    """Keep the existing application repository interface, with one UoW per read."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_flights(self, page: int, size: int) -> FlightPage:
        async with PostgresUnitOfWork(self._sessions) as transaction:
            return await transaction.repository.list_flights(page, size)

    async def get_flight(self, flight_number: str) -> Flight | None:
        async with PostgresUnitOfWork(self._sessions) as transaction:
            return await transaction.repository.get_flight(flight_number)
