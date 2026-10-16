from __future__ import annotations

import asyncio
from types import TracebackType
from uuid import UUID

from ticket_service.domain.models import Ticket


class InMemoryRepository:
    def __init__(self, tickets: dict[UUID, Ticket]) -> None:
        self._tickets = tickets

    async def list_tickets(self, username: str) -> tuple[Ticket, ...]:
        # Dict insertion order represents the stable creation/id order.
        return tuple(ticket for ticket in self._tickets.values() if ticket.username == username)

    async def get_ticket(self, ticket_uid: UUID) -> Ticket | None:
        return self._tickets.get(ticket_uid)

    async def save_ticket(self, ticket: Ticket) -> None:
        self._tickets[ticket.ticket_uid] = ticket

    def snapshot(self) -> dict[UUID, Ticket]:
        return self._tickets.copy()


class InMemoryStore:
    def __init__(self) -> None:
        self.tickets: dict[UUID, Ticket] = {}
        self.lock = asyncio.Lock()

    def transaction(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self)


class InMemoryUnitOfWork:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self._repository: InMemoryRepository | None = None

    @property
    def repository(self) -> InMemoryRepository:
        if self._repository is None:
            raise RuntimeError("Transaction is not active")
        return self._repository

    async def __aenter__(self) -> InMemoryUnitOfWork:
        await self._store.lock.acquire()
        self._repository = InMemoryRepository(self._store.tickets.copy())
        return self

    async def commit(self) -> None:
        self._store.tickets = self.repository.snapshot()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._repository = None
        self._store.lock.release()
