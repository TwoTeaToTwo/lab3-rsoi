from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from gateway.domain.models import (
    Account,
    Flight,
    FlightPage,
    History,
    OperationType,
    Payment,
    Privilege,
    PrivilegeStatus,
    Ticket,
    TicketStatus,
)

Amount = Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)]
FlightNumber = Annotated[str, Field(min_length=1, max_length=20, pattern=r".*\S.*")]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="forbid"
    )


class FlightDTO(ApiModel):
    flight_number: FlightNumber
    from_airport: str
    to_airport: str
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")]
    price: Amount

    def to_domain(self) -> Flight:
        return Flight(self.flight_number, self.from_airport, self.to_airport, self.date, self.price)


class FlightPageDTO(ApiModel):
    page: Annotated[int, Field(strict=True, ge=1)]
    page_size: Annotated[int, Field(strict=True, ge=1, le=100)]
    total_elements: Annotated[int, Field(strict=True, ge=0)]
    items: list[FlightDTO]

    def to_domain(self) -> FlightPage:
        return FlightPage(
            self.page,
            self.page_size,
            self.total_elements,
            tuple(item.to_domain() for item in self.items),
        )


class TicketDTO(ApiModel):
    ticket_uid: UUID
    username: Annotated[str, Field(min_length=1, max_length=80)]
    flight_number: FlightNumber
    price: Amount
    status: TicketStatus

    def to_domain(self) -> Ticket:
        return Ticket(self.ticket_uid, self.username, self.flight_number, self.price, self.status)


class PrivilegeDTO(ApiModel):
    balance: Amount
    status: PrivilegeStatus

    def to_domain(self) -> Privilege:
        return Privilege(self.balance, self.status)


class HistoryDTO(ApiModel):
    date: datetime
    ticket_uid: UUID
    balance_diff: Amount
    operation_type: OperationType

    def to_domain(self) -> History:
        return History(self.date, self.ticket_uid, self.balance_diff, self.operation_type)


class AccountDTO(PrivilegeDTO):
    history: list[HistoryDTO]

    def to_account(self) -> Account:
        return Account(self.balance, self.status, tuple(item.to_domain() for item in self.history))


class PaymentDTO(ApiModel):
    ticket_uid: UUID
    price: Amount
    paid_by_money: Amount
    paid_by_bonuses: Amount
    privilege: PrivilegeDTO

    @model_validator(mode="after")
    def valid_total(self) -> "PaymentDTO":
        if self.paid_by_money + self.paid_by_bonuses != self.price:
            raise ValueError("Payment does not equal price")
        return self

    def to_domain(self) -> Payment:
        return Payment(
            self.ticket_uid,
            self.price,
            self.paid_by_money,
            self.paid_by_bonuses,
            self.privilege.to_domain(),
        )
