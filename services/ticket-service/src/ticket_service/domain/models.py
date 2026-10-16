from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from ticket_service.domain.errors import InvalidInput


class TicketStatus(StrEnum):
    PAID = "PAID"
    CANCELED = "CANCELED"


def validate_username(username: str) -> None:
    if not username.strip() or len(username) > 80:
        raise InvalidInput("X-User-Name", "Username must contain 1 to 80 characters")


def validate_purchase(flight_number: str, price: int) -> None:
    if not flight_number.strip() or len(flight_number) > 20:
        raise InvalidInput("flightNumber", "Flight number must contain 1 to 20 characters")
    if isinstance(price, bool) or not isinstance(price, int) or not 0 <= price <= 2**31 - 1:
        raise InvalidInput("price", "Price must be a nonnegative int32 integer")


@dataclass(frozen=True, slots=True)
class Ticket:
    ticket_uid: UUID
    username: str
    flight_number: str
    price: int
    status: TicketStatus = TicketStatus.PAID

    def cancel(self) -> Ticket:
        return replace(self, status=TicketStatus.CANCELED)
