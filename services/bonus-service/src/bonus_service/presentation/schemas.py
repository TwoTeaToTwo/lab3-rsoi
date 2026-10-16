from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from bonus_service.domain.models import (
    MAX_AMOUNT,
    Account,
    HistoryEntry,
    OperationType,
    PaymentResult,
    Privilege,
    PrivilegeStatus,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class PurchaseRequest(ApiModel):
    price: Annotated[int, Field(strict=True, ge=0, le=MAX_AMOUNT)]
    paid_from_balance: Annotated[bool, Field(strict=True)]


class PrivilegeResponse(ApiModel):
    balance: int
    status: PrivilegeStatus

    @classmethod
    def from_domain(cls, privilege: Privilege) -> PrivilegeResponse:
        return cls(balance=privilege.balance, status=privilege.status)


class HistoryResponse(ApiModel):
    date: datetime
    ticket_uid: UUID
    balance_diff: int
    operation_type: OperationType

    @classmethod
    def from_domain(cls, entry: HistoryEntry) -> HistoryResponse:
        return cls(
            date=entry.date,
            ticket_uid=entry.ticket_uid,
            balance_diff=entry.balance_diff,
            operation_type=entry.operation_type,
        )


class AccountResponse(PrivilegeResponse):
    history: list[HistoryResponse]

    @classmethod
    def from_account(cls, account: Account) -> AccountResponse:
        # Python's sort is stable: insertion order resolves identical timestamps.
        history = sorted(account.history, key=lambda entry: entry.date)
        return cls(
            balance=account.balance,
            status=account.status,
            history=[HistoryResponse.from_domain(entry) for entry in history],
        )


class PaymentResponse(ApiModel):
    ticket_uid: UUID
    price: int
    paid_by_money: int
    paid_by_bonuses: int
    privilege: PrivilegeResponse

    @classmethod
    def from_domain(cls, result: PaymentResult) -> PaymentResponse:
        return cls(
            ticket_uid=result.ticket_uid,
            price=result.price,
            paid_by_money=result.paid_by_money,
            paid_by_bonuses=result.paid_by_bonuses,
            privilege=PrivilegeResponse.from_domain(result.privilege),
        )


class ErrorDescription(BaseModel):
    field: str
    error: str


class ErrorResponse(BaseModel):
    message: str


class ValidationErrorResponse(ErrorResponse):
    errors: list[ErrorDescription]


class HealthResponse(BaseModel):
    status: Literal["UP"] = "UP"
