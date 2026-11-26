"""Text clean-up helpers used before a value is checked."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from walidator.model import TextCase

_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
_WHITESPACE = re.compile(r"\s+")
_LOWERCASE_PARTICLES = frozenset({"nad", "pod", "przy", "na", "w", "we", "z", "ze", "i", "o"})
_FOLD_EXTRA = str.maketrans({"ł": "l", "Ł": "l", "ß": "ss"})


def clean_whitespace(text: str) -> str:
    """Removes invisible characters, trims the text and collapses inner whitespace."""
    return _WHITESPACE.sub(" ", text.translate(_INVISIBLE)).strip()


def as_text(value: object) -> str:
    """Turns a cell value into text the way a person would read it in Excel."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "tak" if value else "nie"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else str(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def plural(count: int, one: str, few: str, many: str) -> str:
    """Polish plural forms: 1 wiersz, 2 wiersze, 5 wierszy, 22 wiersze."""
    if count == 1:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def apply_case(text: str, case: TextCase) -> str:
    match case:
        case TextCase.LOWER:
            return text.lower()
        case TextCase.UPPER:
            return text.upper()
        case TextCase.TITLE:
            return smart_title(text)
        case _:
            return text


def smart_title(text: str) -> str:
    """Title-cases text written entirely in upper or lower case; mixed case is left alone.

    Short Polish particles stay lower case: "NOWE MIASTO NAD PILICĄ" -> "Nowe Miasto nad Pilicą".
    """
    if not (text.isupper() or text.islower()):
        return text
    words = text.lower().split(" ")
    titled = [
        word if index and word in _LOWERCASE_PARTICLES else _title_word(word)
        for index, word in enumerate(words)
    ]
    return " ".join(titled)


def _title_word(word: str) -> str:
    return "-".join(part[:1].upper() + part[1:] for part in word.split("-"))


def fold_key(text: str) -> str:
    """Builds a loose comparison key: no case, no Polish diacritics, letters and digits only."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_FOLD_EXTRA).casefold())
    return "".join(char for char in decomposed if char.isalnum())
