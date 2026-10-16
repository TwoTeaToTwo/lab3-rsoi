from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Airport:
    id: int
    name: str
    city: str
    country: str


@dataclass(frozen=True, slots=True)
class Flight:
    id: int
    flight_number: str
    datetime: datetime
    from_airport: Airport
    to_airport: Airport
    price: int


@dataclass(frozen=True, slots=True)
class FlightPage:
    page: int
    page_size: int
    total_elements: int
    items: tuple[Flight, ...]
