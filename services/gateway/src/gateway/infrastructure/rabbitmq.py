import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Protocol

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection
from aio_pika.exceptions import CONNECTION_EXCEPTIONS
from pamqp.commands import Basic
from pydantic import ValidationError

from gateway.domain.errors import RefundQueueUnavailable, Unavailable
from gateway.domain.models import RefundTask
from gateway.infrastructure.refund_schemas import RefundMessage

logger = logging.getLogger(__name__)
BROKER_ERRORS = (*CONNECTION_EXCEPTIONS, TimeoutError)


class Delivery(Protocol):
    @property
    def body(self) -> bytes: ...

    @property
    def message_id(self) -> str | None: ...

    async def ack(self) -> None: ...


class RabbitRefundQueue:
    def __init__(
        self,
        url: str,
        queue_name: str,
        error_queue_name: str,
        *,
        retry_interval: float = 10,
        timeout: float = 5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if queue_name == error_queue_name:
            raise ValueError("Refund and error queues must have different names")
        self._url = url
        self._queue_name = queue_name
        self._error_queue_name = error_queue_name
        self._retry_interval = retry_interval
        self._timeout = timeout
        self._sleep = sleep
        self._connection: AbstractRobustConnection | None = None
        self._publisher: AbstractChannel | None = None
        self._queue: AbstractQueue | None = None
        self._worker: asyncio.Task[None] | None = None

    async def start(self, handler: Callable[[RefundTask], Awaitable[None]]) -> None:
        self._connection = await aio_pika.connect_robust(self._url, timeout=self._timeout)
        publisher = await self._connection.channel(publisher_confirms=True, on_return_raises=True)
        self._publisher = publisher
        consumer = await self._connection.channel()
        await consumer.set_qos(prefetch_count=1, timeout=self._timeout)
        self._queue = await consumer.declare_queue(
            self._queue_name, durable=True, timeout=self._timeout
        )
        await publisher.declare_queue(self._error_queue_name, durable=True, timeout=self._timeout)
        self._worker = asyncio.create_task(self._consume(handler), name="bonus-refund-consumer")

    async def close(self) -> None:
        try:
            if self._worker is not None:
                self._worker.cancel()
                with suppress(asyncio.CancelledError):
                    await self._worker
        finally:
            # Closing the connection requeues an in-flight unacknowledged delivery.
            if self._connection is not None:
                await self._connection.close()
            self._publisher = None

    async def _send(
        self, body: bytes, routing_key: str, operation_id: str | None, error: str | None = None
    ) -> None:
        if self._publisher is None:
            raise RefundQueueUnavailable()
        message = aio_pika.Message(
            body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=operation_id,
            headers={} if error is None else {"failure": error[:500]},
        )
        try:
            async with asyncio.timeout(self._timeout):
                confirmed = await self._publisher.default_exchange.publish(
                    message, routing_key=routing_key, mandatory=True, timeout=self._timeout
                )
            if not isinstance(confirmed, Basic.Ack):
                raise RefundQueueUnavailable()
        except BROKER_ERRORS as broker_error:
            raise RefundQueueUnavailable() from broker_error

    async def publish(self, task: RefundTask) -> None:
        body = RefundMessage.from_domain(task).model_dump_json(by_alias=True).encode()
        await self._send(body, self._queue_name, task.operation_id)
        logger.info("Refund published: %s", task.operation_id)

    async def handle(
        self, message: Delivery, handler: Callable[[RefundTask], Awaitable[None]]
    ) -> None:
        try:
            task = RefundMessage.model_validate_json(message.body).to_domain()
        except ValidationError:
            await self._send(
                message.body, self._error_queue_name, message.message_id, "Invalid refund message"
            )
            await message.ack()
            logger.error("Invalid refund message moved to error queue: %s", message.message_id)
            return
        logger.info("Refund attempt: %s", task.operation_id)
        try:
            await handler(task)
        except Unavailable:
            logger.warning("Refund pending: %s", task.operation_id)
            await self._sleep(self._retry_interval)
            await self.publish(task)
        except Exception as error:
            logger.exception("Permanent refund failure: %s", task.operation_id)
            await self._send(
                message.body, self._error_queue_name, task.operation_id, type(error).__name__
            )
        else:
            logger.info("Refund completed: %s", task.operation_id)
        # Confirm only after HTTP success, or after confirmed retry/error publication.
        await message.ack()

    async def _consume(self, handler: Callable[[RefundTask], Awaitable[None]]) -> None:
        if self._queue is None:
            raise RuntimeError("Refund queue is not started")
        while True:
            try:
                async with self._queue.iterator(no_ack=False) as messages:
                    async for message in messages:
                        try:
                            await self.handle(message, handler)
                        except (RefundQueueUnavailable, *BROKER_ERRORS):
                            logger.exception(
                                "Refund delivery not completed: %s", message.message_id
                            )
                            await self._sleep(self._retry_interval)
                            if not message.processed:
                                await message.nack(requeue=True)
            except BROKER_ERRORS:
                logger.exception("Refund consumer connection interrupted")
                await self._sleep(self._retry_interval)
