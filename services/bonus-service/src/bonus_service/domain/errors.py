class BonusError(Exception):
    """Base business error."""


class InvalidInput(BonusError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class OperationNotFound(BonusError):
    """No operation belonging to this user exists."""


class OperationConflict(BonusError):
    """A ticket identifier was reused with incompatible data."""
