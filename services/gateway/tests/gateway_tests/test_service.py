from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from gateway.application.service import GatewayService
from gateway.domain.errors import InvalidInput, NotFound, Unavailable
from gateway.domain.models import Account, Flight, FlightPage, Payment, Privilege, Ticket
from gateway.infrastructure.http import HttpFlightClient, HttpTicketClient

FLIGHT = Flight("AFL031", "Санкт-Петербург Пулково", "Москва Шереметьево", "2021-10-08 20:00", 1500)


class Services:
    def __init__(self) -> None:
        self.tickets: dict[UUID, Ticket] = {}
        self.payments: dict[UUID, Payment] = {}
        self.reversed: set[UUID] = set()
        self.balance = 0
        self.fail_after_bonus = False
        self.fail_cancel = False

    async def list_flights(self, page: int, size: int) -> FlightPage:
        return FlightPage(page, size, 1, (FLIGHT,) if page == 1 else ())

    async def get_flight(self, number: str) -> Flight:
        if number != FLIGHT.flight_number:
            raise NotFound("Flight not found")
        return FLIGHT

    async def list_tickets(self, username: str) -> tuple[Ticket, ...]:
        return tuple(ticket for ticket in self.tickets.values() if ticket.username == username)

    async def get_ticket(self, username: str, uid: UUID) -> Ticket:
        if uid not in self.tickets:
            raise NotFound("Ticket not found")
        return self.tickets[uid]

    async def create_ticket(self, username: str, uid: UUID, number: str, price: int) -> Ticket:
        ticket = Ticket(uid, username, number, price, "PAID")
        self.tickets[uid] = ticket
        return ticket

    async def cancel_ticket(self, username: str, uid: UUID) -> None:
        if self.fail_cancel:
            raise Unavailable("Ticket unavailable")
        ticket = await self.get_ticket(username, uid)
        self.tickets[uid] = replace(ticket, status="CANCELED")

    async def get_account(self, username: str) -> Account:
        return Account(self.balance, "BRONZE", ())

    async def apply_purchase(
        self, username: str, uid: UUID, price: int, paid_from_balance: bool
    ) -> Payment:
        bonuses = min(price, self.balance) if paid_from_balance else 0
        self.balance += -bonuses if paid_from_balance else price // 10
        payment = Payment(uid, price, price - bonuses, bonuses, Privilege(self.balance, "BRONZE"))
        self.payments[uid] = payment
        if self.fail_after_bonus:
            raise Unavailable("Response lost after commit")
        return payment

    async def reverse_purchase(self, username: str, uid: UUID) -> None:
        if uid not in self.payments:
            raise NotFound("Operation not found")
        if uid not in self.reversed:
            payment = self.payments[uid]
            self.balance += payment.paid_by_bonuses or -min(self.balance, payment.price // 10)
            self.reversed.add(uid)


@pytest.fixture
def services() -> Services:
    return Services()


def gateway(services: Services) -> GatewayService:
    return GatewayService(services, services, services)


async def test_purchase_and_user_aggregation(services: Services) -> None:
    service = gateway(services)
    result = await service.purchase("alice", "AFL031", 1500, False)
    assert result.paid_by_money == 1500 and result.paid_by_bonuses == 0
    assert result.privilege.balance == 150
    user = await service.get_user("alice")
    assert user.privilege is not None and user.privilege.balance == 150
    assert len(user.tickets) == 1
    assert user.tickets[0].from_airport == FLIGHT.from_airport
    assert (await service.get_ticket("alice", result.ticket_uid)) == user.tickets[0]


async def test_invalid_flight_or_price_does_not_write(services: Services) -> None:
    service = gateway(services)
    with pytest.raises(InvalidInput):
        await service.purchase("alice", "UNKNOWN", 1500, False)
    with pytest.raises(InvalidInput):
        await service.purchase("alice", "AFL031", 1600, False)
    assert services.tickets == {} and services.payments == {}


async def test_bonus_purchase_and_repeated_refund(services: Services) -> None:
    services.balance = 500
    service = gateway(services)
    result = await service.purchase("alice", "AFL031", 1500, True)
    assert (result.paid_by_money, result.paid_by_bonuses) == (1000, 500)
    services.fail_cancel = True
    with pytest.raises(Unavailable):
        await service.cancel("alice", result.ticket_uid)
    services.fail_cancel = False
    await service.cancel("alice", result.ticket_uid)
    await service.cancel("alice", result.ticket_uid)
    assert services.balance == 500
    assert services.tickets[result.ticket_uid].status == "CANCELED"
    assert len(services.reversed) == 1


async def test_foreign_ticket_is_hidden_even_if_upstream_leaks_it(services: Services) -> None:
    service = gateway(services)
    result = await service.purchase("alice", "AFL031", 1500, False)
    with pytest.raises(NotFound):
        await service.get_ticket("bob", result.ticket_uid)
    with pytest.raises(NotFound):
        await service.cancel("bob", result.ticket_uid)
    assert services.tickets[result.ticket_uid].status == "PAID" and services.balance == 150


async def test_unknown_bonus_result_is_compensated_after_recovery(services: Services) -> None:
    services.fail_after_bonus = services.fail_cancel = True
    service = gateway(services)
    with pytest.raises(Unavailable):
        await service.purchase("alice", "AFL031", 1500, False)
    assert services.balance == 150
    services.fail_cancel = False
    await service.recover_pending()
    await service.recover_pending()
    assert services.balance == 0
    assert next(iter(services.tickets.values())).status == "CANCELED"
    assert len(services.reversed) == 1


async def test_http_retry_preserves_uuid_and_request_headers() -> None:
    uid = uuid4()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout("Unknown result", request=request)
        return httpx.Response(
            201,
            json={
                "ticketUid": str(uid),
                "username": request.headers["X-User-Name"],
                "flightNumber": "AFL031",
                "price": 1500,
                "status": "PAID",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ticket"
    ) as client:
        adapter = HttpTicketClient(client)
        await adapter.create_ticket("alice", uid, "AFL031", 1500)
        await adapter.create_ticket("bob", uid, "AFL031", 1500)
    assert len(requests) == 3
    assert requests[0].url == requests[1].url and requests[0].content == requests[1].content
    assert [r.headers["X-User-Name"] for r in requests] == ["alice", "alice", "bob"]
    assert "X-User-Name" not in client.headers


async def test_invalid_upstream_json_is_unavailable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"price": "bad"})),
        base_url="http://flight",
    ) as client:
        with pytest.raises(Unavailable):
            await HttpFlightClient(client).get_flight("AFL031")
