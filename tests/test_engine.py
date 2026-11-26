import threading
from datetime import datetime
from pathlib import Path

import pytest
from python_calamine import CalamineWorkbook

from walidator.engine import RunOptions, analyze, run_check
from walidator.errors import CancelledError, FileReadError, OutputError, RulesError
from walidator.model import ColumnRule, ColumnType, RuleSet
from walidator.readers import open_table
from walidator.rules import parse_rules

HEADER = ["ID", "Firma", "NIP", "E-mail", "Kwota", "Data"]
ROWS = [
    HEADER,
    ["1", "Zielony Kłos Sp. z o.o.", "1234563218", "biuro@example.com", "1 200,50", "01.02.2026"],
    ["2", "ZIELONY KŁOS SP Z OO", "123-456-32-18", "BIURO2@EXAMPLE.COM", "99", "2026-02-02"],
    ["3", "Srebrny Most", "1234563219", "kontakt@example", "x", "31.02.2026"],
    ["1", "Złoty Sad", "", "sad@example.com", "5", "3.2.2026"],
    ["2", "ZIELONY KŁOS SP Z OO", "123-456-32-18", "BIURO2@EXAMPLE.COM", "99", "2026-02-02"],
    ["6", "Dodatkowe pole", "", "x@example.com", "1", "01.01.2026", "nadmiarowe"],
    [],
    ["7", "Pusty wiersz był wyżej", "", "y@example.com", "1", "01.01.2026"],
]


def options(tmp_path: Path, **extra: object) -> RunOptions:
    return RunOptions(output_dir=tmp_path / "wynik", **extra)  # type: ignore[arg-type]


def read_sheet(path: Path) -> list[list[object]]:
    book = CalamineWorkbook.from_path(str(path))
    return book.get_sheet_by_index(0).to_python()


def test_analyze_detects_columns_and_similarity_key(make_csv) -> None:
    analysis = analyze(make_csv(ROWS))
    types = {name: rule.type for name, rule in analysis.rules.columns.items()}
    assert types == {
        "ID": ColumnType.INTEGER,
        "Firma": ColumnType.TEXT,
        "NIP": ColumnType.NIP,
        "E-mail": ColumnType.EMAIL,
        "Kwota": ColumnType.DECIMAL,
        "Data": ColumnType.DATE,
    }
    assert analysis.rules.similarity_key == "Firma"
    assert analysis.examples["E-mail"] == "biuro@example.com"
    assert analysis.info.description == "CSV, UTF-8, średnik"


def test_run_check_counts_and_reasons(make_csv, tmp_path: Path) -> None:
    rules = analyze(make_csv(ROWS)).rules
    rules.columns["ID"].unique = True
    progress: list[tuple[float | None, int]] = []
    result = run_check(
        make_csv(ROWS), rules, options(tmp_path), progress=lambda f, n: progress.append((f, n))
    )

    assert result.total == 7
    assert result.duplicates == 1
    assert result.rejected == 4  # invalid values, repeated ID, duplicate row, extra field
    assert result.fixed == 3  # dates written as DD.MM.YYYY become ISO
    assert result.unchanged == 0
    assert progress[-1] == (1.0, 7)
    categories = dict(result.categories)
    assert categories["Niepoprawny NIP"] == 1
    assert categories["Powtórzona wartość unikalna"] == 1
    assert categories["Duplikat wiersza"] == 1
    assert categories["Zła liczba pól w wierszu"] == 1
    assert result.problems_total == sum(categories.values())
    rows_with_problems = {problem.row for problem in result.problems}
    assert rows_with_problems == {4, 5, 6, 7}

    assert [len(group.rows) for group in result.near_duplicates] == [2]
    assert result.near_duplicate_rows == 2


def test_run_check_writes_csv_outputs(make_csv, tmp_path: Path) -> None:
    result = run_check(make_csv(ROWS), None, options(tmp_path))
    clean = result.outputs.clean.read_text(encoding="utf-8-sig").splitlines()
    assert clean[0] == ";".join(HEADER)
    assert clean[1] == "1;Zielony Kłos Sp. z o.o.;1234563218;biuro@example.com;1200,50;2026-02-01"
    rejected = result.outputs.rejected.read_text(encoding="utf-8-sig").splitlines()
    assert rejected[0].startswith("Nr wiersza;ID;")
    assert any("Zła cyfra kontrolna NIP" in line for line in rejected)
    assert result.outputs.report is not None
    assert result.outputs.report.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_run_check_writes_xlsx_with_native_types(make_csv, tmp_path: Path) -> None:
    result = run_check(make_csv(ROWS), None, options(tmp_path, output_format="xlsx"))
    assert result.outputs.clean.suffix == ".xlsx"
    clean = read_sheet(result.outputs.clean)
    assert clean[0] == HEADER
    assert clean[1][4] == 1200.5
    assert str(clean[1][5]) == "2026-02-01"
    rejected = read_sheet(result.outputs.rejected)
    assert rejected[0][-1] == "Powody odrzucenia"
    assert len(rejected) == result.rejected + 1


def test_rows_with_errors_do_not_block_later_unique_values(make_csv, tmp_path: Path) -> None:
    rows = [["Nr", "E-mail"], ["A1", "zly-adres"], ["A1", "ok@example.com"]]
    rules = RuleSet(
        columns={
            "Nr": ColumnRule("Nr", unique=True),
            "E-mail": ColumnRule("E-mail", ColumnType.EMAIL),
        }
    )
    result = run_check(make_csv(rows), rules, options(tmp_path))
    assert (result.rejected, result.accepted) == (1, 1)


def test_partial_rules_are_completed_by_detection(make_csv, tmp_path: Path) -> None:
    rules = parse_rules({"kolumny": {"kwota": {"typ": "kwota", "max": 100}}})
    result = run_check(
        make_csv(ROWS),
        rules,
        options(tmp_path),
    )
    by_name = {stats.name: stats for stats in result.columns}
    assert by_name["Kwota"].rule.maximum == 100
    assert by_name["NIP"].rule.type is ColumnType.NIP
    assert result.categories["Wartość spoza zakresu"] == 1


def test_missing_required_column_in_rules_is_an_error(make_csv) -> None:
    rules = parse_rules({"kolumny": {"PESEL": {"wymagane": True}}})
    with pytest.raises(RulesError, match="PESEL"):
        analyze(make_csv(ROWS), rules=rules)


def test_missing_optional_column_and_similarity_key_give_warnings(make_csv) -> None:
    rules = parse_rules({"klucz_podobienstwa": "Kontrahent", "kolumny": {"PESEL": {}}})
    warnings = analyze(make_csv(ROWS), rules=rules).warnings
    assert any("PESEL" in warning for warning in warnings)
    assert any("Kontrahent" in warning for warning in warnings)


def test_cancel_removes_partial_files(make_csv, tmp_path: Path) -> None:
    rows = [HEADER] + [
        [str(i), "Firma", "", f"a{i}@example.com", "1", "01.01.2026"] for i in range(1, 5000)
    ]
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CancelledError):
        run_check(make_csv(rows), None, options(tmp_path), cancel=cancel)
    assert not list((tmp_path / "wynik").glob("dane_*"))


def test_locked_output_folder_gives_friendly_error(make_csv, tmp_path: Path) -> None:
    blocker = tmp_path / "plik_zamiast_folderu"
    blocker.write_text("x")
    with pytest.raises(OutputError, match="Nie można"):
        run_check(make_csv(ROWS), None, RunOptions(output_dir=blocker / "wynik"))


def test_xlsx_input_with_offset_header_and_native_values(make_xlsx, tmp_path: Path) -> None:
    path = make_xlsx(
        [
            ["Telefon", "Data", "Kod", "Kod"],
            [600123456, datetime(2026, 2, 1), 950, "x"],
            [None, None, None, None],
            ["+48 601 000 000", "02.02.2026", "00-951", "y"],
        ],
        first_row=2,
    )
    with open_table(path) as source:
        assert source.info.header_row == 3
        assert source.info.headers == ["Telefon", "Data", "Kod", "Kod (2)"]
        assert [number for number, _ in source.rows()] == [4, 6]
    result = run_check(path, None, options(tmp_path))
    assert result.total == 2
    assert result.rejected == 0
    assert result.outputs.clean.suffix == ".xlsx"
    assert read_sheet(result.outputs.clean)[1][:3] == [
        "+48 600 123 456",
        read_sheet(result.outputs.clean)[1][1],
        "00-950",
    ]


def test_reader_errors_are_friendly(tmp_path: Path, make_csv) -> None:
    with pytest.raises(FileReadError, match="Nie znaleziono"):
        analyze(tmp_path / "brak.csv")
    (tmp_path / "plik.pdf").write_text("x")
    with pytest.raises(FileReadError, match="Nieobsługiwany"):
        analyze(tmp_path / "plik.pdf")
    (tmp_path / "pusty.csv").write_text("  \n")
    with pytest.raises(FileReadError, match="pusty"):
        analyze(tmp_path / "pusty.csv")
    (tmp_path / "zepsuty.xlsx").write_bytes(b"to nie jest zip")
    with pytest.raises(FileReadError, match="poprawnym arkuszem"):
        analyze(tmp_path / "zepsuty.xlsx")
    with pytest.raises(FileReadError, match="nie zawiera nagłówka"):
        analyze(make_csv([["", ""], ["", ""]], name="puste_wiersze.csv"))


def test_missing_sheet_lists_available_sheets(make_xlsx) -> None:
    path = make_xlsx([["A"], ["1"]], sheet="Dane")
    with pytest.raises(FileReadError, match="Dostępne arkusze: Dane"):
        analyze(path, sheet="Klienci")


def test_cp1250_file_with_tab_extension(make_csv) -> None:
    path = make_csv(
        [["Miasto", "Kwota"], ["Łódź", "12,5"]], name="dane.tsv", delimiter="\t", encoding="cp1250"
    )
    analysis = analyze(path)
    assert analysis.info.delimiter == "\t"
    assert analysis.info.encoding == "cp1250"
    assert analysis.examples["Miasto"] == "Łódź"
