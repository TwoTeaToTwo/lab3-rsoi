from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Response
from pydantic import BaseModel

from gateway.application.service import GatewayService
from gateway.infrastructure.schemas import (
    AccountDTO,
    FlightPageDTO,
    PublicTicketDTO,
    PurchaseDTO,
    PurchaseRequest,
    UserDTO,
)

Username = Annotated[
    str, Header(alias="X-User-Name", min_length=1, max_length=80, pattern=r".*\S.*")
]
TicketUid = Annotated[UUID, Path(alias="ticketUid")]


class HealthDTO(BaseModel):
    status: Literal["UP"] = "UP"


class ErrorDescription(BaseModel):
    field: str
    error: str


class ErrorDTO(BaseModel):
    message: str


class ValidationErrorDTO(ErrorDTO):
    errors: list[ErrorDescription]


def create_router(service: GatewayService) -> APIRouter:
    router = APIRouter()
    errors: dict[int | str, dict[str, object]] = {
        400: {"model": ValidationErrorDTO},
        500: {"model": ErrorDTO},
        503: {"model": ErrorDTO},
    }
    ticket_errors: dict[int | str, dict[str, object]] = {**errors, 404: {"model": ErrorDTO}}

    @router.get("/manage/health", operation_id="getHealth")
    async def health() -> HealthDTO:
        return HealthDTO()

    @router.get("/api/v1/flights", operation_id="listFlights", responses=errors)
    async def flights(
        page: Annotated[int, Query(ge=1)] = 1,
        size: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> FlightPageDTO:
        return FlightPageDTO.model_validate(await service.list_flights(page, size))

    @router.get("/api/v1/tickets", operation_id="listUserTickets", responses=errors)
    async def tickets(username: Username) -> list[PublicTicketDTO]:
        return [
            PublicTicketDTO.model_validate(item) for item in await service.list_tickets(username)
        ]

    @router.get(
        "/api/v1/tickets/{ticketUid}", operation_id="getUserTicket", responses=ticket_errors
    )
    async def ticket(username: Username, ticket_uid: TicketUid) -> PublicTicketDTO:
        return PublicTicketDTO.model_validate(await service.get_ticket(username, ticket_uid))

    @router.post("/api/v1/tickets", operation_id="purchaseTicket", responses=errors)
    async def purchase(username: Username, body: PurchaseRequest) -> PurchaseDTO:
        return PurchaseDTO.model_validate(
            await service.purchase(username, body.flight_number, body.price, body.paid_from_balance)
        )

    @router.delete(
        "/api/v1/tickets/{ticketUid}",
        operation_id="cancelUserTicket",
        status_code=204,
        response_class=Response,
        responses=ticket_errors,
    )
    async def cancel(username: Username, ticket_uid: TicketUid) -> Response:
        await service.cancel(username, ticket_uid)
        return Response(status_code=204)

    @router.get("/api/v1/me", operation_id="getUserInfo", responses=errors)
    async def me(username: Username) -> UserDTO:
        return UserDTO.model_validate(await service.get_user(username))

    @router.get("/api/v1/privilege", operation_id="getUserPrivilege", responses=errors)
    async def privilege(username: Username) -> AccountDTO:
        return AccountDTO.model_validate(await service.get_privilege(username))

    return router
