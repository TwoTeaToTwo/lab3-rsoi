from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PrivilegeRow(Base):
    __tablename__ = "privilege"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_privilege_balance"),
        CheckConstraint("status IN ('BRONZE','SILVER','GOLD')", name="ck_privilege_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(80), server_default="BRONZE")
    balance: Mapped[int] = mapped_column(Integer, server_default="0")


class HistoryRow(Base):
    __tablename__ = "privilege_history"
    __table_args__ = (
        CheckConstraint("balance_diff >= 0", name="ck_history_amount"),
        CheckConstraint(
            "operation_type IN ('FILL_IN_BALANCE','DEBIT_THE_ACCOUNT')", name="ck_history_type"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    privilege_id: Mapped[int] = mapped_column(ForeignKey("privilege.id"), index=True)
    ticket_uid: Mapped[UUID]
    datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    balance_diff: Mapped[int]
    operation_type: Mapped[str] = mapped_column(String(20))


class OperationRow(Base):
    __tablename__ = "bonus_operation"
    __table_args__ = (
        UniqueConstraint("ticket_uid", name="uq_bonus_operation_ticket_uid"),
        CheckConstraint(
            "price >= 0 AND paid_by_money >= 0 AND paid_by_bonuses >= 0 "
            "AND accrued >= 0 AND result_balance >= 0",
            name="ck_operation_amounts",
        ),
        CheckConstraint("paid_by_money + paid_by_bonuses = price", name="ck_operation_payment"),
        CheckConstraint("result_status IN ('BRONZE','SILVER','GOLD')", name="ck_operation_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_uid: Mapped[UUID]
    privilege_id: Mapped[int] = mapped_column(ForeignKey("privilege.id"), index=True)
    paid_from_balance: Mapped[bool] = mapped_column(Boolean)
    price: Mapped[int]
    paid_by_money: Mapped[int]
    paid_by_bonuses: Mapped[int]
    accrued: Mapped[int]
    result_balance: Mapped[int]
    result_status: Mapped[str] = mapped_column(String(80))
    reversed: Mapped[bool] = mapped_column(Boolean, server_default="false")
