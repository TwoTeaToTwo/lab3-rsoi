import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from bonus_service.application.service import BonusService
from bonus_service.domain.errors import OperationNotFound
from bonus_service.domain.models import purchase
from bonus_service.infrastructure.postgres import PostgresUnitOfWork
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import FixedClock


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("BONUS_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("Set BONUS_TEST_DATABASE_URL to a migrated test database")
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def make_service(sessions: async_sessionmaker[AsyncSession]) -> BonusService:
    return BonusService(lambda: PostgresUnitOfWork(sessions), FixedClock())


async def test_postgres_persists_original_result_and_reversal(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    username, uid = str(uuid4()), uuid4()
    original, _ = await make_service(sessions).apply_purchase(username, uid, 1500, False)
    service = make_service(sessions)
    await service.apply_purchase(username, uuid4(), 1000, False)
    repeated, created = await service.apply_purchase(username, uid, 1500, False)
    assert not created and repeated == original
    assert (await service.get_account(username)).balance == 250
    await service.reverse_purchase(username, uid)
    assert (await make_service(sessions).reverse_purchase(username, uid)).balance == 100
    assert len((await service.get_account(username)).history) == 3


async def test_postgres_concurrent_spending_and_duplicate_uuid(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    username, uid = str(uuid4()), uuid4()
    results = await asyncio.gather(
        *[make_service(sessions).apply_purchase(username, uid, 5000, False) for _ in range(8)]
    )
    assert sum(created for _, created in results) == 1
    results = await asyncio.gather(
        *[make_service(sessions).apply_purchase(username, uuid4(), 400, True) for _ in range(8)]
    )
    assert sum(result.paid_by_bonuses for result, _ in results) == 500
    account = await make_service(sessions).get_account(username)
    assert account.balance == 0 and len(account.history) == 9


async def test_postgres_same_uuid_cannot_belong_to_two_users(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    uid = uuid4()

    async def buy(username: str) -> bool:
        try:
            await make_service(sessions).apply_purchase(username, uid, 1500, False)
            return True
        except OperationNotFound:
            return False

    assert sum(await asyncio.gather(buy(str(uuid4())), buy(str(uuid4())))) == 1


async def test_postgres_rolls_back_account_history_and_operation(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    username, uid = str(uuid4()), uuid4()
    service = make_service(sessions)
    await service.get_account(username)
    with pytest.raises(RuntimeError, match="Abort"):
        async with PostgresUnitOfWork(sessions) as transaction:
            account = await transaction.repository.get_account(username)
            updated, operation = purchase(account, uid, 1500, False, FixedClock().now())
            await transaction.repository.save_account(updated)
            await transaction.repository.save_operation(operation)
            raise RuntimeError("Abort")
    account = await service.get_account(username)
    assert account.balance == 0 and account.history == ()
    async with PostgresUnitOfWork(sessions) as transaction:
        assert await transaction.repository.get_operation(uid) is None
