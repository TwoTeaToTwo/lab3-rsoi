from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from bonus_service.domain.models import Account, PurchaseOperation


class BonusRepository(Protocol):
    async def get_account(self, username: str) -> Account | None: ...

    async def save_account(self, account: Account) -> None: ...

    async def get_operation(self, ticket_uid: UUID) -> PurchaseOperation | None: ...

    async def save_operation(self, operation: PurchaseOperation) -> None: ...


class UnitOfWork(Protocol):
    @property
    def repository(self) -> BonusRepository: ...

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
