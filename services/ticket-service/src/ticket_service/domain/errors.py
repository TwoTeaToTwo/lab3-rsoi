class TicketError(Exception):
    """Base business error."""


class InvalidInput(TicketError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class TicketNotFound(TicketError):
    """No ticket belonging to this user exists."""


class TicketConflict(TicketError):
    """A ticket UUID was reused with different purchase parameters."""
