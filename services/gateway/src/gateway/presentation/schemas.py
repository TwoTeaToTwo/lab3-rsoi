from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from gateway.domain.models import OperationType, PrivilegeStatus, TicketStatus, UserInfo

Amount = Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)]
FlightNumber = Annotated[str, Field(min_length=1, max_length=20, pattern=r".*\S.*")]
FlightDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="forbid"
    )


class FlightDTO(ApiModel):
    flight_number: FlightNumber
    from_airport: str
    to_airport: str
    date: FlightDate
    price: Amount


class FlightPageDTO(ApiModel):
    page: Annotated[int, Field(strict=True, ge=1)]
    page_size: Annotated[int, Field(strict=True, ge=1, le=100)]
    total_elements: Annotated[int, Field(strict=True, ge=0)]
    items: list[FlightDTO]


class PrivilegeDTO(ApiModel):
    balance: Amount
    status: PrivilegeStatus


class HistoryDTO(ApiModel):
    date: datetime
    ticket_uid: UUID
    balance_diff: Amount
    operation_type: OperationType


class AccountDTO(PrivilegeDTO):
    history: list[HistoryDTO]


class PublicTicketDTO(ApiModel):
    ticket_uid: UUID
    flight_number: FlightNumber
    from_airport: str
    to_airport: str
    date: FlightDate | Literal["Unavailable"]
    price: Amount
    status: TicketStatus


class PurchaseDTO(FlightDTO):
    ticket_uid: UUID
    status: TicketStatus
    paid_by_money: Amount
    paid_by_bonuses: Amount
    privilege: PrivilegeDTO


class EmptyPrivilegeDTO(ApiModel):
    pass


class UserDTO(ApiModel):
    tickets: list[PublicTicketDTO]
    privilege: PrivilegeDTO | EmptyPrivilegeDTO

    @classmethod
    def from_domain(cls, user: UserInfo) -> "UserDTO":
        return cls(
            tickets=[PublicTicketDTO.model_validate(ticket) for ticket in user.tickets],
            privilege=EmptyPrivilegeDTO()
            if user.privilege is None
            else PrivilegeDTO.model_validate(user.privilege),
        )


class PurchaseRequest(ApiModel):
    flight_number: FlightNumber
    price: Amount
    paid_from_balance: Annotated[bool, Field(strict=True)]


class HealthDTO(BaseModel):
    status: Literal["UP"] = "UP"


class ErrorDescription(BaseModel):
    field: str
    error: str


class ErrorDTO(BaseModel):
    message: str


class BonusUnavailableDTO(ApiModel):
    message: Literal["Bonus Service unavailable"] = "Bonus Service unavailable"


class ValidationErrorDTO(ErrorDTO):
    errors: list[ErrorDescription]
