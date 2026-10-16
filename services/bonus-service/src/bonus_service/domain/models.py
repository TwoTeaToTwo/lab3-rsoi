from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from bonus_service.domain.errors import InvalidInput

MAX_AMOUNT = 2**31 - 1


class PrivilegeStatus(StrEnum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class OperationType(StrEnum):
    FILL_IN_BALANCE = "FILL_IN_BALANCE"
    DEBIT_THE_ACCOUNT = "DEBIT_THE_ACCOUNT"


def validate_username(username: str) -> None:
    if not username.strip() or len(username) > 80:
        raise InvalidInput("X-User-Name", "Username must contain 1 to 80 characters")


def validate_price(price: int) -> None:
    if isinstance(price, bool) or not isinstance(price, int) or not 0 <= price <= MAX_AMOUNT:
        raise InvalidInput("price", "Price must be a nonnegative int32 integer")


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    date: datetime
    ticket_uid: UUID
    balance_diff: int
    operation_type: OperationType


@dataclass(frozen=True, slots=True)
class Privilege:
    balance: int
    status: PrivilegeStatus


@dataclass(frozen=True, slots=True)
class Account:
    username: str
    balance: int = 0
    status: PrivilegeStatus = PrivilegeStatus.BRONZE
    history: tuple[HistoryEntry, ...] = ()

    @property
    def privilege(self) -> Privilege:
        return Privilege(self.balance, self.status)

    def record(self, entry: HistoryEntry) -> Account:
        delta = entry.balance_diff
        if entry.operation_type == OperationType.DEBIT_THE_ACCOUNT:
            delta = -delta
        balance = self.balance + delta
        if not 0 <= balance <= MAX_AMOUNT:
            raise InvalidInput("balance", "Resulting balance is outside the int32 range")
        return replace(self, balance=balance, history=(*self.history, entry))


@dataclass(frozen=True, slots=True)
class PaymentResult:
    ticket_uid: UUID
    price: int
    paid_by_money: int
    paid_by_bonuses: int
    privilege: Privilege


@dataclass(frozen=True, slots=True)
class PurchaseOperation:
    username: str
    paid_from_balance: bool
    result: PaymentResult
    accrued: int
    reversed: bool = False


def purchase(
    account: Account, ticket_uid: UUID, price: int, paid_from_balance: bool, now: datetime
) -> tuple[Account, PurchaseOperation]:
    validate_price(price)
    if not isinstance(paid_from_balance, bool):
        raise InvalidInput("paidFromBalance", "A boolean is required")
    paid_by_bonuses = min(account.balance, price) if paid_from_balance else 0
    accrued = 0 if paid_from_balance else price // 10
    entry = HistoryEntry(
        now,
        ticket_uid,
        paid_by_bonuses if paid_from_balance else accrued,
        OperationType.DEBIT_THE_ACCOUNT if paid_from_balance else OperationType.FILL_IN_BALANCE,
    )
    updated = account.record(entry)
    result = PaymentResult(
        ticket_uid, price, price - paid_by_bonuses, paid_by_bonuses, updated.privilege
    )
    return updated, PurchaseOperation(account.username, paid_from_balance, result, accrued)


def reverse(
    account: Account, operation: PurchaseOperation, now: datetime
) -> tuple[Account, PurchaseOperation]:
    if operation.reversed:
        return account, operation
    entry = HistoryEntry(
        now,
        operation.result.ticket_uid,
        operation.result.paid_by_bonuses
        if operation.paid_from_balance
        else min(account.balance, operation.accrued),
        OperationType.FILL_IN_BALANCE
        if operation.paid_from_balance
        else OperationType.DEBIT_THE_ACCOUNT,
    )
    return account.record(entry), replace(operation, reversed=True)
