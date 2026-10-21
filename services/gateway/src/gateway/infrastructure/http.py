import asyncio
from collections.abc import Callable
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway.domain.errors import NotFound, ServiceName, UpstreamRejected, UpstreamUnavailable
from gateway.domain.models import Account, Flight, FlightPage, Payment, Ticket
from gateway.infrastructure.circuit_breaker import CircuitBreaker
from gateway.infrastructure.schemas import (
    AccountDTO,
    FlightDTO,
    FlightPageDTO,
    PaymentDTO,
    PrivilegeDTO,
    TicketDTO,
)


class HttpAdapter:
    service_name: ServiceName

    def __init__(
        self,
        client: httpx.AsyncClient,
        retries: int = 2,
        *,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._client, self._retries = client, retries
        self._breaker = breaker

    async def request(
        self,
        method: str,
        path: str,
        username: str | None = None,
        body: dict[str, object] | None = None,
        params: dict[str, int] | None = None,
    ) -> httpx.Response:
        retries = 0 if method == "GET" else self._retries
        for attempt in range(retries + 1):
            try:
                response = await self._client.request(
                    method,
                    path,
                    headers={} if username is None else {"X-User-Name": username},
                    json=body,
                    params=params,
                )
                if response.status_code == 404:
                    raise NotFound("Resource not found")
                if 400 <= response.status_code < 500:
                    raise UpstreamRejected(self.service_name, response.status_code)
                if 200 <= response.status_code < 300:
                    return response
            except httpx.RequestError:
                pass
            if attempt < retries:
                await asyncio.sleep(0.1 * (attempt + 1))
        raise UpstreamUnavailable(self.service_name)

    async def read[T](
        self,
        schema: TypeAdapter[T],
        method: str,
        path: str,
        username: str | None = None,
        body: dict[str, object] | None = None,
        params: dict[str, int] | None = None,
        *,
        validate: Callable[[T], bool] | None = None,
    ) -> T:
        async def execute() -> T:
            response = await self.request(method, path, username, body, params)
            try:
                result = schema.validate_json(response.content)
            except ValidationError as error:
                raise UpstreamUnavailable(self.service_name) from error
            if validate is not None and not validate(result):
                raise UpstreamUnavailable(self.service_name)
            return result

        if method == "GET" and self._breaker is not None:
            return await self._breaker.call(execute)
        return await execute()


class HttpFlightClient(HttpAdapter):
    service_name: ServiceName = "Flight"

    async def list_flights(self, page: int, size: int) -> FlightPage:
        result = await self.read(
            TypeAdapter(FlightPageDTO),
            "GET",
            "/internal/v1/flights",
            params={"page": page, "size": size},
        )
        return result.to_domain()

    async def get_flight(self, number: str) -> Flight:
        result = await self.read(
            TypeAdapter(FlightDTO),
            "GET",
            "/internal/v1/flights/" + quote(number, safe=""),
            validate=lambda result: result.flight_number == number,
        )
        return result.to_domain()


class HttpTicketClient(HttpAdapter):
    service_name: ServiceName = "Ticket"

    async def list_tickets(self, username: str) -> tuple[Ticket, ...]:
        result = await self.read(
            TypeAdapter(list[TicketDTO]), "GET", "/internal/v1/tickets", username
        )
        return tuple(item.to_domain() for item in result)

    async def get_ticket(self, username: str, uid: UUID) -> Ticket:
        result = await self.read(
            TypeAdapter(TicketDTO),
            "GET",
            f"/internal/v1/tickets/{uid}",
            username,
            validate=lambda result: result.ticket_uid == uid,
        )
        return result.to_domain()

    async def create_ticket(self, username: str, uid: UUID, number: str, price: int) -> Ticket:
        result = await self.read(
            TypeAdapter(TicketDTO),
            "PUT",
            f"/internal/v1/tickets/{uid}",
            username,
            {"flightNumber": number, "price": price},
        )
        if result.ticket_uid != uid or result.flight_number != number or result.price != price:
            raise UpstreamUnavailable(self.service_name)
        return result.to_domain()

    async def cancel_ticket(self, username: str, uid: UUID) -> None:
        response = await self.request("PUT", f"/internal/v1/tickets/{uid}/cancellation", username)
        if response.status_code != 204 or response.content:
            raise UpstreamUnavailable(self.service_name)


class HttpBonusClient(HttpAdapter):
    service_name: ServiceName = "Bonus"

    async def get_account(self, username: str) -> Account:
        return (
            await self.read(TypeAdapter(AccountDTO), "GET", "/internal/v1/privilege", username)
        ).to_account()

    async def apply_purchase(
        self, username: str, uid: UUID, price: int, paid_from_balance: bool
    ) -> Payment:
        return (
            await self.read(
                TypeAdapter(PaymentDTO),
                "PUT",
                f"/internal/v1/privilege/operations/{uid}",
                username,
                {"price": price, "paidFromBalance": paid_from_balance},
            )
        ).to_domain()

    async def reverse_purchase(self, username: str, uid: UUID) -> None:
        await self.read(
            TypeAdapter(PrivilegeDTO),
            "PUT",
            f"/internal/v1/privilege/operations/{uid}/reversal",
            username,
        )
