from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TicketRow(Base):
    __tablename__ = "ticket"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_ticket_price"),
        CheckConstraint("status IN ('PAID','CANCELED')", name="ck_ticket_status"),
        Index("ix_ticket_username_id", "username", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_uid: Mapped[UUID] = mapped_column(unique=True)
    username: Mapped[str] = mapped_column(String(80))
    flight_number: Mapped[str] = mapped_column(String(20))
    price: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
