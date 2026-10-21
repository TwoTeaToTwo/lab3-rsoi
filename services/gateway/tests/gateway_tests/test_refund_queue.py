from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import aio_pika
import httpx
import pytest
from aio_pika.abc import AbstractChannel, AbstractMessage
from gateway.application.service import GatewayService
from gateway.domain.errors import NotFound, RefundQueueUnavailable, UpstreamUnavailable
from gateway.domain.models import RefundTask
from gateway.infrastructure.rabbitmq import RabbitRefundQueue
from gateway.infrastructure.refund_schemas import RefundMessage
from gateway.main import create_app
from pamqp.commands import Basic

from gateway_tests.test_service import Services


class PendingRefunds:
    def __init__(self) -> None:
        self.tasks: list[RefundTask] = []
        self.fail = False

    async def publish(self, task: RefundTask) -> None:
        if self.fail:
            raise RefundQueueUnavailable()
        self.tasks.append(task)


class RefundServices(Services):
    def __init__(self) -> None:
        super().__init__()
        self.fail_bonus = False
        self.events: list[str] = []

    async def cancel_ticket(self, username: str, uid: UUID) -> None:
        self.events.append("ticket")
        if self.fail_cancel:
            raise UpstreamUnavailable("Ticket")
        await super().cancel_ticket(username, uid)

    async def reverse_purchase(self, username: str, uid: UUID) -> None:
        self.events.append("bonus")
        if self.fail_bonus:
            raise UpstreamUnavailable("Bonus")
        await super().reverse_purchase(username, uid)


@dataclass
class Message:
    body: bytes
    message_id: str | None
    events: list[str]

    async def ack(self) -> None:
        self.events.append("ack")


class ConfirmExchange:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.messages: list[tuple[str, AbstractMessage]] = []
        self.fail = False
        self.confirm = True

    async def publish(
        self, message: AbstractMessage, *, routing_key: str, mandatory: bool, **options: object
    ) -> Basic.Ack | None:
        assert mandatory and "timeout" in options
        self.events.append("publish")
        self.messages.append((routing_key, message))
        if self.fail:
            raise OSError("broker unavailable")
        if not self.confirm:
            return None
        self.events.append("confirm")
        return Basic.Ack(delivery_tag=1)


def queue(events: list[str]) -> tuple[RabbitRefundQueue, ConfirmExchange]:
    async def sleep(delay: float) -> None:
        events.append(f"sleep:{delay}")

    adapter = RabbitRefundQueue("amqp://unused", "refunds", "errors", sleep=sleep)
    exchange = ConfirmExchange(events)
    adapter._publisher = cast(AbstractChannel, SimpleNamespace(default_exchange=exchange))
    return adapter, exchange


async def test_refund_is_accepted_and_repeated_delivery_changes_balance_only_once() -> None:
    services, pending = RefundServices(), PendingRefunds()
    gateway = GatewayService(services, services, services, pending)
    ticket = await gateway.purchase("alice", "AFL031", 1500, False)
    services.fail_bonus = True
    services.events.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(gateway)), base_url="http://gateway"
    ) as client:
        for _ in range(2):
            response = await client.delete(
                f"/api/v1/tickets/{ticket.ticket_uid}", headers={"X-User-Name": "alice"}
            )
            assert response.status_code == 204 and response.content == b""
    assert services.events == ["ticket", "bonus", "ticket", "bonus"]
    assert services.tickets[ticket.ticket_uid].status == "CANCELED"
    assert services.balance == 150 and len(pending.tasks) == 2
    assert pending.tasks[0] == pending.tasks[1]
    services.fail_bonus = False
    services.fail_cancel = True  # The worker must not read or change Ticket again.
    for task in pending.tasks:
        await gateway.process_refund(task)
    assert services.balance == 0 and services.reversed == {ticket.ticket_uid}


async def test_ticket_and_publication_failures_do_not_report_success() -> None:
    services, pending = RefundServices(), PendingRefunds()
    gateway = GatewayService(services, services, services, pending)
    ticket = await gateway.purchase("alice", "AFL031", 1500, False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(gateway)), base_url="http://gateway"
    ) as client:
        path = f"/api/v1/tickets/{ticket.ticket_uid}"
        services.events.clear()
        response = await client.delete(path, headers={"X-User-Name": "bob"})
        assert response.status_code == 404 and services.events == []
        services.fail_cancel = True
        response = await client.delete(path, headers={"X-User-Name": "alice"})
        assert response.status_code == 500 and pending.tasks == []
        assert services.tickets[ticket.ticket_uid].status == "PAID"
        assert services.events == ["ticket"]
        services.fail_cancel = False
        services.fail_bonus = pending.fail = True
        response = await client.delete(path, headers={"X-User-Name": "alice"})
        assert response.status_code == 503
        assert response.json() == {"message": "Refund queue unavailable"}
        assert services.tickets[ticket.ticket_uid].status == "CANCELED" and pending.tasks == []
        pending.fail = False
        response = await client.delete(path, headers={"X-User-Name": "alice"})
        assert response.status_code == 204 and len(pending.tasks) == 1


async def test_success_is_acknowledged_after_http_completion() -> None:
    events: list[str] = []
    adapter, exchange = queue(events)
    task = RefundTask(uuid4(), "alice")

    async def handler(received: RefundTask) -> None:
        assert received == task
        events.append("http")

    message = Message(
        RefundMessage.from_domain(task).model_dump_json(by_alias=True).encode(),
        task.operation_id,
        events,
    )
    await adapter.handle(message, handler)
    assert events == ["http", "ack"] and exchange.messages == []


async def test_retry_is_confirmed_before_original_message_is_acknowledged() -> None:
    events: list[str] = []
    adapter, exchange = queue(events)
    task = RefundTask(uuid4(), "alice")

    async def handler(received: RefundTask) -> None:
        events.append("http")
        raise UpstreamUnavailable("Bonus")

    message = Message(
        RefundMessage.from_domain(task).model_dump_json(by_alias=True).encode(),
        task.operation_id,
        events,
    )
    await adapter.handle(message, handler)
    assert events == ["http", "sleep:10", "publish", "confirm", "ack"]
    routing, published = exchange.messages[0]
    assert routing == "refunds" and published.message_id == task.operation_id
    assert published.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert RefundMessage.model_validate_json(published.body).to_domain() == task


@pytest.mark.parametrize("no_confirm", [False, True])
async def test_failed_republication_never_acknowledges_original(no_confirm: bool) -> None:
    events: list[str] = []
    adapter, exchange = queue(events)
    exchange.fail = not no_confirm
    exchange.confirm = not no_confirm
    task = RefundTask(uuid4(), "alice")

    async def handler(received: RefundTask) -> None:
        raise UpstreamUnavailable("Bonus")

    message = Message(
        RefundMessage.from_domain(task).model_dump_json(by_alias=True).encode(),
        task.operation_id,
        events,
    )
    with pytest.raises(RefundQueueUnavailable):
        await adapter.handle(message, handler)
    assert "ack" not in events


async def test_invalid_and_permanently_failed_tasks_are_preserved_in_error_queue() -> None:
    events: list[str] = []
    adapter, exchange = queue(events)
    task = RefundTask(uuid4(), "alice")
    calls = 0

    async def handler(received: RefundTask) -> None:
        nonlocal calls
        calls += 1
        raise NotFound("Bonus operation not found")

    for body in [
        b"not JSON",
        RefundMessage.from_domain(task).model_dump_json(by_alias=True).encode(),
    ]:
        events.clear()
        await adapter.handle(Message(body, task.operation_id, events), handler)
        assert events == ["publish", "confirm", "ack"]
        assert exchange.messages[-1][0] == "errors" and exchange.messages[-1][1].body == body
    assert calls == 1
