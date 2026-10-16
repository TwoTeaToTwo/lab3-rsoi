import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ticket_service.application.service import TicketService
from ticket_service.domain.errors import TicketConflict, TicketNotFound
from ticket_service.domain.models import Ticket, TicketStatus
from ticket_service.infrastructure.postgres import PostgresUnitOfWork


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("TICKET_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("Set TICKET_TEST_DATABASE_URL to a migrated test database")
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def make_service(sessions: async_sessionmaker[AsyncSession]) -> TicketService:
    return TicketService(lambda: PostgresUnitOfWork(sessions))


async def test_persisted_ticket_retry_owner_and_cancellation(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    username, uid = str(uuid4()), uuid4()
    original, _ = await make_service(sessions).create_ticket(username, uid, "AFL031", 1500)
    service = make_service(sessions)
    assert await service.get_ticket(username, uid) == original
    with pytest.raises(TicketConflict):
        await service.create_ticket(username, uid, "AFL031", 1600)
    with pytest.raises(TicketNotFound):
        await service.cancel_ticket(str(uuid4()), uid)
    await asyncio.gather(*[make_service(sessions).cancel_ticket(username, uid) for _ in range(8)])
    ticket, created = await make_service(sessions).create_ticket(username, uid, "AFL031", 1500)
    assert not created and ticket.status == TicketStatus.CANCELED
    assert await service.list_tickets(username) == (ticket,)


async def test_concurrent_uuid_creation_is_unique_across_users(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    username, uid = str(uuid4()), uuid4()
    results = await asyncio.gather(
        *[make_service(sessions).create_ticket(username, uid, "AFL031", 1500) for _ in range(8)]
    )
    assert sum(created for _, created in results) == 1
    assert len(await make_service(sessions).list_tickets(username)) == 1
    foreign_uid = uuid4()

    async def create(owner: str) -> bool:
        try:
            await make_service(sessions).create_ticket(owner, foreign_uid, "AFL031", 1500)
            return True
        except TicketNotFound:
            return False

    assert sum(await asyncio.gather(create(str(uuid4())), create(str(uuid4())))) == 1


async def test_uncommitted_creation_and_failed_cancellation_roll_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    username, uid = str(uuid4()), uuid4()
    async with PostgresUnitOfWork(sessions) as transaction:
        assert await transaction.repository.get_ticket(uid) is None
        await transaction.repository.save_ticket(Ticket(uid, username, "AFL031", 1500))
    service = make_service(sessions)
    with pytest.raises(TicketNotFound):
        await service.get_ticket(username, uid)
    original, _ = await service.create_ticket(username, uid, "AFL031", 1500)
    with pytest.raises(RuntimeError, match="Abort"):
        async with PostgresUnitOfWork(sessions) as transaction:
            ticket = await transaction.repository.get_ticket(uid)
            assert ticket is not None
            await transaction.repository.save_ticket(ticket.cancel())
            raise RuntimeError("Abort")
    assert await service.get_ticket(username, uid) == original
