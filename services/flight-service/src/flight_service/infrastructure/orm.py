from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AirportRow(Base):
    __tablename__ = "airport"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(255))


class FlightRow(Base):
    __tablename__ = "flight"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_flight_price"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    flight_number: Mapped[str] = mapped_column(String(20), unique=True)
    datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    from_airport_id: Mapped[int] = mapped_column(ForeignKey("airport.id"))
    to_airport_id: Mapped[int] = mapped_column(ForeignKey("airport.id"))
    price: Mapped[int]
    from_airport: Mapped[AirportRow] = relationship(foreign_keys=[from_airport_id], lazy="raise")
    to_airport: Mapped[AirportRow] = relationship(foreign_keys=[to_airport_id], lazy="raise")
