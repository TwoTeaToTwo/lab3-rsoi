class FlightNotFound(Exception):
    """No flight exists with the requested number."""


class InvalidInput(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
