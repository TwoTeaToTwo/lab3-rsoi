from typing import Literal

ServiceName = Literal["Flight", "Ticket", "Bonus"]


class GatewayError(Exception):
    pass


class NotFound(GatewayError):
    pass


class Unavailable(GatewayError):
    pass


class UpstreamUnavailable(Unavailable):
    def __init__(self, service: ServiceName) -> None:
        super().__init__(f"{service} Service unavailable")
        self.service = service


class UpstreamRejected(GatewayError):
    def __init__(self, service: ServiceName, status_code: int) -> None:
        super().__init__(f"{service} Service rejected the operation")
        self.service = service
        self.status_code = status_code


class InvalidInput(GatewayError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
