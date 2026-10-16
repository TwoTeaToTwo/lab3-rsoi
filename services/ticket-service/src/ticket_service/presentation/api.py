from collections.abc import Awaitable, Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Response
from pydantic import BaseModel

from ticket_service.application.service import TicketService
from ticket_service.presentation.schemas import (
    CreateTicketRequest,
    ErrorResponse,
    TicketResponse,
    ValidationErrorResponse,
)

Username = Annotated[
    str, Header(alias="X-User-Name", min_length=1, max_length=80, pattern=r".*\S.*")
]
TicketUid = Annotated[UUID, Path(alias="ticketUid")]


class HealthResponse(BaseModel):
    status: Literal["UP"] = "UP"


def create_router(
    service: TicketService, health_check: Callable[[], Awaitable[None]] | None = None
) -> APIRouter:
    router = APIRouter()
    errors: dict[int | str, dict[str, object]] = {
        400: {"model": ValidationErrorResponse},
        500: {"model": ErrorResponse},
    }
    ticket_errors: dict[int | str, dict[str, object]] = {**errors, 404: {"model": ErrorResponse}}

    @router.get("/manage/health", operation_id="getHealth", tags=["Management"])
    async def health() -> HealthResponse:
        if health_check is not None:
            await health_check()
        return HealthResponse()

    @router.get(
        "/internal/v1/tickets",
        operation_id="internalListTickets",
        tags=["Ticket Internal"],
        responses=errors,
    )
    async def list_tickets(username: Username) -> list[TicketResponse]:
        return [
            TicketResponse.from_domain(ticket) for ticket in await service.list_tickets(username)
        ]

    @router.get(
        "/internal/v1/tickets/{ticketUid}",
        operation_id="internalGetTicket",
        tags=["Ticket Internal"],
        responses=ticket_errors,
    )
    async def get_ticket(username: Username, ticket_uid: TicketUid) -> TicketResponse:
        return TicketResponse.from_domain(await service.get_ticket(username, ticket_uid))

    @router.put(
        "/internal/v1/tickets/{ticketUid}",
        operation_id="internalCreateTicket",
        tags=["Ticket Internal"],
        status_code=201,
        responses={**ticket_errors, 200: {"model": TicketResponse}, 409: {"model": ErrorResponse}},
    )
    async def create_ticket(
        username: Username, ticket_uid: TicketUid, body: CreateTicketRequest, response: Response
    ) -> TicketResponse:
        ticket, created = await service.create_ticket(
            username, ticket_uid, body.flight_number, body.price
        )
        response.status_code = 201 if created else 200
        return TicketResponse.from_domain(ticket)

    @router.put(
        "/internal/v1/tickets/{ticketUid}/cancellation",
        operation_id="internalCancelTicket",
        tags=["Ticket Internal"],
        status_code=204,
        response_class=Response,
        responses=ticket_errors,
    )
    async def cancel_ticket(username: Username, ticket_uid: TicketUid) -> Response:
        await service.cancel_ticket(username, ticket_uid)
        return Response(status_code=204)

    return router
