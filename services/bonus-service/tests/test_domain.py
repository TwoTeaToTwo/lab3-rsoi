from datetime import UTC, datetime
from uuid import uuid4

from bonus_service.domain.models import Account, OperationType, PrivilegeStatus, purchase, reverse

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def test_cash_purchase_accrues_integer_ten_percent() -> None:
    price, expected = 1599, 159
    original = Account("alice")
    account, operation = purchase(original, uuid4(), price, False, NOW)
    assert original.balance == 0
    assert account.balance == expected
    assert operation.result.paid_by_money == price
    assert operation.result.paid_by_bonuses == 0
    assert account.history[0].balance_diff == expected
    assert account.history[0].operation_type == OperationType.FILL_IN_BALANCE


def test_bonus_purchase_uses_maximum_available_balance() -> None:
    balance, bonuses, money, remaining = 500, 500, 1000, 0
    account, operation = purchase(Account("alice", balance), uuid4(), 1500, True, NOW)
    assert account.balance == remaining
    assert operation.result.paid_by_bonuses == bonuses
    assert operation.result.paid_by_money == money
    assert operation.accrued == 0
    assert account.history[0].operation_type == OperationType.DEBIT_THE_ACCOUNT


def test_bonus_refund_restores_spent_points_and_preserves_status() -> None:
    paid, operation = purchase(
        Account("alice", 500, PrivilegeStatus.GOLD), uuid4(), 1500, True, NOW
    )
    refunded, reversed_operation = reverse(paid, operation, NOW)
    assert refunded.balance == 500
    assert refunded.status == PrivilegeStatus.GOLD
    assert reversed_operation.reversed
    assert refunded.history[-1].balance_diff == 500
    assert refunded.history[-1].operation_type == OperationType.FILL_IN_BALANCE
    assert reverse(refunded, reversed_operation, NOW) == (refunded, reversed_operation)


def test_cash_refund_only_removes_points_still_available() -> None:
    paid, operation = purchase(Account("alice"), uuid4(), 1500, False, NOW)
    spent, _ = purchase(paid, uuid4(), 100, True, NOW)
    refunded, _ = reverse(spent, operation, NOW)
    assert refunded.balance == 0
    assert refunded.history[-1].balance_diff == 50
    assert refunded.history[-1].operation_type == OperationType.DEBIT_THE_ACCOUNT
