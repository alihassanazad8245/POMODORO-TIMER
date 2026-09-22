"""Exception types used across the timer."""

from __future__ import annotations


class PomodoroError(Exception):
    """Base class for all expected, user-facing errors."""

    hints: tuple[str, ...] = ()

    def __init__(self, message: str, hints: tuple[str, ...] | None = None) -> None:
        super().__init__(message)
        self.message = message
        if hints is not None:
            self.hints = hints


class InvalidInputError(PomodoroError):
    """Raised when a duration, label, or option cannot be parsed."""


class StorageError(PomodoroError):
    """Raised when the session log or config file cannot be read or written."""

    hints = (
        "Check that the data/ folder exists and is writable",
        "A corrupted file can be renamed or deleted; a fresh one will be created",
    )
