from dataclasses import dataclass


class ExitCode:
    SUCCESS = 0
    INTERNAL_ERROR = 1
    VALIDATION_ERROR = 2
    NOT_FOUND = 3
    AMBIGUITY = 4
    LEDGER_BUSY = 5


@dataclass
class FieldbookError(Exception):
    message: str
    exit_code: int = ExitCode.INTERNAL_ERROR

    def __str__(self) -> str:
        return self.message


class ValidationError(FieldbookError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.VALIDATION_ERROR)


class NotFoundError(FieldbookError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.NOT_FOUND)


class AmbiguityError(FieldbookError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.AMBIGUITY)


class LedgerBusyError(FieldbookError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.LEDGER_BUSY)
