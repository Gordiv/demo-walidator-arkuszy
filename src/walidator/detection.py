"""Guesses the encoding and delimiter of CSV files and the type of every column."""

from __future__ import annotations

import codecs
import csv
import io
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from walidator.cleaners import as_text, clean_whitespace, fold_key
from walidator.model import ColumnRule, ColumnType, TextCase
from walidator.validators import accepts, is_digit_identifier

POLISH_LETTERS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
DELIMITERS = (";", "\t", ",", "|")


def detect_encoding(sample: bytes) -> str:
    """Returns ``utf-8-sig``, ``utf-8``, ``cp1250`` or ``iso-8859-2``.

    Bytes that are not valid UTF-8 are decoded with both Polish 8-bit code pages and the one
    that yields more Polish letters wins (they place ą, ś and ź at different byte values).
    """
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
    except UnicodeDecodeError:
        pass
    else:
        return "utf-8"
    scores = {
        encoding: sum(char in POLISH_LETTERS for char in sample.decode(encoding, "replace"))
        for encoding in ("cp1250", "iso-8859-2")
    }
    return max(scores, key=lambda encoding: (scores[encoding], encoding == "cp1250"))


def detect_delimiter(text: str, max_lines: int = 50) -> str:
    """Picks the delimiter that splits the first lines into the same, largest number of fields.

    Decimal commas make "," split lines unevenly, so ";" wins for typical Polish exports.
    """
    lines = [line for line in text.splitlines()[:max_lines] if line.strip()]
    if not lines:
        return ";"
    best, best_score = ";", (0.0, 0)
    for delimiter in DELIMITERS:
        counts = [
            len(row) for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        ]
        typical, hits = Counter(counts).most_common(1)[0]
        score = (hits / len(counts) if typical > 1 else 0.0, typical)
        if score > best_score:
            best, best_score = delimiter, score
    return best


# --- column types ----------------------------------------------------------------------------

# Checked in this order, so more specific types win over generic ones.
_CONTENT_ORDER = (
    ColumnType.NIP,
    ColumnType.POSTAL_CODE,
    ColumnType.EMAIL,
    ColumnType.URL,
    ColumnType.PHONE,
    ColumnType.DATE,
    ColumnType.BOOLEAN,
    ColumnType.INTEGER,
    ColumnType.DECIMAL,
)

_HEADER_HINTS: tuple[tuple[ColumnType, tuple[str, ...]], ...] = (
    (ColumnType.NIP, ("nip",)),
    (ColumnType.EMAIL, ("email", "e mail", "mail")),
    (ColumnType.PHONE, ("telefon", "tel", "komorka", "phone", "gsm")),
    (ColumnType.POSTAL_CODE, ("kod pocztowy", "pocztowy", "kod", "zip")),
    (ColumnType.URL, ("www", "strona", "url", "witryna")),
    (ColumnType.DATE, ("data", "date", "dzien")),
    (ColumnType.BOOLEAN, ("aktywny", "aktywna", "zgoda", "czy", "vip", "newsletter", "oplacone")),
    (ColumnType.DECIMAL, ("kwota", "cena", "wartosc", "suma", "netto", "brutto", "limit", "saldo")),
    (ColumnType.INTEGER, ("ilosc", "liczba", "sztuk", "szt", "lp", "wiek")),
)
_NUMBER_TYPES = frozenset({ColumnType.INTEGER, ColumnType.DECIMAL})
_TITLE_CASE_WORDS = ("imie", "nazwisko", "miasto", "miejscowosc", "wojewodztwo")
_MONEY_WORDS = ("kwota", "cena", "wartosc", "suma", "netto", "brutto", "limit", "saldo")
_IDENTITY_WORDS = ("id", "nr", "numer", "identyfikator", "kod klienta")
_SIMILARITY_WORDS = ("firma", "nazwa", "kontrahent", "klient")

CONTENT_THRESHOLD = 0.8
HEADER_THRESHOLD = 0.5
REQUIRED_THRESHOLD = 0.95


@dataclass(slots=True)
class ColumnGuess:
    rule: ColumnRule
    source: str  # human-readable reason shown in the GUI and the verbose CLI output
    fill_ratio: float
    example: str


def header_words(header: str) -> list[str]:
    """Splits a header into folded words: "Nr tel. (komórka)" -> ["nr", "tel", "komorka"]."""
    words = "".join(char if char.isalnum() else " " for char in header.casefold()).split()
    return [fold_key(word) for word in words]


def _hint_matches(hint: str, words: list[str]) -> bool:
    if " " in hint:
        return f" {hint} " in f" {' '.join(words)} "
    return any(word == hint or (len(hint) >= 4 and word.startswith(hint)) for word in words)


def header_hint(header: str) -> ColumnType | None:
    words = header_words(header)
    return next(
        (kind for kind, hints in _HEADER_HINTS if any(_hint_matches(h, words) for h in hints)),
        None,
    )


def content_ratio(column_type: ColumnType, values: Sequence[object]) -> float:
    if not values:
        return 0.0
    return sum(accepts(column_type, value) for value in values) / len(values)


def guess_column(header: str, sample: Sequence[object]) -> ColumnGuess:
    """Guesses the type and suggested rules of one column from its header and sample values."""
    values = [_prepare(value) for value in sample]
    filled = [value for value in values if value != ""]
    hint = header_hint(header)
    words = header_words(header)
    # Identifiers (ID, Nr, "000123", PESEL, account numbers) are labels: as numbers they
    # would lose leading zeros or digits beyond Excel's precision, so they stay text.
    # A number header (Kwota, Ilość) wins over the content: a 28-digit amount is an error there.
    if _is_identity(words):
        identifier = True
        hint = None if hint in _NUMBER_TYPES else hint
    else:
        identifier = hint not in _NUMBER_TYPES and any(map(is_digit_identifier, filled))
    candidates = [kind for kind in _CONTENT_ORDER if not (identifier and kind in _NUMBER_TYPES)]

    if hint and (not filled or content_ratio(hint, filled) >= HEADER_THRESHOLD):
        column_type, source = hint, "nagłówek i zawartość" if filled else "nagłówek"
    else:
        column_type = next(
            (kind for kind in candidates if content_ratio(kind, filled) >= CONTENT_THRESHOLD),
            ColumnType.TEXT,
        )
        source = "zawartość" if column_type is not ColumnType.TEXT or filled else "brak danych"

    fill_ratio = len(filled) / len(values) if values else 0.0
    rule = ColumnRule(
        name=header,
        type=column_type,
        required=fill_ratio >= REQUIRED_THRESHOLD,
        unique=_suggest_unique(column_type, words, filled),
    )
    if column_type is ColumnType.TEXT and any(_hint_matches(w, words) for w in _TITLE_CASE_WORDS):
        rule.case = TextCase.TITLE
    if column_type is ColumnType.DECIMAL and any(_hint_matches(w, words) for w in _MONEY_WORDS):
        rule.decimals = 2
    example = next((as_text(value) for value in filled), "")
    return ColumnGuess(rule=rule, source=source, fill_ratio=fill_ratio, example=example)


def _is_identity(words: list[str]) -> bool:
    return any(_hint_matches(hint, words) for hint in _IDENTITY_WORDS)


def _prepare(value: object) -> object:
    return clean_whitespace(value) if isinstance(value, str) else ("" if value is None else value)


def _suggest_unique(column_type: ColumnType, words: list[str], filled: list[object]) -> bool:
    """Suggests "unique" only for identifier columns (ID, Nr, Numer) whose sample has no repeats.

    E-mail or NIP are not assumed unique: in an orders file the same buyer appears many times.
    """
    identity = column_type in {ColumnType.INTEGER, ColumnType.TEXT} and _is_identity(words)
    if not identity or not filled:
        return False
    return len({as_text(value) for value in filled}) == len(filled)


def suggest_similarity_key(headers: Sequence[str], rules: Sequence[ColumnRule]) -> str | None:
    """Picks a company/name column for near-duplicate detection, if there is one."""
    for header, rule in zip(headers, rules, strict=True):
        if rule.type is ColumnType.TEXT and any(
            _hint_matches(word, header_words(header)) for word in _SIMILARITY_WORDS
        ):
            return header
    return None
