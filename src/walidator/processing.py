"""Checking and cleaning single cells according to a column rule."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from walidator.cleaners import apply_case, as_text, clean_whitespace, fold_key
from walidator.model import ColumnRule, ColumnType
from walidator.validators import PARSERS, InvalidValue, format_value, has_time, round_decimal

MISSING = "Brak wymaganej wartości"
OUT_OF_RANGE = "Wartość spoza zakresu"
NOT_ALLOWED = "Wartość niedozwolona"
NOT_UNIQUE = "Powtórzona wartość unikalna"
DUPLICATE_ROW = "Duplikat wiersza"
BAD_STRUCTURE = "Zła liczba pól w wierszu"

_CACHE_LIMIT = 20_000
_LEGAL_FORM_WORDS = frozenset({
    "sp", "z", "o", "oo", "zoo", "spzoo", "s", "a", "sa", "j", "k", "sj", "sk", "spj", "spk",
    "spolka", "ograniczona", "odpowiedzialnoscia", "akcyjna", "jawna", "komandytowa", "cywilna",
})  # fmt: skip


class Cell(NamedTuple):
    value: object  # normalised value, None for empty or invalid cells
    text: str  # value as written to CSV and shown in the report
    changed: bool
    error: InvalidValue | None
    time_dropped: bool = False  # a date cell had a time of day, only the date is kept


class ColumnProcessor:
    """Checks one column. Results for repeated text values are cached (cities, statuses, dates)."""

    def __init__(self, rule: ColumnRule, decimal_separator: str = ",") -> None:
        self.rule = rule
        self._parse = PARSERS[rule.type]
        self._separator = decimal_separator
        self._allowed = {value.casefold(): value for value in rule.allowed}
        self._cache: dict[str, Cell] = {}

    def process(self, raw: object) -> Cell:
        if isinstance(raw, str):
            cached = self._cache.get(raw)
            if cached is None:
                cached = self._process(raw)
                if len(self._cache) < _CACHE_LIMIT:
                    self._cache[raw] = cached
            return cached
        return self._process(raw)

    def _process(self, raw: object) -> Cell:
        prepared = clean_whitespace(raw) if isinstance(raw, str) else raw
        if prepared is None or prepared == "":
            if self.rule.required:
                return Cell(None, "", False, InvalidValue(MISSING, MISSING))
            return Cell(None, "", raw not in (None, ""), None)
        try:
            parsed = self._parse(prepared)
            value = self._apply_rules(parsed)
        except InvalidValue as error:
            return Cell(None, as_text(raw), False, error)
        text = format_value(value, self._separator)
        changed = is_changed(raw, value, text)
        if changed and isinstance(parsed, Decimal) and value == parsed:
            # "5" -> "5,00" only pads the decimals of a valid number; that is not a fix
            changed = is_changed(raw, parsed, format_value(parsed, self._separator))
        time_dropped = self.rule.type is ColumnType.DATE and has_time(prepared)
        return Cell(value, text, changed, None, time_dropped)

    def _apply_rules(self, value: object) -> object:
        rule = self.rule
        if rule.type is ColumnType.TEXT:
            value = apply_case(str(value), rule.case)
        if rule.decimals is not None and isinstance(value, Decimal):
            value = round_decimal(value, rule.decimals)
        if self._allowed:
            value = self._check_allowed(value)
        if rule.minimum is not None or rule.maximum is not None:
            self._check_range(value)
        return value

    def _check_allowed(self, value: object) -> object:
        canonical = self._allowed.get(format_value(value, self._separator).casefold())
        if canonical is None:
            shown = ", ".join(self.rule.allowed[:6]) + ("…" if len(self.rule.allowed) > 6 else "")
            raise InvalidValue(NOT_ALLOWED, f"„{format_value(value)}” spoza listy: {shown}")
        return canonical if isinstance(value, str) else value

    def _check_range(self, value: object) -> None:
        rule = self.rule
        if rule.type is ColumnType.TEXT:
            measured: object = len(str(value))
            low, high = "Tekst jest za krótki", "Tekst jest za długi"
            unit = " znaków"
        else:
            measured = Decimal(value) if isinstance(value, int) else value
            low, high = "Wartość mniejsza niż minimum", "Wartość większa niż maksimum"
            unit = ""
        if rule.minimum is not None and measured < rule.minimum:  # type: ignore[operator]
            raise InvalidValue(OUT_OF_RANGE, f"{low} ({_show(rule.minimum)}{unit})")
        if rule.maximum is not None and measured > rule.maximum:  # type: ignore[operator]
            raise InvalidValue(OUT_OF_RANGE, f"{high} ({_show(rule.maximum)}{unit})")


def _show(bound: object) -> str:
    return format_value(bound) if not isinstance(bound, Decimal) else format(bound.normalize(), "f")


def is_changed(raw: object, value: object, text: str) -> bool:
    """True when cleaning changed the value, not just the way XLSX stores it."""
    if isinstance(raw, str):
        return raw != text
    if isinstance(raw, datetime):
        return raw.date() != value or raw.time() != datetime.min.time()
    if isinstance(raw, date | bool):
        return raw != value
    if isinstance(raw, int | float) and isinstance(value, int | Decimal):
        return Decimal(str(raw)) != value
    return as_text(raw) != text


def similarity_key(text: str) -> str:
    """Key for near-duplicates: "ZIELONY KŁOS SP. Z O.O." and "Zielony Kłos sp.z o.o" match."""
    words = "".join(char if char.isalnum() else " " for char in text).split()
    folded = [fold_key(word) for word in words]
    core = [word for word in folded if word not in _LEGAL_FORM_WORDS]
    return "".join(core or folded)
