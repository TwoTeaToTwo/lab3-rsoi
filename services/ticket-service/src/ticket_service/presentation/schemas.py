from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ticket_service.domain.models import Ticket, TicketStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class CreateTicketRequest(ApiModel):
    flight_number: Annotated[str, Field(min_length=1, max_length=20, pattern=r".*\S.*")]
    price: Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)]


class TicketResponse(ApiModel):
    ticket_uid: UUID
    username: str
    flight_number: str
    price: int
    status: TicketStatus

    @classmethod
    def from_domain(cls, ticket: Ticket) -> TicketResponse:
        return cls(
            ticket_uid=ticket.ticket_uid,
            username=ticket.username,
            flight_number=ticket.flight_number,
            price=ticket.price,
            status=ticket.status,
        )


class ErrorDescription(BaseModel):
    field: str
    error: str


class ErrorResponse(BaseModel):
    message: str


class ValidationErrorResponse(ErrorResponse):
    errors: list[ErrorDescription]
