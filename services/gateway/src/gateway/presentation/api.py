from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Response

from gateway.application.service import GatewayService
from gateway.presentation.schemas import (
    AccountDTO,
    BonusUnavailableDTO,
    ErrorDTO,
    FlightPageDTO,
    HealthDTO,
    PublicTicketDTO,
    PurchaseDTO,
    PurchaseRequest,
    UserDTO,
    ValidationErrorDTO,
)

Username = Annotated[
    str, Header(alias="X-User-Name", min_length=1, max_length=80, pattern=r".*\S.*")
]
TicketUid = Annotated[UUID, Path(alias="ticketUid")]


def create_router(service: GatewayService) -> APIRouter:
    router = APIRouter()
    errors: dict[int | str, dict[str, object]] = {
        400: {"model": ValidationErrorDTO},
        500: {"model": ErrorDTO},
        "4XX": {"model": ErrorDTO, "description": "Зависимый сервис отклонил запрос"},
    }
    ticket_errors: dict[int | str, dict[str, object]] = {**errors, 404: {"model": ErrorDTO}}
    bonus_errors: dict[int | str, dict[str, object]] = {
        **errors,
        503: {"model": BonusUnavailableDTO},
    }

    @router.get("/manage/health", operation_id="getHealth")
    async def health() -> HealthDTO:
        return HealthDTO()

    @router.get(
        "/api/v1/flights",
        operation_id="listFlights",
        responses=errors,
        description="Недоступный Flight Service возвращает 500; fallback рейсов не используется.",
    )
    async def flights(
        page: Annotated[int, Query(ge=1)] = 1,
        size: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> FlightPageDTO:
        return FlightPageDTO.model_validate(await service.list_flights(page, size))

    @router.get(
        "/api/v1/tickets",
        operation_id="listUserTickets",
        responses=errors,
        description="Недоступный Ticket возвращает 500. При отказе Flight билеты сохраняются, "
        'fromAirport, toAirport и date недоступных рейсов равны "Unavailable".',
    )
    async def tickets(username: Username) -> list[PublicTicketDTO]:
        return [
            PublicTicketDTO.model_validate(item) for item in await service.list_tickets(username)
        ]

    @router.get(
        "/api/v1/tickets/{ticketUid}",
        operation_id="getUserTicket",
        responses=ticket_errors,
        description="Недоступный Ticket возвращает 500. При отказе Flight сохраняются поля билета, "
        'fromAirport, toAirport и date равны "Unavailable". Чужой или отсутствующий билет — 404.',
    )
    async def ticket(username: Username, ticket_uid: TicketUid) -> PublicTicketDTO:
        return PublicTicketDTO.model_validate(await service.get_ticket(username, ticket_uid))

    @router.post("/api/v1/tickets", operation_id="purchaseTicket", responses=bonus_errors)
    async def purchase(username: Username, body: PurchaseRequest) -> PurchaseDTO:
        return PurchaseDTO.model_validate(
            await service.purchase(username, body.flight_number, body.price, body.paid_from_balance)
        )

    @router.delete(
        "/api/v1/tickets/{ticketUid}",
        operation_id="cancelUserTicket",
        status_code=204,
        response_class=Response,
        responses={**ticket_errors, 503: {"model": ErrorDTO}},
        description="Сначала билет отменяется в Ticket, затем отменяется бонусная операция. "
        "При временном отказе Bonus задание публикуется в RabbitMQ с подтверждением, "
        "после чего возвращается 204. "
        "Gateway повторяет бонусный возврат через очередь до успеха с интервалом 10 секунд. "
        "При ошибке публикации возвращается 503; повторный DELETE безопасен.",
    )
    async def cancel(username: Username, ticket_uid: TicketUid) -> Response:
        await service.cancel(username, ticket_uid)
        return Response(status_code=204)

    @router.get(
        "/api/v1/me",
        operation_id="getUserInfo",
        responses=errors,
        description="Недоступный Ticket возвращает 500. При отказе Flight используются заглушки "
        '"Unavailable" в билетах, при отказе Bonus возвращается privilege: {}. '
        "Оба fallback могут применяться одновременно, статус ответа — 200.",
    )
    async def me(username: Username) -> UserDTO:
        return UserDTO.from_domain(await service.get_user(username))

    @router.get(
        "/api/v1/privilege",
        operation_id="getUserPrivilege",
        responses=bonus_errors,
        description='Недоступный Bonus возвращает 503 с message="Bonus Service unavailable".',
    )
    async def privilege(username: Username) -> AccountDTO:
        return AccountDTO.model_validate(await service.get_privilege(username))

    return router
