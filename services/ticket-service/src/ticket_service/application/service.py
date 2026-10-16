from uuid import UUID

from ticket_service.application.ports import UnitOfWorkFactory
from ticket_service.domain.errors import TicketConflict, TicketNotFound
from ticket_service.domain.models import Ticket, validate_purchase, validate_username


class TicketService:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def list_tickets(self, username: str) -> tuple[Ticket, ...]:
        validate_username(username)
        async with self._unit_of_work() as transaction:
            return await transaction.repository.list_tickets(username)

    async def get_ticket(self, username: str, ticket_uid: UUID) -> Ticket:
        validate_username(username)
        async with self._unit_of_work() as transaction:
            ticket = await transaction.repository.get_ticket(ticket_uid)
            if ticket is None or ticket.username != username:
                raise TicketNotFound("Ticket not found")
            return ticket

    async def create_ticket(
        self, username: str, ticket_uid: UUID, flight_number: str, price: int
    ) -> tuple[Ticket, bool]:
        validate_username(username)
        validate_purchase(flight_number, price)
        async with self._unit_of_work() as transaction:
            existing = await transaction.repository.get_ticket(ticket_uid)
            if existing is not None:
                if existing.username != username:
                    raise TicketNotFound("Ticket not found")
                if existing.flight_number != flight_number or existing.price != price:
                    raise TicketConflict("Ticket already used with different purchase parameters")
                return existing, False
            ticket = Ticket(ticket_uid, username, flight_number, price)
            await transaction.repository.save_ticket(ticket)
            await transaction.commit()
            return ticket, True

    async def cancel_ticket(self, username: str, ticket_uid: UUID) -> None:
        validate_username(username)
        async with self._unit_of_work() as transaction:
            ticket = await transaction.repository.get_ticket(ticket_uid)
            if ticket is None or ticket.username != username:
                raise TicketNotFound("Ticket not found")
            await transaction.repository.save_ticket(ticket.cancel())
            await transaction.commit()
