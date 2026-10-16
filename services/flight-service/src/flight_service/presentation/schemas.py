from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from flight_service.domain.models import Flight, FlightPage


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class FlightResponse(ApiModel):
    flight_number: str
    from_airport: str
    to_airport: str
    date: str
    price: int

    @classmethod
    def from_domain(cls, flight: Flight) -> FlightResponse:
        return cls(
            flight_number=flight.flight_number,
            from_airport=f"{flight.from_airport.city} {flight.from_airport.name}",
            to_airport=f"{flight.to_airport.city} {flight.to_airport.name}",
            date=flight.datetime.astimezone(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M"),
            price=flight.price,
        )


class FlightPageResponse(ApiModel):
    page: int
    page_size: int
    total_elements: int
    items: list[FlightResponse]

    @classmethod
    def from_domain(cls, page: FlightPage) -> FlightPageResponse:
        return cls(
            page=page.page,
            page_size=page.page_size,
            total_elements=page.total_elements,
            items=[FlightResponse.from_domain(flight) for flight in page.items],
        )


class ErrorDescription(BaseModel):
    field: str
    error: str


class ErrorResponse(BaseModel):
    message: str


class ValidationErrorResponse(ErrorResponse):
    errors: list[ErrorDescription]
