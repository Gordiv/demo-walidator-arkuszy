"""Column types and validation rules shared by the CLI, the GUI and the rules file."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class ColumnType(StrEnum):
    TEXT = "tekst"
    INTEGER = "liczba_calkowita"
    DECIMAL = "kwota"
    DATE = "data"
    EMAIL = "email"
    PHONE = "telefon"
    POSTAL_CODE = "kod_pocztowy"
    NIP = "nip"
    URL = "url"
    BOOLEAN = "tak_nie"

    @property
    def label(self) -> str:
        return _TYPE_LABELS[self]

    @classmethod
    def from_label(cls, label: str) -> ColumnType:
        return next(kind for kind, text in _TYPE_LABELS.items() if text == label)


_TYPE_LABELS = {
    ColumnType.TEXT: "Tekst",
    ColumnType.INTEGER: "Liczba całkowita",
    ColumnType.DECIMAL: "Kwota / liczba",
    ColumnType.DATE: "Data",
    ColumnType.EMAIL: "E-mail",
    ColumnType.PHONE: "Telefon",
    ColumnType.POSTAL_CODE: "Kod pocztowy",
    ColumnType.NIP: "NIP",
    ColumnType.URL: "Adres WWW",
    ColumnType.BOOLEAN: "Tak / nie",
}

RANGE_TYPES = frozenset({ColumnType.TEXT, ColumnType.INTEGER, ColumnType.DECIMAL, ColumnType.DATE})


class TextCase(StrEnum):
    KEEP = "bez_zmian"
    LOWER = "male"
    UPPER = "wielkie"
    TITLE = "tytulowe"


Bound = Decimal | date


@dataclass(slots=True)
class ColumnRule:
    """How one column is checked. For text columns ``minimum``/``maximum`` limit the length."""

    name: str
    type: ColumnType = ColumnType.TEXT
    required: bool = False
    unique: bool = False
    minimum: Bound | None = None
    maximum: Bound | None = None
    allowed: tuple[str, ...] = ()
    case: TextCase = TextCase.KEEP
    decimals: int | None = None


@dataclass(slots=True)
class RuleSet:
    columns: dict[str, ColumnRule] = field(default_factory=dict)
    similarity_key: str | None = None
    remove_duplicates: bool = True
    description: str = ""

    def find(self, header: str) -> ColumnRule | None:
        """Finds a rule by column name, ignoring letter case and extra spaces."""
        wanted = normalize_header(header)
        return next(
            (rule for name, rule in self.columns.items() if normalize_header(name) == wanted),
            None,
        )


def normalize_header(header: str) -> str:
    return " ".join(header.split()).casefold()
