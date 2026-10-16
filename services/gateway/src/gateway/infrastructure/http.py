import asyncio
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway.domain.errors import NotFound, Unavailable
from gateway.domain.models import Account, Flight, FlightPage, Payment, Ticket
from gateway.infrastructure.schemas import (
    AccountDTO,
    FlightDTO,
    FlightPageDTO,
    PaymentDTO,
    PrivilegeDTO,
    TicketDTO,
)


class HttpAdapter:
    def __init__(self, client: httpx.AsyncClient, retries: int = 2) -> None:
        self._client, self._retries = client, retries

    async def request(
        self,
        method: str,
        path: str,
        username: str | None = None,
        body: dict[str, object] | None = None,
        params: dict[str, int] | None = None,
    ) -> httpx.Response:
        for attempt in range(self._retries + 1):
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
                if response.status_code < 500:
                    if response.status_code >= 300:
                        raise Unavailable("Dependent service rejected the operation")
                    return response
            except httpx.RequestError:
                pass
            if attempt < self._retries:
                await asyncio.sleep(0.1 * (attempt + 1))
        raise Unavailable("Dependent service unavailable")

    async def read[T](
        self,
        schema: TypeAdapter[T],
        method: str,
        path: str,
        username: str | None = None,
        body: dict[str, object] | None = None,
        params: dict[str, int] | None = None,
    ) -> T:
        response = await self.request(method, path, username, body, params)
        try:
            return schema.validate_json(response.content)
        except ValidationError as error:
            raise Unavailable("Invalid dependent service response") from error


class HttpFlightClient(HttpAdapter):
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
            TypeAdapter(FlightDTO), "GET", "/internal/v1/flights/" + quote(number, safe="")
        )
        if result.flight_number != number:
            raise Unavailable("Invalid flight response")
        return result.to_domain()


class HttpTicketClient(HttpAdapter):
    async def list_tickets(self, username: str) -> tuple[Ticket, ...]:
        result = await self.read(
            TypeAdapter(list[TicketDTO]), "GET", "/internal/v1/tickets", username
        )
        return tuple(item.to_domain() for item in result)

    async def get_ticket(self, username: str, uid: UUID) -> Ticket:
        result = await self.read(
            TypeAdapter(TicketDTO), "GET", f"/internal/v1/tickets/{uid}", username
        )
        if result.ticket_uid != uid:
            raise Unavailable("Invalid ticket response")
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
            raise Unavailable("Invalid ticket response")
        return result.to_domain()

    async def cancel_ticket(self, username: str, uid: UUID) -> None:
        response = await self.request("PUT", f"/internal/v1/tickets/{uid}/cancellation", username)
        if response.status_code != 204 or response.content:
            raise Unavailable("Invalid cancellation response")


class HttpBonusClient(HttpAdapter):
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
