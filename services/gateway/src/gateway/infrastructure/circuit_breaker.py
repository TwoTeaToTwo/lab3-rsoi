import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from math import isfinite
from time import monotonic

from gateway.domain.errors import NotFound, ServiceName, UpstreamRejected, UpstreamUnavailable

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        service: ServiceName,
        n: int,
        recovery_timeout: float,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if n < 0 or not isfinite(recovery_timeout) or recovery_timeout <= 0:
            raise ValueError(
                "N must be nonnegative and recovery_timeout must be finite and positive"
            )
        self._service = service
        self._n = n
        self._recovery_timeout = recovery_timeout
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0
        self._generation = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def _transition(self, state: CircuitState) -> None:
        previous = self._state
        self._state = state
        self._generation += 1
        if state == CircuitState.OPEN:
            self._opened_at = self._clock()
        logger.info(
            "Circuit breaker %s: %s -> %s, failures=%d",
            self._service,
            previous,
            state,
            self._failure_count,
        )

    async def _acquire(self) -> int:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._clock() - self._opened_at < self._recovery_timeout:
                    raise UpstreamUnavailable(self._service)
                self._transition(CircuitState.HALF_OPEN)
            elif self._state == CircuitState.HALF_OPEN:
                raise UpstreamUnavailable(self._service)
            return self._generation

    async def _record(self, generation: int, *, failed: bool) -> None:
        async with self._lock:
            # Responses started before a transition cannot affect the current circuit.
            if generation != self._generation:
                return
            if failed:
                self._failure_count += 1
                if self._state == CircuitState.HALF_OPEN or self._failure_count > self._n:
                    self._transition(CircuitState.OPEN)
            elif self._state == CircuitState.HALF_OPEN:
                self._failure_count = 0
                self._transition(CircuitState.CLOSED)

    async def _abandon(self, generation: int) -> None:
        async with self._lock:
            if generation == self._generation and self._state == CircuitState.HALF_OPEN:
                # Cancellation or a local error must not leave the probe occupied forever.
                self._transition(CircuitState.OPEN)

    async def call[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        generation = await self._acquire()
        try:
            result = await operation()
        except UpstreamUnavailable:
            await self._record(generation, failed=True)
            raise
        except (NotFound, UpstreamRejected):
            # A 4xx proves availability, including during a recovery probe.
            await self._record(generation, failed=False)
            raise
        except BaseException:
            await self._abandon(generation)
            raise
        else:
            await self._record(generation, failed=False)
            return result
