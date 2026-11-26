"""Log file for technical details; the user sees only short Polish messages."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WalidatorArkuszy"
LOG_FILE = LOG_DIR / "walidator.log"


def setup_logging(verbose: bool = False) -> Path:
    """Logs to a rotating file; falls back to no file when the folder cannot be created."""
    root = logging.getLogger("walidator")
    if root.handlers:
        return LOG_FILE
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    return LOG_FILE
