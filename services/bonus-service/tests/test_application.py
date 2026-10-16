import asyncio
from uuid import uuid4

import pytest
from bonus_service.application.service import BonusService
from bonus_service.domain.errors import OperationConflict


async def test_purchase_retry_returns_original_snapshot(service: BonusService) -> None:
    ticket = uuid4()
    original, created = await service.apply_purchase("alice", ticket, 1500, False)
    await service.apply_purchase("alice", uuid4(), 1000, False)
    repeated, created_again = await service.apply_purchase("alice", ticket, 1500, False)
    assert created and not created_again
    assert repeated == original
    assert repeated.privilege.balance == 150
    assert (await service.get_account("alice")).balance == 250
    assert len((await service.get_account("alice")).history) == 2


async def test_reversal_retry_returns_current_balance_without_extra_history(
    service: BonusService,
) -> None:
    ticket = uuid4()
    await service.apply_purchase("alice", ticket, 1500, False)
    assert (await service.reverse_purchase("alice", ticket)).balance == 0
    await service.apply_purchase("alice", uuid4(), 1000, False)
    assert (await service.reverse_purchase("alice", ticket)).balance == 100
    assert len((await service.get_account("alice")).history) == 3
    with pytest.raises(OperationConflict):
        await service.apply_purchase("alice", ticket, 1500, False)


async def test_concurrent_spending_cannot_overdraw(service: BonusService) -> None:
    await service.apply_purchase("alice", uuid4(), 5000, False)
    results = await asyncio.gather(
        *[service.apply_purchase("alice", uuid4(), 400, True) for _ in range(10)]
    )
    assert sum(result.paid_by_bonuses for result, _ in results) == 500
    assert (await service.get_account("alice")).balance == 0
