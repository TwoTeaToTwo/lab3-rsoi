from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ticket_service.domain.models import Ticket, TicketStatus
from ticket_service.infrastructure.orm import TicketRow


def to_domain(row: TicketRow) -> Ticket:
    return Ticket(
        row.ticket_uid, row.username, row.flight_number, row.price, TicketStatus(row.status)
    )


class PostgresRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tickets(self, username: str) -> tuple[Ticket, ...]:
        rows = await self._session.scalars(
            select(TicketRow).where(TicketRow.username == username).order_by(TicketRow.id)
        )
        return tuple(to_domain(row) for row in rows)

    async def get_ticket(self, ticket_uid: UUID) -> Ticket | None:
        # A row lock alone cannot lock a UUID that has not yet been inserted.
        # Always acquire the transaction-scoped UUID lock before the row lock.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(ticket_uid)},
        )
        row = await self._session.scalar(
            select(TicketRow).where(TicketRow.ticket_uid == ticket_uid).with_for_update()
        )
        return None if row is None else to_domain(row)

    async def save_ticket(self, ticket: Ticket) -> None:
        # Repository callers must first get_ticket(), acquiring the UUID lock.
        row = await self._session.scalar(
            select(TicketRow).where(TicketRow.ticket_uid == ticket.ticket_uid)
        )
        if row is None:
            self._session.add(
                TicketRow(
                    ticket_uid=ticket.ticket_uid,
                    username=ticket.username,
                    flight_number=ticket.flight_number,
                    price=ticket.price,
                    status=ticket.status.value,
                )
            )
        else:
            row.status = ticket.status.value
        await self._session.flush()


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
