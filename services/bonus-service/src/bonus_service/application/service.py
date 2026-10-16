from uuid import UUID

from bonus_service.application.ports import Clock, UnitOfWorkFactory
from bonus_service.domain.errors import OperationConflict, OperationNotFound
from bonus_service.domain.models import (
    Account,
    PaymentResult,
    Privilege,
    purchase,
    reverse,
    validate_price,
    validate_username,
)


class BonusService:
    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def get_account(self, username: str) -> Account:
        validate_username(username)
        async with self._unit_of_work() as transaction:
            account = await transaction.repository.get_account(username)
            if account is None:
                account = Account(username)
                await transaction.repository.save_account(account)
            await transaction.commit()
            return account

    async def apply_purchase(
        self, username: str, ticket_uid: UUID, price: int, paid_from_balance: bool
    ) -> tuple[PaymentResult, bool]:
        validate_username(username)
        validate_price(price)
        async with self._unit_of_work() as transaction:
            repository = transaction.repository
            existing = await repository.get_operation(ticket_uid)
            if existing is not None:
                if existing.username != username:
                    raise OperationNotFound("Bonus operation not found")
                if (
                    existing.reversed
                    or existing.result.price != price
                    or existing.paid_from_balance != paid_from_balance
                ):
                    raise OperationConflict("Ticket already used for another or reversed operation")
                return existing.result, False
            account = await repository.get_account(username) or Account(username)
            updated, operation = purchase(
                account, ticket_uid, price, paid_from_balance, self._clock.now()
            )
            await repository.save_account(updated)
            await repository.save_operation(operation)
            await transaction.commit()
            return operation.result, True

    async def reverse_purchase(self, username: str, ticket_uid: UUID) -> Privilege:
        validate_username(username)
        async with self._unit_of_work() as transaction:
            repository = transaction.repository
            operation = await repository.get_operation(ticket_uid)
            if operation is None or operation.username != username:
                raise OperationNotFound("Bonus operation not found")
            account = await repository.get_account(username)
            if account is None:
                raise OperationNotFound("Bonus account not found")
            if operation.reversed:
                return account.privilege
            updated, reversed_operation = reverse(account, operation, self._clock.now())
            await repository.save_account(updated)
            await repository.save_operation(reversed_operation)
            await transaction.commit()
            return updated.privilege
