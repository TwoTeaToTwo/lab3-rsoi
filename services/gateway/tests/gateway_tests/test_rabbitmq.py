import asyncio
import os
from uuid import uuid4

import aio_pika
import pytest
from gateway.domain.errors import UpstreamUnavailable
from gateway.domain.models import RefundTask
from gateway.infrastructure.rabbitmq import RabbitRefundQueue


async def test_real_broker_retry_error_queue_and_unacked_redelivery() -> None:
    url = os.environ.get("GATEWAY_TEST_RABBITMQ_URL")
    if url is None:
        pytest.skip("Set GATEWAY_TEST_RABBITMQ_URL to a dedicated RabbitMQ broker")
    name = f"test.refunds.{uuid4().hex}"
    task = RefundTask(uuid4(), "alice")
    adapter = RabbitRefundQueue(url, name, name + ".errors", retry_interval=0.05)
    attempt, completed, parked = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release = asyncio.Event()
    available = False
    calls = 0

    async def handler(received: RefundTask) -> None:
        nonlocal calls
        assert received == task
        calls += 1
        attempt.set()
        if not available:
            raise UpstreamUnavailable("Bonus")
        completed.set()

    async def blocked(received: RefundTask) -> None:
        parked.set()
        await release.wait()

    connection = await aio_pika.connect_robust(url)
    try:
        channel = await connection.channel()
        await adapter.start(handler)
        await adapter.publish(task)
        await asyncio.wait_for(attempt.wait(), 5)
        available = True
        await asyncio.wait_for(completed.wait(), 5)
        assert calls >= 2
        # Graceful close flushes the first successful delivery before inspecting queues.
        await adapter.close()
        queue = await channel.declare_queue(name, durable=True)
        errors = await channel.declare_queue(name + ".errors", durable=True)
        await channel.default_exchange.publish(aio_pika.Message(b"invalid JSON"), routing_key=name)
        adapter = RabbitRefundQueue(url, name, name + ".errors", retry_interval=0.05)
        await adapter.start(handler)
        async with errors.iterator() as messages:
            error = await asyncio.wait_for(anext(messages), 5)
            assert error.body == b"invalid JSON"
            await error.ack()
        await adapter.close()
        adapter = RabbitRefundQueue(url, name, name + ".errors", retry_interval=0.05)
        await adapter.start(blocked)
        await adapter.publish(task)
        await asyncio.wait_for(parked.wait(), 5)
        await adapter.close()  # No ack: the broker must redeliver to the next consumer.
        completed.clear()
        adapter = RabbitRefundQueue(url, name, name + ".errors", retry_interval=0.05)
        await adapter.start(handler)
        await asyncio.wait_for(completed.wait(), 5)
        await adapter.close()
        await queue.delete(if_unused=False, if_empty=False)
        await errors.delete(if_unused=False, if_empty=False)
    finally:
        await adapter.close()
        await connection.close()
