"""Exceptions whose messages are written in Polish and can be shown to the user as they are."""


class WalidatorError(Exception):
    """Base class for errors the user can understand and fix."""


class FileReadError(WalidatorError):
    """The input file cannot be opened or has no usable data."""


class RulesError(WalidatorError):
    """The rules file is missing, is not valid JSON or breaks the rules format."""

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        self.problems = problems or []
        full = (
            message
            if not self.problems
            else message + "\n" + "\n".join(f"  • {problem}" for problem in self.problems)
        )
        super().__init__(full)


class OutputError(WalidatorError):
    """An output file cannot be written."""


class CancelledError(WalidatorError):
    """The user stopped the check before it finished."""

    def __init__(self) -> None:
        super().__init__("Sprawdzanie zostało przerwane.")
