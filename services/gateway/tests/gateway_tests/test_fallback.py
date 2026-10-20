import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from copy import deepcopy
from uuid import UUID

import httpx
import pytest
from gateway.application.service import GatewayService
from gateway.infrastructure.http import HttpBonusClient, HttpFlightClient, HttpTicketClient
from gateway.infrastructure.schemas import FlightDTO, PaymentDTO
from gateway.main import create_app
from gateway.presentation.schemas import PublicTicketDTO, PurchaseDTO, UserDTO
from pydantic import BaseModel, ValidationError

UID = UUID("049161bb-badd-4fa8-9d90-87c9a82b0668")
HEADERS = {"X-User-Name": "alice"}
FLIGHT: dict[str, object] = {
    "flightNumber": "AFL031",
    "fromAirport": "Санкт-Петербург Пулково",
    "toAirport": "Москва Шереметьево",
    "date": "2021-10-08 20:00",
    "price": 1500,
}
TICKET: dict[str, object] = {
    "ticketUid": str(UID),
    "username": "alice",
    "flightNumber": "AFL031",
    "price": 1500,
    "status": "PAID",
}
PRIVILEGE = {"balance": 150, "status": "BRONZE"}


class Backends:
    def __init__(self) -> None:
        self.overrides: dict[tuple[str, str], httpx.Response | httpx.RequestError] = {}
        self.calls: list[httpx.Request] = []
        self.tickets = [deepcopy(TICKET)]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host, path = request.url.host, request.url.path
        override = self.overrides.get((host, path))
        if isinstance(override, httpx.RequestError):
            raise override
        if override is not None:
            return override
        if host == "flight":
            if path == "/internal/v1/flights":
                return httpx.Response(
                    200, json={"page": 1, "pageSize": 10, "totalElements": 1, "items": [FLIGHT]}
                )
            return httpx.Response(200, json={**FLIGHT, "flightNumber": path.rsplit("/", 1)[1]})
        if host == "ticket":
            if path.endswith("/cancellation"):
                return httpx.Response(204)
            if request.method == "PUT":
                body = json.loads(request.content)
                return httpx.Response(
                    201,
                    json={**TICKET, **body, "ticketUid": path.rsplit("/", 1)[1]},
                )
            if path == "/internal/v1/tickets":
                return httpx.Response(200, json=self.tickets)
            return httpx.Response(200, json=self.tickets[0])
        if path == "/internal/v1/privilege":
            return httpx.Response(200, json={**PRIVILEGE, "history": []})
        return httpx.Response(503)


@pytest.fixture
async def api() -> AsyncIterator[tuple[httpx.AsyncClient, Backends]]:
    backends = Backends()
    async with AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=f"http://{host}", transport=httpx.MockTransport(backends.handle)
                )
            )
            for host in ("flight", "ticket", "bonus")
        ]
        service = GatewayService(
            HttpFlightClient(clients[0], retries=0),
            HttpTicketClient(clients[1], retries=0),
            HttpBonusClient(clients[2], retries=0),
        )
        client = await stack.enter_async_context(
            httpx.AsyncClient(
                base_url="http://gateway",
                transport=httpx.ASGITransport(app=create_app(service)),
                headers=HEADERS,
            )
        )
        yield client, backends


async def test_ticket_fallback_preserves_other_flights_and_ticket_fields(
    api: tuple[httpx.AsyncClient, Backends],
) -> None:
    client, backends = api
    backends.tickets.extend(
        [
            {**TICKET, "ticketUid": "149161bb-badd-4fa8-9d90-87c9a82b0668"},
            {
                **TICKET,
                "ticketUid": "249161bb-badd-4fa8-9d90-87c9a82b0668",
                "flightNumber": "AFL032",
                "price": 2000,
                "status": "CANCELED",
            },
        ]
    )
    backends.overrides["flight", "/internal/v1/flights/AFL031"] = httpx.Response(503)
    response = await client.get("/api/v1/tickets")
    assert response.status_code == 200
    first, duplicate, other = response.json()
    assert first == {
        **{key: value for key, value in TICKET.items() if key != "username"},
        "fromAirport": "Unavailable",
        "toAirport": "Unavailable",
        "date": "Unavailable",
    }
    assert duplicate["date"] == "Unavailable"
    assert other["date"] == FLIGHT["date"] and other["status"] == "CANCELED"
    assert other["price"] == 2000 and other["flightNumber"] == "AFL032"
    assert sum(request.url.host == "flight" for request in backends.calls) == 2
    assert (await client.get(f"/api/v1/tickets/{UID}")).json() == first


@pytest.mark.parametrize(
    "flight_down,bonus_down", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_user_fallback_and_empty_ticket_list(
    api: tuple[httpx.AsyncClient, Backends], flight_down: bool, bonus_down: bool
) -> None:
    client, backends = api
    if flight_down:
        backends.overrides["flight", "/internal/v1/flights/AFL031"] = httpx.Response(500)
    if bonus_down:
        backends.overrides["bonus", "/internal/v1/privilege"] = httpx.ConnectError("offline")
    response = await client.get("/api/v1/me")
    assert response.status_code == 200
    body = response.json()
    assert body["privilege"] == ({} if bonus_down else PRIVILEGE)
    assert body["tickets"][0]["date"] == ("Unavailable" if flight_down else FLIGHT["date"])
    UserDTO.model_validate(body)
    backends.tickets.clear()
    backends.calls.clear()
    response = await client.get("/api/v1/me")
    assert response.status_code == 200 and response.json()["tickets"] == []
    assert all(request.url.host != "flight" for request in backends.calls)


@pytest.mark.parametrize(
    "route,host,path,status",
    [
        ("/api/v1/flights", "flight", "/internal/v1/flights", 500),
        ("/api/v1/privilege", "bonus", "/internal/v1/privilege", 503),
        ("/api/v1/tickets", "ticket", "/internal/v1/tickets", 500),
        (f"/api/v1/tickets/{UID}", "ticket", f"/internal/v1/tickets/{UID}", 500),
        ("/api/v1/me", "ticket", "/internal/v1/tickets", 500),
    ],
)
async def test_critical_dependencies_return_errors(
    api: tuple[httpx.AsyncClient, Backends], route: str, host: str, path: str, status: int
) -> None:
    client, backends = api
    backends.overrides[host, path] = httpx.Response(503)
    response = await client.get(route)
    assert response.status_code == status
    assert response.json() == {"message": f"{host.title()} Service unavailable"}
    assert sum(request.url.host == host for request in backends.calls) == 1
    assert (await client.get("/manage/health")).json() == {"status": "UP"}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429])
async def test_business_errors_do_not_become_fallback(
    api: tuple[httpx.AsyncClient, Backends], status: int
) -> None:
    client, backends = api
    for host, path in [
        ("bonus", "/internal/v1/privilege"),
        ("flight", "/internal/v1/flights/AFL031"),
    ]:
        backends.overrides.clear()
        backends.calls.clear()
        backends.overrides[host, path] = httpx.Response(status, json={"message": "private details"})
        response = await client.get("/api/v1/me")
        assert response.status_code == status
        assert "privilege" not in response.json() and "private details" not in response.text
        assert sum(request.url.host == host for request in backends.calls) == 1


async def test_malformed_upstream_and_failed_purchase_do_not_return_success(
    api: tuple[httpx.AsyncClient, Backends],
) -> None:
    client, backends = api
    failures: list[httpx.Response | httpx.RequestError] = [
        httpx.ReadTimeout("timeout"),
        httpx.Response(200, content="not JSON"),
        httpx.Response(200, json={**FLIGHT, "date": "Unavailable"}),
        httpx.Response(200, json={**FLIGHT, "flightNumber": "WRONG"}),
    ]
    for failure in failures:
        backends.overrides["flight", "/internal/v1/flights/AFL031"] = failure
        response = await client.get(f"/api/v1/tickets/{UID}")
        assert response.status_code == 200 and response.json()["date"] == "Unavailable"
        response = await client.post(
            "/api/v1/tickets",
            json={"flightNumber": "AFL031", "price": 1500, "paidFromBalance": False},
        )
        assert response.status_code == 500
    backends.overrides.clear()
    response = await client.post(
        "/api/v1/tickets", json={"flightNumber": "AFL031", "price": 1500, "paidFromBalance": False}
    )
    assert response.status_code == 503
    assert response.json() == {"message": "Bonus Service unavailable"}
    assert any(request.url.path.endswith("/cancellation") for request in backends.calls)


def test_partial_models_do_not_weaken_strict_models() -> None:
    ticket = {**FLIGHT, "ticketUid": str(UID), "status": "PAID", "date": "Unavailable"}
    PublicTicketDTO.model_validate(ticket)
    with pytest.raises(ValidationError):
        FlightDTO.model_validate({**FLIGHT, "date": "Unavailable"})
    payment = {
        "ticketUid": str(UID),
        "price": 1500,
        "paidByMoney": 1500,
        "paidByBonuses": 0,
        "privilege": PRIVILEGE,
    }
    PurchaseDTO.model_validate({**FLIGHT, "status": "PAID", **payment})
    invalid: list[tuple[type[BaseModel], dict[str, object]]] = [
        (PurchaseDTO, {**ticket, **payment}),
        (PaymentDTO, {**payment, "privilege": {}}),
        (PurchaseDTO, {**FLIGHT, "status": "PAID", **payment, "privilege": {}}),
        (PublicTicketDTO, {**ticket, "date": "invalid date"}),
        (UserDTO, {"tickets": [], "privilege": None}),
        (UserDTO, {"tickets": [], "privilege": {"balance": 0}}),
    ]
    for schema, body in invalid:
        with pytest.raises(ValidationError):
            schema.model_validate(body)
