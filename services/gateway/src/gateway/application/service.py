import asyncio
import logging
from uuid import UUID, uuid4

from gateway.application.ports import BonusClient, FlightClient, TicketClient
from gateway.domain.errors import (
    InvalidInput,
    NotFound,
    Unavailable,
    UpstreamRejected,
    UpstreamUnavailable,
)
from gateway.domain.models import (
    Account,
    Flight,
    FlightPage,
    Privilege,
    PurchaseResult,
    Ticket,
    TicketInfo,
    UserInfo,
)

logger = logging.getLogger(__name__)


class GatewayService:
    def __init__(self, flights: FlightClient, tickets: TicketClient, bonus: BonusClient) -> None:
        self._flights, self._tickets, self._bonus = flights, tickets, bonus
        self._pending: dict[UUID, str] = {}

    async def list_flights(self, page: int, size: int) -> FlightPage:
        if page < 1 or not 1 <= size <= 100:
            raise InvalidInput("page", "Invalid pagination")
        return await self._flights.list_flights(page, size)

    async def get_privilege(self, username: str) -> Account:
        return await self._bonus.get_account(username)

    @staticmethod
    def _owned(ticket: Ticket, username: str) -> None:
        if ticket.username != username:
            raise NotFound("Ticket not found")

    @staticmethod
    def _info(ticket: Ticket, flight: Flight | None) -> TicketInfo:
        return TicketInfo(
            ticket.flight_number,
            flight.from_airport if flight is not None else "Unavailable",
            flight.to_airport if flight is not None else "Unavailable",
            flight.date if flight is not None else "Unavailable",
            ticket.price,
            ticket.ticket_uid,
            ticket.status,
        )

    async def _optional_flight(self, number: str) -> Flight | None:
        try:
            return await self._flights.get_flight(number)
        except Unavailable:
            return None

    async def _optional_privilege(self, username: str) -> Privilege | None:
        try:
            account = await self.get_privilege(username)
        except Unavailable:
            return None
        return Privilege(account.balance, account.status)

    async def get_ticket(self, username: str, uid: UUID) -> TicketInfo:
        ticket = await self._tickets.get_ticket(username, uid)
        self._owned(ticket, username)
        flight = await self._optional_flight(ticket.flight_number)
        return self._info(ticket, flight)

    async def list_tickets(self, username: str) -> tuple[TicketInfo, ...]:
        tickets = await self._tickets.list_tickets(username)
        for ticket in tickets:
            self._owned(ticket, username)
        numbers = list(dict.fromkeys(ticket.flight_number for ticket in tickets))
        flights = await asyncio.gather(*[self._optional_flight(number) for number in numbers])
        by_number = dict(zip(numbers, flights, strict=True))
        return tuple(self._info(ticket, by_number[ticket.flight_number]) for ticket in tickets)

    async def get_user(self, username: str) -> UserInfo:
        tickets, privilege = await asyncio.gather(
            self.list_tickets(username), self._optional_privilege(username)
        )
        return UserInfo(tickets, privilege)

    async def purchase(
        self, username: str, number: str, price: int, paid_from_balance: bool
    ) -> PurchaseResult:
        try:
            flight = await self._flights.get_flight(number)
        except NotFound as error:
            raise InvalidInput("flightNumber", "Flight not found") from error
        if flight.price != price:
            raise InvalidInput("price", "Price does not match the flight price")
        uid = uuid4()
        try:
            ticket = await self._tickets.create_ticket(username, uid, number, price)
            self._owned(ticket, username)
            if ticket.status != "PAID":
                raise UpstreamUnavailable("Ticket")
            payment = await self._bonus.apply_purchase(username, uid, price, paid_from_balance)
            if payment.ticket_uid != uid or payment.price != price:
                raise UpstreamUnavailable("Bonus")
            result = PurchaseResult(
                number,
                flight.from_airport,
                flight.to_airport,
                flight.date,
                price,
                uid,
                ticket.status,
                payment.paid_by_money,
                payment.paid_by_bonuses,
                payment.privilege,
            )
        except asyncio.CancelledError:
            self._pending[uid] = username
            raise
        except (Unavailable, NotFound, UpstreamRejected):
            self._pending[uid] = username
            await self._compensate(uid, username)
            raise
        else:
            self._pending.pop(uid, None)
            return result

    async def _compensate(self, uid: UUID, username: str) -> None:
        try:
            try:
                await self._tickets.cancel_ticket(username, uid)
            except NotFound:
                pass
            try:
                await self._bonus.reverse_purchase(username, uid)
            except NotFound:
                pass
        except Unavailable:
            logger.warning("Purchase compensation pending for %s", uid)
        else:
            self._pending.pop(uid, None)

    async def recover_pending(self) -> None:
        for uid, username in list(self._pending.items()):
            await self._compensate(uid, username)

    async def cancel(self, username: str, uid: UUID) -> None:
        ticket = await self._tickets.get_ticket(username, uid)
        self._owned(ticket, username)
        try:
            await self._bonus.reverse_purchase(username, uid)
        except NotFound as error:
            if ticket.status != "CANCELED":
                raise Unavailable("Bonus operation is missing") from error
        await self._tickets.cancel_ticket(username, uid)
