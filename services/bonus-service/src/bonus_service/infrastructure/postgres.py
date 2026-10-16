from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bonus_service.domain.models import (
    Account,
    HistoryEntry,
    OperationType,
    PaymentResult,
    Privilege,
    PrivilegeStatus,
    PurchaseOperation,
)
from bonus_service.infrastructure.orm import HistoryRow, OperationRow, PrivilegeRow


class PostgresRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts: dict[str, tuple[PrivilegeRow, int]] = {}

    async def get_account(self, username: str) -> Account:
        # Upsert handles concurrent first access; the row lock protects balance and history.
        await self._session.execute(
            insert(PrivilegeRow)
            .values(username=username)
            .on_conflict_do_nothing(index_elements=[PrivilegeRow.username])
        )
        row = (
            await self._session.scalars(
                select(PrivilegeRow).where(PrivilegeRow.username == username).with_for_update()
            )
        ).one()
        history = tuple(
            HistoryEntry(
                item.datetime,
                item.ticket_uid,
                item.balance_diff,
                OperationType(item.operation_type),
            )
            for item in (
                await self._session.scalars(
                    select(HistoryRow)
                    .where(HistoryRow.privilege_id == row.id)
                    .order_by(HistoryRow.id)
                )
            ).all()
        )
        self._accounts[username] = row, len(history)
        return Account(username, row.balance, PrivilegeStatus(row.status), history)

    async def save_account(self, account: Account) -> None:
        row, history_size = self._accounts[account.username]
        row.balance, row.status = account.balance, account.status.value
        for entry in account.history[history_size:]:
            self._session.add(
                HistoryRow(
                    privilege_id=row.id,
                    ticket_uid=entry.ticket_uid,
                    datetime=entry.date,
                    balance_diff=entry.balance_diff,
                    operation_type=entry.operation_type.value,
                )
            )
        self._accounts[account.username] = row, len(account.history)

    async def get_operation(self, ticket_uid: UUID) -> PurchaseOperation | None:
        # Lock even a missing UUID, before locking its account. Transaction-scoped,
        # shared across processes; hash collisions only serialize unrelated operations.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(ticket_uid)},
        )
        row = await self._session.scalar(
            select(OperationRow).where(OperationRow.ticket_uid == ticket_uid)
        )
        if row is None:
            return None
        username = (
            await self._session.scalars(
                select(PrivilegeRow.username).where(PrivilegeRow.id == row.privilege_id)
            )
        ).one()
        result = PaymentResult(
            ticket_uid,
            row.price,
            row.paid_by_money,
            row.paid_by_bonuses,
            Privilege(row.result_balance, PrivilegeStatus(row.result_status)),
        )
        return PurchaseOperation(username, row.paid_from_balance, result, row.accrued, row.reversed)

    async def save_operation(self, operation: PurchaseOperation) -> None:
        row = await self._session.scalar(
            select(OperationRow).where(OperationRow.ticket_uid == operation.result.ticket_uid)
        )
        if row is not None:
            row.reversed = operation.reversed
            return
        account, _ = self._accounts[operation.username]
        result = operation.result
        self._session.add(
            OperationRow(
                ticket_uid=result.ticket_uid,
                privilege_id=account.id,
                paid_from_balance=operation.paid_from_balance,
                price=result.price,
                paid_by_money=result.paid_by_money,
                paid_by_bonuses=result.paid_by_bonuses,
                accrued=operation.accrued,
                result_balance=result.privilege.balance,
                result_status=result.privilege.status.value,
                reversed=operation.reversed,
            )
        )


class PostgresUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._session: AsyncSession | None = None
        self._repository: PostgresRepository | None = None

    @property
    def repository(self) -> PostgresRepository:
        if self._repository is None:
            raise RuntimeError("Transaction is not active")
        return self._repository

    async def __aenter__(self) -> PostgresUnitOfWork:
        self._session = self._sessions()
        await self._session.begin()
        self._repository = PostgresRepository(self._session)
        return self

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Transaction is not active")
        await self._session.commit()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is not None:
            try:
                await self._session.rollback()
            finally:
                await self._session.close()
                self._session = None
                self._repository = None
