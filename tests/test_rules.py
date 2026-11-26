import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from walidator.errors import RulesError
from walidator.model import ColumnRule, ColumnType, RuleSet, TextCase
from walidator.rules import load_rules, parse_rules, rules_to_dict, save_rules

VALID = {
    "wersja": 1,
    "opis": "Klienci",
    "usun_duplikaty": False,
    "klucz_podobienstwa": "Firma",
    "kolumny": {
        "NIP": {"typ": "nip", "wymagane": True, "unikalne": True},
        "Kwota": {"typ": "kwota", "min": 0, "max": "100000,50", "miejsca_po_przecinku": 2},
        "Data": {"typ": "data", "min": "2020-01-01", "max": "31.12.2026"},
        "Status": {"typ": "tekst", "dozwolone": ["nowe", "wysłane"], "wielkosc_liter": "male"},
        "Firma": {},
    },
}


def problems_of(data: object) -> list[str]:
    with pytest.raises(RulesError) as error:
        parse_rules(data, "test.json")
    return error.value.problems


def test_parse_rules_reads_every_field() -> None:
    rules = parse_rules(VALID)
    assert rules.description == "Klienci"
    assert rules.remove_duplicates is False
    assert rules.similarity_key == "Firma"
    nip, amount, day, status, company = rules.columns.values()
    assert (nip.type, nip.required, nip.unique) == (ColumnType.NIP, True, True)
    assert (amount.minimum, amount.maximum, amount.decimals) == (
        Decimal(0),
        Decimal("100000.50"),
        2,
    )
    assert (day.minimum, day.maximum) == (date(2020, 1, 1), date(2026, 12, 31))
    assert status.allowed == ("nowe", "wysłane")
    assert status.case is TextCase.LOWER
    assert company.type is ColumnType.TEXT


def test_find_ignores_case_and_spaces() -> None:
    rules = parse_rules(VALID)
    assert rules.find("  nip ") is rules.columns["NIP"]
    assert rules.find("Brak") is None


def test_unknown_keys_get_suggestions() -> None:
    problems = problems_of({"kolumny": {"A": {"typ": "tekst", "wymagny": True}}, "wersjaa": 1})
    assert any("„wymagny”" in p and "„wymagane”" in p for p in problems)
    assert any("„wersjaa”" in p and "„wersja”" in p for p in problems)


def test_unknown_type_is_reported_with_suggestion() -> None:
    problems = problems_of({"kolumny": {"A": {"typ": "emial"}}})
    assert "„email”" in problems[0]


def test_all_problems_are_collected_at_once() -> None:
    problems = problems_of(
        {
            "wersja": 2,
            "usun_duplikaty": "tak",
            "kolumny": {
                "A": {"typ": "tekst", "wymagane": "tak", "dozwolone": "x"},
                "B": {"typ": "email", "min": 1},
                "C": {"typ": "kwota", "min": 10, "max": 1, "miejsca_po_przecinku": 9},
                "D": {"typ": "tekst", "miejsca_po_przecinku": 2, "wielkosc_liter": "duze"},
                "E": {"typ": "data", "min": "kiedyś"},
                "F": {"typ": "liczba_calkowita", "max": "dużo", "unikalne": 1},
                "G": "tekst",
            },
        }
    )
    expected_fragments = [
        "wersja formatu",
        "„usun_duplikaty”",
        "„wymagane”",
        "„dozwolone”",
        "działa tylko dla typów",
        "„min” jest większe",
        "od 0 do 6",
        "tylko dla typu „kwota”",
        "„wielkosc_liter”",
        "musi być datą",
        "musi być liczbą",
        "„unikalne”",
        "muszą być obiektem",
    ]
    for fragment in expected_fragments:
        assert any(fragment in problem for problem in problems), fragment


def test_rules_must_be_an_object_with_columns() -> None:
    with pytest.raises(RulesError, match="obiektu JSON"):
        parse_rules([1, 2])
    assert any("niepustym obiektem" in p for p in problems_of({"kolumny": {}}))


def test_dozwolone_must_contain_text() -> None:
    assert any("listą tekstów" in p for p in problems_of({"kolumny": {"A": {"dozwolone": [1]}}}))


def test_min_rejects_booleans_and_objects() -> None:
    problems = problems_of({"kolumny": {"A": {"typ": "kwota", "min": True, "max": [1]}}})
    assert len([p for p in problems if "musi być liczbą" in p]) == 2


def test_load_rules_reports_json_syntax_position(tmp_path: Path) -> None:
    path = tmp_path / "reguly.json"
    path.write_text('{\n  "kolumny": {\n    "A": {"typ": "tekst",}\n  }\n}', encoding="utf-8")
    with pytest.raises(RulesError, match=r"wierszu 3"):
        load_rules(path)


def test_load_rules_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="Nie znaleziono pliku reguł"):
        load_rules(tmp_path / "brak.json")


def test_load_rules_wrong_encoding(tmp_path: Path) -> None:
    path = tmp_path / "reguly.json"
    path.write_bytes('{"kolumny": {"Ilość": {}}}'.encode("cp1250"))
    with pytest.raises(RulesError, match="UTF-8"):
        load_rules(path)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    original = parse_rules(VALID)
    path = tmp_path / "reguly.json"
    save_rules(original, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["kolumny"]["Kwota"] == {
        "typ": "kwota",
        "min": 0,
        "max": 100000.5,
        "miejsca_po_przecinku": 2,
    }
    assert data["kolumny"]["Data"]["max"] == "2026-12-31"
    assert load_rules(path) == original


def test_rules_to_dict_omits_defaults() -> None:
    rules = RuleSet(columns={"A": ColumnRule("A")})
    assert rules_to_dict(rules) == {
        "wersja": 1,
        "usun_duplikaty": True,
        "kolumny": {"A": {"typ": "tekst"}},
    }


def test_sample_rules_files_are_valid() -> None:
    folder = Path(__file__).resolve().parent.parent / "przyklady"
    for path in folder.glob("reguly_*.json"):
        assert load_rules(path).columns


# --- regressions -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column_type", "key", "value"),
    [
        ("kwota", "min", "NaN"),
        ("kwota", "max", "sNaN"),
        ("kwota", "min", float("inf")),
        ("kwota", "max", float("nan")),
        ("liczba_calkowita", "max", "1e9999999"),
        ("kwota", "min", "-1e40"),
        ("tekst", "max", "Infinity"),
        ("kwota", "max", "1" * 50),
    ],
)
def test_bounds_must_be_finite_and_reasonable(column_type: str, key: str, value: object) -> None:
    problems = problems_of({"kolumny": {"A": {"typ": column_type, key: value}}})
    assert len(problems) == 1
    assert "rozsądną liczbą" in problems[0]


def test_huge_bounds_from_json_text_are_rejected_quickly(tmp_path: Path) -> None:
    path = tmp_path / "reguly.json"
    path.write_text(
        '{"kolumny": {"A": {"typ": "kwota", "min": 1e400, "max": "1e9999999"}}}', encoding="utf-8"
    )
    with pytest.raises(RulesError) as error:
        load_rules(path)
    assert len(error.value.problems) == 2


def test_suggestions_end_with_a_single_question_mark() -> None:
    problems = problems_of({"kolumny": {"A": {"typ": "emial", "wymagny": True}}})
    assert problems
    assert not any("?." in problem for problem in problems)
    assert any(problem.endswith("Czy chodziło o „wymagane”?") for problem in problems)
