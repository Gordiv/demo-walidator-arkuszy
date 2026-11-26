"""Desktop window (CustomTkinter). The window only collects settings and shows results."""

from __future__ import annotations

import sys

MISSING_GUI = (
    "Brak bibliotek okna programu (CustomTkinter). Zainstaluj je poleceniem:\n"
    '    pip install -e ".[gui]"\n'
    "Wiersz poleceń działa bez nich: walidator --help"
)


def main(argv: list[str] | None = None) -> int:
    """Entry point of ``walidator-gui``: explains a missing ``[gui]`` extra instead of crashing."""
    try:
        from walidator.gui.app import main as run_window  # noqa: PLC0415 - optional dependency
    except ImportError:
        print(MISSING_GUI, file=sys.stderr)
        _show_error(MISSING_GUI)
        return 1
    return run_window(argv)


def _show_error(message: str) -> None:
    """Shows the message in a window too: ``walidator-gui`` has no console to print to."""
    try:
        from tkinter import Tk, messagebox  # noqa: PLC0415

        root = Tk()
        root.withdraw()
        messagebox.showerror("Walidator arkuszy", message, parent=root)
        root.destroy()
    except Exception:
        pass
