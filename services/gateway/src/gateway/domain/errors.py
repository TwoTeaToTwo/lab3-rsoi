class GatewayError(Exception):
    pass


class NotFound(GatewayError):
    pass


class Unavailable(GatewayError):
    pass


class InvalidInput(GatewayError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
