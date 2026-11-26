"""Loading, validating and saving rules files (JSON) so that a check can be repeated."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from walidator.errors import RulesError
from walidator.model import RANGE_TYPES, Bound, ColumnRule, ColumnType, RuleSet, TextCase
from walidator.validators import InvalidValue, parse_date

FORMAT_VERSION = 1
_TOP_KEYS = ("wersja", "opis", "usun_duplikaty", "klucz_podobienstwa", "kolumny")
_COLUMN_KEYS = (
    "typ",
    "wymagane",
    "unikalne",
    "min",
    "max",
    "dozwolone",
    "wielkosc_liter",
    "miejsca_po_przecinku",
)
_TYPE_NAMES = [kind.value for kind in ColumnType]
_TYPES = ", ".join(_TYPE_NAMES)
_CASES = ", ".join(case.value for case in TextCase)


def load_rules(path: str | Path) -> RuleSet:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        raise RulesError(f"Nie znaleziono pliku reguł: {path}") from error
    except (OSError, UnicodeDecodeError) as error:
        raise RulesError(
            f"Nie można odczytać pliku reguł {path.name} (wymagane kodowanie UTF-8)."
        ) from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise RulesError(
            f"Plik reguł {path.name} nie jest poprawnym plikiem JSON: błąd w wierszu "
            f"{error.lineno}, znak {error.colno}. Sprawdź przecinki, cudzysłowy i nawiasy."
        ) from error
    return parse_rules(data, path.name)


def parse_rules(data: Any, source: str = "reguły") -> RuleSet:
    """Builds a :class:`RuleSet` and collects every problem, so the user can fix them in one go."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise RulesError(f"Plik {source}: oczekiwano obiektu JSON w nawiasach klamrowych {{ }}.")
    _check_keys(data, _TOP_KEYS, "w głównym obiekcie", problems)
    if data.get("wersja", FORMAT_VERSION) != FORMAT_VERSION:
        problems.append(f"Nieobsługiwana wersja formatu: {data['wersja']} (obsługiwana: 1).")

    rules = RuleSet(
        description=_expect(data, "opis", str, "", where="w głównym obiekcie", problems=problems),
        remove_duplicates=_expect(
            data, "usun_duplikaty", bool, True, where="w głównym obiekcie", problems=problems
        ),
        similarity_key=_expect(
            data, "klucz_podobienstwa", str, None, where="w głównym obiekcie", problems=problems
        ),
    )
    columns = data.get("kolumny", {})
    if not isinstance(columns, dict) or not columns:
        problems.append("Pole „kolumny” musi być niepustym obiektem: nazwa kolumny → reguły.")
        columns = {}
    for name, spec in columns.items():
        rule = _parse_column(name, spec, problems)
        if rule:
            rules.columns[name] = rule
    if problems:
        raise RulesError(f"Plik reguł {source} zawiera błędy:", problems)
    return rules


def _parse_column(name: str, spec: Any, problems: list[str]) -> ColumnRule | None:
    where = f"w kolumnie „{name}”"
    if not isinstance(spec, dict):
        problems.append(f'Reguły {where} muszą być obiektem, np. {{"typ": "tekst"}}.')
        return None
    _check_keys(spec, _COLUMN_KEYS, where, problems)
    type_name = spec.get("typ", ColumnType.TEXT.value)
    if type_name not in {kind.value for kind in ColumnType}:
        problems.append(
            f"Nieznany typ „{type_name}” {where}{_suggest(type_name, _TYPE_NAMES)}. "
            f"Dozwolone: {_TYPES}."
        )
        return None
    rule = ColumnRule(name=name, type=ColumnType(type_name))
    rule.required = _expect(spec, "wymagane", bool, False, where=where, problems=problems)
    rule.unique = _expect(spec, "unikalne", bool, False, where=where, problems=problems)
    allowed = _expect(spec, "dozwolone", list, [], where=where, problems=problems)
    if not all(isinstance(item, str) for item in allowed):
        problems.append(f"Pole „dozwolone” {where} musi być listą tekstów.")
    else:
        rule.allowed = tuple(allowed)
    case_name = _expect(
        spec, "wielkosc_liter", str, TextCase.KEEP.value, where=where, problems=problems
    )
    if case_name in {case.value for case in TextCase}:
        rule.case = TextCase(case_name)
    else:
        problems.append(
            f"Nieznana wartość „wielkosc_liter” {where}: „{case_name}”. Dozwolone: {_CASES}."
        )
    rule.decimals = _parse_decimals(spec, rule, where, problems)
    for key in ("min", "max"):
        if key in spec:
            bound = _parse_bound(spec[key], rule.type, f"„{key}” {where}", problems)
            setattr(rule, "minimum" if key == "min" else "maximum", bound)
    if rule.minimum is not None and rule.maximum is not None and rule.minimum > rule.maximum:
        problems.append(f"„min” jest większe niż „max” {where}.")
    return rule


def _parse_decimals(spec: dict, rule: ColumnRule, where: str, problems: list[str]) -> int | None:
    if "miejsca_po_przecinku" not in spec:
        return None
    value = spec["miejsca_po_przecinku"]
    if rule.type is not ColumnType.DECIMAL:
        problems.append(f"„miejsca_po_przecinku” {where} ma sens tylko dla typu „kwota”.")
    elif not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 6:
        problems.append(f"„miejsca_po_przecinku” {where} musi być liczbą od 0 do 6.")
    else:
        return value
    return None


def _parse_bound(
    value: Any, column_type: ColumnType, where: str, problems: list[str]
) -> Bound | None:
    if column_type not in RANGE_TYPES:
        problems.append(f"Pole {where} działa tylko dla typów: tekst (długość), liczby i daty.")
        return None
    if column_type is ColumnType.DATE:
        try:
            return parse_date(str(value))
        except InvalidValue:
            problems.append(f'Pole {where} musi być datą, np. "2026-01-31".')
            return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        problems.append(f"Pole {where} musi być liczbą.")
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        problems.append(f"Pole {where} musi być liczbą, a jest: {value!r}.")
        return None


def _expect[T](
    data: dict, key: str, kind: type[T], default: T, *, where: str, problems: list[str]
) -> T:
    value = data.get(key)
    if value is None:
        return default
    # bool is a subclass of int in Python, so true/false must not pass as other types
    if isinstance(value, kind) and (kind is bool or not isinstance(value, bool)):
        return value
    names = {bool: "true albo false", str: "tekst w cudzysłowie", list: "lista w nawiasach [ ]"}
    problems.append(f"Pole „{key}” {where} musi być: {names.get(kind, kind.__name__)}.")
    return default


def _check_keys(data: dict, known: tuple[str, ...], where: str, problems: list[str]) -> None:
    for key in data:
        if key not in known:
            problems.append(f"Nieznane pole „{key}” {where}{_suggest(key, known)}.")


def _suggest(word: str, options: list[str] | tuple[str, ...]) -> str:
    match = get_close_matches(str(word), options, n=1, cutoff=0.6)
    return f" – czy chodziło o „{match[0]}”?" if match else ""


# --- saving ----------------------------------------------------------------------------------


def rules_to_dict(rules: RuleSet) -> dict[str, Any]:
    data: dict[str, Any] = {"wersja": FORMAT_VERSION}
    if rules.description:
        data["opis"] = rules.description
    data["usun_duplikaty"] = rules.remove_duplicates
    if rules.similarity_key:
        data["klucz_podobienstwa"] = rules.similarity_key
    data["kolumny"] = {name: _column_to_dict(rule) for name, rule in rules.columns.items()}
    return data


def _column_to_dict(rule: ColumnRule) -> dict[str, Any]:
    spec: dict[str, Any] = {"typ": rule.type.value}
    if rule.required:
        spec["wymagane"] = True
    if rule.unique:
        spec["unikalne"] = True
    for key, bound in (("min", rule.minimum), ("max", rule.maximum)):
        if bound is not None:
            spec[key] = bound.isoformat() if isinstance(bound, date) else _number(bound)
    if rule.allowed:
        spec["dozwolone"] = list(rule.allowed)
    if rule.case is not TextCase.KEEP:
        spec["wielkosc_liter"] = rule.case.value
    if rule.decimals is not None:
        spec["miejsca_po_przecinku"] = rule.decimals
    return spec


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def save_rules(rules: RuleSet, path: str | Path) -> None:
    text = json.dumps(rules_to_dict(rules), ensure_ascii=False, indent=2)
    Path(path).write_text(text + "\n", encoding="utf-8")
