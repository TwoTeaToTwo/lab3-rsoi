from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Response, status

from bonus_service.application.service import BonusService
from bonus_service.presentation.schemas import (
    AccountResponse,
    ErrorResponse,
    HealthResponse,
    PaymentResponse,
    PrivilegeResponse,
    PurchaseRequest,
    ValidationErrorResponse,
)

Username = Annotated[
    str, Header(alias="X-User-Name", min_length=1, max_length=80, pattern=r".*\S.*")
]


def create_router(
    service: BonusService, health_check: Callable[[], Awaitable[None]] | None = None
) -> APIRouter:
    router = APIRouter()

    def get_service() -> BonusService:
        return service

    @router.get(
        "/manage/health",
        response_model=HealthResponse,
        tags=["Management"],
        operation_id="getHealth",
    )
    async def health() -> HealthResponse:
        if health_check is not None:
            await health_check()
        return HealthResponse()

    @router.get(
        "/internal/v1/privilege",
        response_model=AccountResponse,
        operation_id="internalGetPrivilege",
        responses={400: {"model": ValidationErrorResponse}},
        tags=["Bonus Internal"],
    )
    async def get_privilege(
        username: Username, bonus: Annotated[BonusService, Depends(get_service)]
    ) -> AccountResponse:
        return AccountResponse.from_account(await bonus.get_account(username))

    @router.put(
        "/internal/v1/privilege/operations/{ticketUid}",
        response_model=PaymentResponse,
        operation_id="internalApplyBonusOperation",
        status_code=status.HTTP_201_CREATED,
        responses={
            200: {"model": PaymentResponse},
            400: {"model": ValidationErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
        tags=["Bonus Internal"],
    )
    async def apply_purchase(
        ticket_uid: Annotated[UUID, Path(alias="ticketUid")],
        body: PurchaseRequest,
        username: Username,
        response: Response,
        bonus: Annotated[BonusService, Depends(get_service)],
    ) -> PaymentResponse:
        result, created = await bonus.apply_purchase(
            username, ticket_uid, body.price, body.paid_from_balance
        )
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return PaymentResponse.from_domain(result)

    @router.put(
        "/internal/v1/privilege/operations/{ticketUid}/reversal",
        response_model=PrivilegeResponse,
        operation_id="internalReverseBonusOperation",
        responses={400: {"model": ValidationErrorResponse}, 404: {"model": ErrorResponse}},
        tags=["Bonus Internal"],
    )
    async def reverse_purchase(
        ticket_uid: Annotated[UUID, Path(alias="ticketUid")],
        username: Username,
        bonus: Annotated[BonusService, Depends(get_service)],
    ) -> PrivilegeResponse:
        return PrivilegeResponse.from_domain(await bonus.reverse_purchase(username, ticket_uid))

    return router
