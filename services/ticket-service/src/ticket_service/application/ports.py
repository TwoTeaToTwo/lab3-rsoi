from __future__ import annotations

from types import TracebackType
from typing import Protocol
from uuid import UUID

from ticket_service.domain.models import Ticket


class TicketRepository(Protocol):
    async def list_tickets(self, username: str) -> tuple[Ticket, ...]: ...

    async def get_ticket(self, ticket_uid: UUID) -> Ticket | None: ...

    async def save_ticket(self, ticket: Ticket) -> None: ...


class UnitOfWork(Protocol):
    @property
    def repository(self) -> TicketRepository: ...

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
