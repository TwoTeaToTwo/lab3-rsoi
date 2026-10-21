import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import httpx
import pytest
from gateway.config import Settings
from gateway.domain.errors import NotFound, UpstreamRejected, UpstreamUnavailable
from gateway.infrastructure.circuit_breaker import CircuitBreaker, CircuitState
from gateway.infrastructure.http import HttpBonusClient, HttpFlightClient, HttpTicketClient
from gateway.main import create_app

from gateway_tests.test_fallback import FLIGHT, HEADERS, PRIVILEGE, UID, Backends


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def assert_state(breaker: CircuitBreaker, state: CircuitState, failures: int) -> None:
    assert breaker.state == state
    assert breaker.failure_count == failures


async def success() -> str:
    return "ok"


async def failure() -> str:
    raise UpstreamUnavailable("Flight")


async def test_errors_accumulate_until_n_plus_one_and_reset_only_after_recovery() -> None:
    clock = Clock()
    breaker = CircuitBreaker("Flight", n=2, recovery_timeout=5, clock=clock)
    for count in (1, 2):
        with pytest.raises(UpstreamUnavailable):
            await breaker.call(failure)
        assert await breaker.call(success) == "ok"
        assert_state(breaker, CircuitState.CLOSED, count)
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(failure)
    assert_state(breaker, CircuitState.OPEN, 3)
    for _ in range(3):
        with pytest.raises(UpstreamUnavailable):
            await breaker.call(success)
    assert breaker.failure_count == 3
    clock.now = 4.99
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(success)
    clock.now = 5
    assert await breaker.call(success) == "ok"
    assert_state(breaker, CircuitState.CLOSED, 0)
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(failure)
    assert_state(breaker, CircuitState.CLOSED, 1)


async def test_only_one_probe_and_failed_probe_restarts_timeout() -> None:
    clock = Clock()
    breaker = CircuitBreaker("Flight", n=0, recovery_timeout=5, clock=clock)
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(failure)
    clock.now = 5
    started, finish = asyncio.Event(), asyncio.Event()

    async def probe() -> str:
        started.set()
        await finish.wait()
        raise UpstreamUnavailable("Flight")

    task = asyncio.create_task(breaker.call(probe))
    await started.wait()
    assert_state(breaker, CircuitState.HALF_OPEN, 1)
    for _ in range(4):
        with pytest.raises(UpstreamUnavailable):
            await breaker.call(success)
    clock.now = 7
    finish.set()
    with pytest.raises(UpstreamUnavailable):
        await task
    assert_state(breaker, CircuitState.OPEN, 2)
    clock.now = 11.99
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(success)
    clock.now = 12
    assert await breaker.call(success) == "ok"


async def test_late_results_cannot_damage_a_new_generation() -> None:
    clock = Clock()
    breaker = CircuitBreaker("Flight", n=0, recovery_timeout=1, clock=clock)
    started = [asyncio.Event(), asyncio.Event()]
    finish = [asyncio.Event(), asyncio.Event()]

    async def delayed(index: int) -> str:
        started[index].set()
        await finish[index].wait()
        return await (success() if index == 0 else failure())

    old_success = asyncio.create_task(breaker.call(lambda: delayed(0)))
    old_failure = asyncio.create_task(breaker.call(lambda: delayed(1)))
    await asyncio.gather(*(event.wait() for event in started))
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(failure)
    finish[0].set()
    assert await old_success == "ok"
    assert_state(breaker, CircuitState.OPEN, 1)
    clock.now = 1
    await breaker.call(success)
    finish[1].set()
    with pytest.raises(UpstreamUnavailable):
        await old_failure
    assert_state(breaker, CircuitState.CLOSED, 0)


async def test_canceled_probe_is_released_without_counting_a_failure() -> None:
    clock = Clock()
    breaker = CircuitBreaker("Flight", n=0, recovery_timeout=1, clock=clock)
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(failure)
    clock.now = 1
    started, finish = asyncio.Event(), asyncio.Event()

    async def probe() -> str:
        started.set()
        await finish.wait()
        return "ok"

    task = asyncio.create_task(breaker.call(probe))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_state(breaker, CircuitState.OPEN, 1)
    clock.now = 2
    assert await breaker.call(success) == "ok"


@pytest.mark.parametrize("status", [400, 404, 409])
async def test_business_errors_close_probe_but_do_not_increase_counter(status: int) -> None:
    clock = Clock()
    breaker = CircuitBreaker("Flight", n=0, recovery_timeout=1, clock=clock)

    async def rejected() -> str:
        if status == 404:
            raise NotFound("Flight not found")
        raise UpstreamRejected("Flight", status)

    with pytest.raises((NotFound, UpstreamRejected)):
        await breaker.call(rejected)
    assert_state(breaker, CircuitState.CLOSED, 0)
    with pytest.raises(UpstreamUnavailable):
        await breaker.call(failure)
    clock.now = 1
    with pytest.raises((NotFound, UpstreamRejected)):
        await breaker.call(rejected)
    assert_state(breaker, CircuitState.CLOSED, 0)


async def test_http_reads_count_all_technical_failures_and_writes_bypass_open_circuit() -> None:
    backends = Backends()
    clock = Clock()
    breakers = {
        name: CircuitBreaker(name, n=0, recovery_timeout=1, clock=clock)
        for name in ("Flight", "Ticket", "Bonus")
    }
    async with (
        httpx.AsyncClient(
            base_url="http://flight", transport=httpx.MockTransport(backends.handle)
        ) as flights,
        httpx.AsyncClient(
            base_url="http://ticket", transport=httpx.MockTransport(backends.handle)
        ) as tickets,
        httpx.AsyncClient(
            base_url="http://bonus", transport=httpx.MockTransport(backends.handle)
        ) as bonus,
    ):
        flight = HttpFlightClient(flights, breaker=breakers["Flight"])
        ticket = HttpTicketClient(tickets, retries=0, breaker=breakers["Ticket"])
        account = HttpBonusClient(bonus, retries=0, breaker=breakers["Bonus"])
        failures: list[httpx.Response | httpx.RequestError] = [
            httpx.Response(500),
            httpx.ConnectError("offline"),
            httpx.ReadTimeout("timeout"),
            httpx.Response(200, content="not JSON"),
            httpx.Response(200, json={}),
            httpx.Response(200, json={**FLIGHT, "flightNumber": "WRONG"}),
        ]
        for response in failures:
            backends.overrides["flight", "/internal/v1/flights/AFL031"] = response
            before = len(backends.calls)
            with pytest.raises(UpstreamUnavailable):
                await flight.get_flight("AFL031")
            with pytest.raises(UpstreamUnavailable):
                await flight.list_flights(1, 10)
            assert len(backends.calls) == before + 1
            assert breakers["Flight"].failure_count == 1
            clock.now += 1
            backends.overrides.clear()
            await flight.list_flights(1, 10)
            assert breakers["Flight"].failure_count == 0
        for name in ("Ticket", "Bonus"):
            assert_state(breakers[name], CircuitState.CLOSED, 0)
        backends.overrides["ticket", "/internal/v1/tickets"] = httpx.Response(500)
        backends.overrides["bonus", "/internal/v1/privilege"] = httpx.Response(500)
        operations: list[Callable[[], Awaitable[object]]] = [
            lambda: ticket.list_tickets("alice"),
            lambda: account.get_account("alice"),
        ]
        for operation in operations:
            with pytest.raises(UpstreamUnavailable):
                await operation()
        for name in ("Ticket", "Bonus"):
            assert_state(breakers[name], CircuitState.OPEN, 1)
        await ticket.create_ticket("alice", UID, "AFL031", 1500)
        await ticket.cancel_ticket("alice", UID)
        backends.overrides["bonus", f"/internal/v1/privilege/operations/{UID}/reversal"] = (
            httpx.Response(200, json=PRIVILEGE)
        )
        await account.reverse_purchase("alice", UID)
        before = len(backends.calls)
        with pytest.raises(UpstreamUnavailable):
            await account.apply_purchase("alice", UID, 1500, False)
        assert len(backends.calls) == before + 1
        assert breakers["Ticket"].failure_count == breakers["Bonus"].failure_count == 1


async def test_application_wiring_protects_all_reads_including_purchase_and_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_CIRCUIT_BREAKER_N", "0")
    monkeypatch.setenv("GATEWAY_CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "7")
    monkeypatch.setenv("GATEWAY_FLIGHT_URL", "http://flight")
    monkeypatch.setenv("GATEWAY_TICKET_URL", "http://ticket")
    monkeypatch.setenv("GATEWAY_BONUS_URL", "http://bonus")
    assert Settings().circuit_breaker_n == 0
    assert Settings().circuit_breaker_recovery_timeout == 7
    backends = Backends()
    original_client = httpx.AsyncClient

    def client_factory(*, base_url: str, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return original_client(
            base_url=base_url, timeout=timeout, transport=httpx.MockTransport(backends.handle)
        )

    monkeypatch.setattr("gateway.main.httpx.AsyncClient", client_factory)
    monkeypatch.setattr("gateway.main.RabbitRefundQueue.start", AsyncMock())
    monkeypatch.setattr("gateway.main.RabbitRefundQueue.close", AsyncMock())
    app = create_app()
    async with app.router.lifespan_context(app):
        async with original_client(
            base_url="http://gateway", transport=httpx.ASGITransport(app=app), headers=HEADERS
        ) as client:
            backends.overrides["flight", "/internal/v1/flights"] = httpx.Response(500)
            response = await client.get("/api/v1/flights")
            assert response.status_code == 500
            before = len(backends.calls)
            response = await client.post(
                "/api/v1/tickets",
                json={"flightNumber": "AFL031", "price": 1500, "paidFromBalance": False},
            )
            assert response.status_code == 500 and len(backends.calls) == before
            assert (await client.get(f"/api/v1/tickets/{UID}")).json()["date"] == "Unavailable"
            backends.overrides["bonus", "/internal/v1/privilege"] = httpx.Response(500)
            assert (await client.get("/api/v1/privilege")).status_code == 503
            before = len(backends.calls)
            response = await client.get("/api/v1/me")
            assert response.status_code == 200
            assert response.json()["privilege"] == {}
            assert response.json()["tickets"][0]["date"] == "Unavailable"
            assert len(backends.calls) == before + 1  # Only Ticket is still queried.
            backends.overrides["ticket", f"/internal/v1/tickets/{UID}"] = httpx.Response(500)
            assert (await client.delete(f"/api/v1/tickets/{UID}")).status_code == 500
            before = len(backends.calls)
            assert (await client.delete(f"/api/v1/tickets/{UID}")).status_code == 500
            assert (await client.get("/api/v1/tickets")).status_code == 500
            assert len(backends.calls) == before
            assert set(app.state.circuit_breakers) == {"Flight", "Ticket", "Bonus"}
