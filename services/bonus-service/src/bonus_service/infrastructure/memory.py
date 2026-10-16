from __future__ import annotations

import asyncio
from types import TracebackType
from uuid import UUID

from bonus_service.domain.models import Account, PurchaseOperation


class InMemoryRepository:
    def __init__(
        self, accounts: dict[str, Account], operations: dict[UUID, PurchaseOperation]
    ) -> None:
        self.accounts = accounts
        self.operations = operations

    async def get_account(self, username: str) -> Account | None:
        return self.accounts.get(username)

    async def save_account(self, account: Account) -> None:
        self.accounts[account.username] = account

    async def get_operation(self, ticket_uid: UUID) -> PurchaseOperation | None:
        return self.operations.get(ticket_uid)

    async def save_operation(self, operation: PurchaseOperation) -> None:
        self.operations[operation.result.ticket_uid] = operation


class InMemoryStore:
    """One store per app; frozen values and staged writes provide transaction isolation."""

    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}
        self.operations: dict[UUID, PurchaseOperation] = {}
        self.lock = asyncio.Lock()

    def transaction(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self)


class InMemoryUnitOfWork:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self._repository: InMemoryRepository | None = None

    @property
    def repository(self) -> InMemoryRepository:
        if self._repository is None:
            raise RuntimeError("Transaction is not active")
        return self._repository

    async def __aenter__(self) -> InMemoryUnitOfWork:
        await self._store.lock.acquire()
        self._repository = InMemoryRepository(
            self._store.accounts.copy(), self._store.operations.copy()
        )
        return self

    async def commit(self) -> None:
        repository = self.repository
        # No await between assignments: the in-process commit cannot be partially observed.
        self._store.accounts = repository.accounts.copy()
        self._store.operations = repository.operations.copy()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._repository = None
        self._store.lock.release()
