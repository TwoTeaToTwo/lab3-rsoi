from datetime import datetime
from uuid import uuid4

import pytest
from bonus_service.application.service import BonusService
from bonus_service.infrastructure.memory import InMemoryStore
from bonus_service.main import create_app
from httpx import ASGITransport, AsyncClient

from tests.conftest import FixedClock

HEADERS = {"X-User-Name": "alice"}


async def test_unexpected_error_returns_json_and_rolls_back() -> None:
    class FailingClock:
        def now(self) -> datetime:
            raise RuntimeError("Sensitive internal details")

    store = InMemoryStore()
    service = BonusService(store.transaction, FailingClock())
    async with AsyncClient(
        transport=ASGITransport(app=create_app(service), raise_app_exceptions=False),
        base_url="http://bonus",
    ) as client:
        response = await client.put(
            f"/internal/v1/privilege/operations/{uuid4()}",
            headers=HEADERS,
            json={"price": 1500, "paidFromBalance": False},
        )
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"message": "Internal server error"}
    assert store.accounts == {}
    assert store.operations == {}
    healthy = BonusService(store.transaction, FixedClock())
    result, created = await healthy.apply_purchase("alice", uuid4(), 1500, False)
    assert created
    assert result.privilege.balance == 150


async def test_health_and_initial_account(client: AsyncClient) -> None:
    health = await client.get("/manage/health")
    assert health.status_code == 200
    assert health.json() == {"status": "UP"}
    response = await client.get("/internal/v1/privilege", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"balance": 0, "status": "BRONZE", "history": []}


async def test_purchase_retry_and_reversal_contract(client: AsyncClient) -> None:
    ticket = uuid4()
    url = f"/internal/v1/privilege/operations/{ticket}"
    body = {"price": 1500, "paidFromBalance": False}
    response = await client.put(url, json=body, headers=HEADERS)
    assert response.status_code == 201
    assert response.json() == {
        "ticketUid": str(ticket),
        "price": 1500,
        "paidByMoney": 1500,
        "paidByBonuses": 0,
        "privilege": {"balance": 150, "status": "BRONZE"},
    }
    repeated = await client.put(url, json=body, headers=HEADERS)
    assert repeated.status_code == 200
    assert repeated.json() == response.json()
    account = (await client.get("/internal/v1/privilege", headers=HEADERS)).json()
    assert account["history"] == [
        {
            "date": "2026-10-11T00:00:00Z",
            "ticketUid": str(ticket),
            "balanceDiff": 150,
            "operationType": "FILL_IN_BALANCE",
        }
    ]
    reversed_response = await client.put(url + "/reversal", headers=HEADERS)
    assert reversed_response.status_code == 200
    assert reversed_response.json() == {"balance": 0, "status": "BRONZE"}
    assert (await client.put(url + "/reversal", headers=HEADERS)).status_code == 200
    assert (await client.put(url, json=body, headers=HEADERS)).status_code == 409
    account = (await client.get("/internal/v1/privilege", headers=HEADERS)).json()
    assert len(account["history"]) == 2
    assert account["history"][-1]["operationType"] == "DEBIT_THE_ACCOUNT"


async def test_bonus_payment_and_refund_contract(client: AsyncClient) -> None:
    await client.put(
        f"/internal/v1/privilege/operations/{uuid4()}",
        headers=HEADERS,
        json={"price": 5000, "paidFromBalance": False},
    )
    url = f"/internal/v1/privilege/operations/{uuid4()}"
    payment = await client.put(url, headers=HEADERS, json={"price": 1500, "paidFromBalance": True})
    assert payment.status_code == 201
    assert payment.json()["paidByBonuses"] == 500
    assert payment.json()["paidByMoney"] == 1000
    refund = await client.put(url + "/reversal", headers=HEADERS)
    assert refund.json()["balance"] == 500


@pytest.mark.parametrize(
    "headers", [{}, {"X-User-Name": ""}, {"X-User-Name": "  "}, {"X-User-Name": "a" * 81}]
)
async def test_invalid_username_returns_400(client: AsyncClient, headers: dict[str, str]) -> None:
    response = await client.get("/internal/v1/privilege", headers=headers)
    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "X-User-Name"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"price": -1, "paidFromBalance": False},
        {"price": 1.5, "paidFromBalance": False},
        {"price": "1500", "paidFromBalance": False},
        {"price": True, "paidFromBalance": False},
        {"price": 1500, "paidFromBalance": "true"},
        {"price": 1500},
        {"price": 2**31, "paidFromBalance": False},
    ],
)
async def test_invalid_request_returns_400(client: AsyncClient, body: dict[str, object]) -> None:
    response = await client.put(
        f"/internal/v1/privilege/operations/{uuid4()}", headers=HEADERS, json=body
    )
    assert response.status_code == 400
    assert response.json()["message"] == "Validation failed"
    assert response.json()["errors"]
    assert (await client.get("/internal/v1/privilege", headers=HEADERS)).json()["history"] == []


async def test_invalid_uuid_and_malformed_json(client: AsyncClient) -> None:
    bad_uuid = await client.put(
        "/internal/v1/privilege/operations/not-a-uuid",
        headers=HEADERS,
        json={"price": 1500, "paidFromBalance": False},
    )
    assert bad_uuid.status_code == 400
    malformed = await client.put(
        f"/internal/v1/privilege/operations/{uuid4()}",
        headers={**HEADERS, "Content-Type": "application/json"},
        content="{",
    )
    assert malformed.status_code == 400


async def test_foreign_operation_and_changed_payload(client: AsyncClient) -> None:
    url = f"/internal/v1/privilege/operations/{uuid4()}"
    body = {"price": 1500, "paidFromBalance": False}
    await client.put(url, headers=HEADERS, json=body)
    other = {"X-User-Name": "bob"}
    assert (await client.put(url, headers=other, json=body)).status_code == 404
    assert (await client.put(url + "/reversal", headers=other)).status_code == 404
    conflict = await client.put(
        url, headers=HEADERS, json={"price": 1600, "paidFromBalance": False}
    )
    assert conflict.status_code == 409
    missing = await client.put(
        f"/internal/v1/privilege/operations/{uuid4()}/reversal", headers=HEADERS
    )
    assert missing.status_code == 404


async def test_app_instances_do_not_share_state() -> None:
    async with AsyncClient(
        transport=ASGITransport(
            app=create_app(BonusService(InMemoryStore().transaction, FixedClock()))
        ),
        base_url="http://first",
    ) as first:
        await first.put(
            f"/internal/v1/privilege/operations/{uuid4()}",
            headers=HEADERS,
            json={"price": 1500, "paidFromBalance": False},
        )
    async with AsyncClient(
        transport=ASGITransport(
            app=create_app(BonusService(InMemoryStore().transaction, FixedClock()))
        ),
        base_url="http://second",
    ) as second:
        response = await second.get("/internal/v1/privilege", headers=HEADERS)
        assert response.json()["balance"] == 0


async def test_balance_overflow_is_a_business_validation_error(client: AsyncClient) -> None:
    body = {"price": 2**31 - 1, "paidFromBalance": False}
    for _ in range(10):
        assert (
            await client.put(
                f"/internal/v1/privilege/operations/{uuid4()}", headers=HEADERS, json=body
            )
        ).status_code == 201
    before = (await client.get("/internal/v1/privilege", headers=HEADERS)).json()
    response = await client.put(
        f"/internal/v1/privilege/operations/{uuid4()}", headers=HEADERS, json=body
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "balance"
    assert (await client.get("/internal/v1/privilege", headers=HEADERS)).json() == before


async def test_openapi_uses_contract_paths_and_validation_status(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    operation = paths["/internal/v1/privilege/operations/{ticketUid}"]["put"]
    assert operation["operationId"] == "internalApplyBonusOperation"
    assert "400" in operation["responses"]
    assert "422" not in operation["responses"]
