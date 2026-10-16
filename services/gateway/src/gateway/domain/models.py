from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

TicketStatus = Literal["PAID", "CANCELED"]
PrivilegeStatus = Literal["BRONZE", "SILVER", "GOLD"]
OperationType = Literal["FILL_IN_BALANCE", "DEBIT_THE_ACCOUNT"]


@dataclass(frozen=True)
class Flight:
    flight_number: str
    from_airport: str
    to_airport: str
    date: str
    price: int


@dataclass(frozen=True)
class FlightPage:
    page: int
    page_size: int
    total_elements: int
    items: tuple[Flight, ...]


@dataclass(frozen=True)
class Ticket:
    ticket_uid: UUID
    username: str
    flight_number: str
    price: int
    status: TicketStatus


@dataclass(frozen=True)
class Privilege:
    balance: int
    status: PrivilegeStatus


@dataclass(frozen=True)
class History:
    date: datetime
    ticket_uid: UUID
    balance_diff: int
    operation_type: OperationType


@dataclass(frozen=True)
class Account(Privilege):
    history: tuple[History, ...]


@dataclass(frozen=True)
class Payment:
    ticket_uid: UUID
    price: int
    paid_by_money: int
    paid_by_bonuses: int
    privilege: Privilege


@dataclass(frozen=True)
class TicketInfo(Flight):
    ticket_uid: UUID
    status: TicketStatus


@dataclass(frozen=True)
class PurchaseResult(TicketInfo):
    paid_by_money: int
    paid_by_bonuses: int
    privilege: Privilege


@dataclass(frozen=True)
class UserInfo:
    tickets: tuple[TicketInfo, ...]
    privilege: Privilege
