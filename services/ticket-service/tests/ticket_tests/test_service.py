import asyncio
from uuid import uuid4

import pytest
from ticket_service.application.service import TicketService
from ticket_service.domain.errors import InvalidInput, TicketConflict, TicketNotFound
from ticket_service.domain.models import TicketStatus
from ticket_service.infrastructure.memory import InMemoryStore


@pytest.fixture
def service() -> TicketService:
    return TicketService(InMemoryStore().transaction)


async def test_create_get_and_list_only_owned_tickets(service: TicketService) -> None:
    assert await service.list_tickets("alice") == ()
    first, created = await service.create_ticket("alice", uuid4(), "AFL031", 1500)
    await service.create_ticket("bob", uuid4(), "AFL031", 1500)
    second, _ = await service.create_ticket("alice", uuid4(), "AFL032", 2000)
    assert created and first.status == TicketStatus.PAID
    assert first.username == "alice" and first.price == 1500
    assert await service.get_ticket("alice", first.ticket_uid) == first
    assert await service.list_tickets("alice") == (first, second)


async def test_concurrent_creation_with_same_uuid_applies_once(service: TicketService) -> None:
    uid = uuid4()
    results = await asyncio.gather(
        *[service.create_ticket("alice", uid, "AFL031", 1500) for _ in range(10)]
    )
    assert sum(created for _, created in results) == 1
    assert all(ticket == results[0][0] for ticket, _ in results)
    assert len(await service.list_tickets("alice")) == 1


async def test_changed_purchase_parameters_conflict(service: TicketService) -> None:
    ticket, _ = await service.create_ticket("alice", uuid4(), "AFL031", 1500)
    with pytest.raises(TicketConflict):
        await service.create_ticket("alice", ticket.ticket_uid, "AFL032", 1500)
    with pytest.raises(TicketConflict):
        await service.create_ticket("alice", ticket.ticket_uid, "AFL031", 1600)
    assert await service.get_ticket("alice", ticket.ticket_uid) == ticket


async def test_foreign_ticket_is_hidden_for_all_operations(service: TicketService) -> None:
    ticket, _ = await service.create_ticket("alice", uuid4(), "AFL031", 1500)
    with pytest.raises(TicketNotFound):
        await service.get_ticket("bob", ticket.ticket_uid)
    with pytest.raises(TicketNotFound):
        await service.create_ticket("bob", ticket.ticket_uid, "AFL031", 1500)
    with pytest.raises(TicketNotFound):
        await service.cancel_ticket("bob", ticket.ticket_uid)
    assert await service.get_ticket("alice", ticket.ticket_uid) == ticket


async def test_missing_ticket_is_not_found(service: TicketService) -> None:
    uid = uuid4()
    with pytest.raises(TicketNotFound):
        await service.get_ticket("alice", uid)
    with pytest.raises(TicketNotFound):
        await service.cancel_ticket("alice", uid)


async def test_cancellation_is_idempotent_and_creation_does_not_reactivate(
    service: TicketService,
) -> None:
    original, _ = await service.create_ticket("alice", uuid4(), "AFL031", 1500)
    await service.cancel_ticket("alice", original.ticket_uid)
    await service.cancel_ticket("alice", original.ticket_uid)
    ticket, created = await service.create_ticket("alice", original.ticket_uid, "AFL031", 1500)
    assert not created and ticket.status == TicketStatus.CANCELED
    assert ticket.price == original.price and ticket.flight_number == original.flight_number
    assert await service.list_tickets("alice") == (ticket,)


async def test_invalid_purchase_does_not_create_ticket(service: TicketService) -> None:
    with pytest.raises(InvalidInput) as error:
        await service.create_ticket("alice", uuid4(), "AFL031", -1)
    assert error.value.field == "price"
    assert await service.list_tickets("alice") == ()
