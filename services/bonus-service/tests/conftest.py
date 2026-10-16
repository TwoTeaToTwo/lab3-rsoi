from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from bonus_service.application.service import BonusService
from bonus_service.infrastructure.memory import InMemoryStore
from bonus_service.main import create_app
from httpx import ASGITransport, AsyncClient


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 11, 0, 0, tzinfo=UTC)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def service(store: InMemoryStore) -> BonusService:
    return BonusService(store.transaction, FixedClock())


@pytest.fixture
async def client(service: BonusService) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(service)), base_url="http://bonus"
    ) as client:
        yield client
