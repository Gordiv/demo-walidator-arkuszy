"""Values must survive cleaning unchanged and output files must be safe and complete."""

import csv
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import xlsxwriter

from walidator.engine import RunOptions, analyze, run_check
from walidator.errors import OutputError
from walidator.model import ColumnRule, ColumnType, RuleSet
from walidator.report import render_report, write_report
from walidator.results import MAX_NEAR_DUPLICATE_GROUPS

from .test_engine import ROWS, options, read_sheet


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, delimiter=";"))


# --- values ----------------------------------------------------------------------------------


def test_leading_zeros_in_identifiers_are_kept(make_csv, tmp_path: Path) -> None:
    rows = [["PESEL", "Numer klienta"], ["02270803628", "000123"], ["85010112345", "000124"]]
    result = run_check(make_csv(rows), None, options(tmp_path))
    assert read_csv(result.outputs.clean)[1:] == rows[1:]
    assert (result.fixed, result.rejected) == (0, 0)


def test_long_integers_are_exact_in_xlsx(make_csv, tmp_path: Path) -> None:
    accounts = ["61109010140000071219812874", "61109010140000071219812875"]
    rows = [["Konto"], *([account] for account in accounts)]
    rules = RuleSet(columns={"Konto": ColumnRule("Konto", ColumnType.INTEGER, unique=True)})
    result = run_check(make_csv(rows), rules, options(tmp_path, output_format="xlsx"))
    assert result.rejected == 0
    assert [row[0] for row in read_sheet(result.outputs.clean)[1:]] == accounts


def test_unique_check_compares_long_integers_exactly(make_csv, tmp_path: Path) -> None:
    rows = [["Konto", "Lp"], ["1" * 20, "1"], ["1" * 19 + "2", "2"], ["1" * 20, "3"]]
    rules = RuleSet(columns={"Konto": ColumnRule("Konto", ColumnType.INTEGER, unique=True)})
    result = run_check(make_csv(rows), rules, options(tmp_path, output_format="xlsx"))
    assert result.categories["Powtórzona wartość unikalna"] == 1
    assert [problem.row for problem in result.problems] == [4]


def test_csv_outputs_neutralise_formulas(make_csv, tmp_path: Path) -> None:
    rows = [
        ["Nazwa", "Kwota", "E-mail"],
        ['=HYPERLINK("http://zly.example","klik")', "-12,50", "a@example.com"],
        ["+SUM(1,2)", "-2", "b@example.com"],
        ["@cmd", "5", "zly-adres"],
        ["-minus", "abc", "c@example.com"],
    ]
    result = run_check(make_csv(rows), None, options(tmp_path))
    clean = read_csv(result.outputs.clean)
    assert clean[1] == ['\'=HYPERLINK("http://zly.example","klik")', "-12,50", "a@example.com"]
    assert clean[2] == ["'+SUM(1,2)", "-2,00", "b@example.com"]
    rejected = read_csv(result.outputs.rejected)
    assert rejected[1][1:3] == ["'@cmd", "5"]
    assert rejected[2][1:3] == ["'-minus", "abc"]


def test_csv_outputs_keep_phone_numbers_readable(make_csv, tmp_path: Path) -> None:
    rows = [["Telefon", "Uwagi"], ["600 123 456", "x"], ["+48 22 123 45 67", "=1+1"]]
    result = run_check(make_csv(rows), None, options(tmp_path))
    assert read_csv(result.outputs.clean)[1:] == [
        ["+48 600 123 456", "x"],
        ["+48 22 123 45 67", "'=1+1"],
    ]


def test_xlsx_outputs_keep_formulas_as_text(make_csv, tmp_path: Path) -> None:
    rows = [["Nazwa"], ["=1+1"]]
    result = run_check(make_csv(rows), None, options(tmp_path, output_format="xlsx"))
    assert read_sheet(result.outputs.clean)[1] == ["=1+1"]


def test_amount_with_too_many_digits_rejects_only_its_row(make_csv, tmp_path: Path) -> None:
    rows = [["Kwota"], ["1" * 28], ["5"]]
    rules = RuleSet(columns={"Kwota": ColumnRule("Kwota", ColumnType.DECIMAL, decimals=2)})
    result = run_check(make_csv(rows), rules, options(tmp_path))
    assert (result.rejected, result.accepted) == (1, 1)
    assert result.categories["Niepoprawna liczba"] == 1


def test_padding_an_amount_is_not_counted_as_a_fix(make_csv, tmp_path: Path) -> None:
    amounts = ["5", "12,5", "7,00", "1.234,50", "2,345"]
    rows = [["Kwota", "Uwagi"], *([amount, f"uwaga {amount}"] for amount in amounts)]
    result = run_check(make_csv(rows), None, options(tmp_path))
    clean = [row[0] for row in read_csv(result.outputs.clean)[1:]]
    assert clean == ["5,00", "12,50", "7,00", "1234,50", "2,35"]
    assert result.fixed == 2
    assert result.columns[0].fix_examples == [("1.234,50", "1234,50"), ("2,345", "2,35")]


def test_date_with_time_keeps_only_the_date_and_warns(make_csv, tmp_path: Path) -> None:
    rows = [
        ["Data"],
        ["2026-02-01 13:45"],
        ["2026-02-02"],
        ["2026-02-03 00:00"],
        ["01.02.2026 25:99"],
    ]
    result = run_check(make_csv(rows), None, options(tmp_path))
    assert read_csv(result.outputs.clean)[1] == ["2026-02-01"]
    assert result.rejected == 1
    assert any("„Data”" in w and "1 komórce" in w and "godzin" in w for w in result.warnings)


# --- structure and warnings ------------------------------------------------------------------


def test_mixed_encoding_gives_a_warning(tmp_path: Path) -> None:
    path = tmp_path / "mieszane.csv"
    body = "".join(f"{i};Warszawa\r\n" for i in range(8000))
    path.write_bytes(("Lp;Miasto\r\n" + body).encode() + "8000;Kraków\r\n".encode("cp1250"))
    result = run_check(path, None, options(tmp_path))
    assert any("mieszane kodowanie" in w and "wiersz 8002" in w for w in result.warnings)


def test_text_cut_in_xlsx_gives_a_warning(make_csv, tmp_path: Path) -> None:
    rows = [["Opis"], ["a" * 40_000]]
    result = run_check(make_csv(rows), None, options(tmp_path, output_format="xlsx"))
    assert len(read_sheet(result.outputs.clean)[1][0]) == 32_767
    assert any("32 767" in warning for warning in result.warnings)


def test_workbook_with_more_sheets_gives_a_warning(tmp_path: Path) -> None:
    path = tmp_path / "arkusze.xlsx"
    book = xlsxwriter.Workbook(str(path))
    for name in ("Klienci", "Archiwum", "Notatki"):
        book.add_worksheet(name).write_column(0, 0, ["Nazwa", "x"])
    book.close()
    warnings = analyze(path).warnings
    assert any("3 arkusze" in w and "„Klienci”" in w and "--arkusz" in w for w in warnings)
    assert analyze(path, sheet="Archiwum").warnings == []


def test_rows_with_wrong_number_of_fields(make_csv, tmp_path: Path) -> None:
    rows = [["A", "B"], ["1", "2", "3"], ["4"], ["5", "6"], ["7"]]
    result = run_check(make_csv(rows), None, options(tmp_path))
    assert [problem.reason for problem in result.problems] == ["Wiersz ma 3 pola zamiast 2"]
    assert any("2 wiersze mają mniej pól" in w and "wiersz 3" in w for w in result.warnings)
    assert result.accepted == 3


def test_structure_error_uses_polish_plural(make_csv, tmp_path: Path) -> None:
    rows = [["A", "B", "C", "D"], ["1", "2", "3", "4", "5"]]
    result = run_check(make_csv(rows), None, options(tmp_path))
    assert result.problems[0].reason == "Wiersz ma 5 pól zamiast 4"


def test_near_duplicate_limit_is_shared_with_the_report(make_csv, tmp_path: Path) -> None:
    groups = MAX_NEAR_DUPLICATE_GROUPS + 20
    rows = [["Firma"]] + [[f"{name} {i}"] for i in range(groups) for name in ("Firma", "FIRMA")]
    result = run_check(make_csv(rows), None, options(tmp_path))
    assert len(result.near_duplicates) == MAX_NEAR_DUPLICATE_GROUPS
    assert result.near_duplicate_groups == groups
    assert f"Pokazano {MAX_NEAR_DUPLICATE_GROUPS} z {groups} grup" in render_report(result)


# --- output files ----------------------------------------------------------------------------


def test_xlsx_row_limit_stops_with_a_clear_error(
    make_csv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("walidator.writers.XLSX_MAX_ROWS", 3)
    rows = [["Nazwa"]] + [[f"wiersz {i}"] for i in range(5)]
    with pytest.raises(OutputError, match="CSV"):
        run_check(make_csv(rows), None, options(tmp_path, output_format="xlsx"))
    assert not list((tmp_path / "wynik").glob("dane_*"))


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Opens a file without sharing, like Excel does with an open workbook."""
    import _winapi

    generic_read, no_sharing, open_existing = 0x80000000, 0, 3
    handle = _winapi.CreateFile(str(path), generic_read, no_sharing, 0, open_existing, 0, 0)
    try:
        yield
    finally:
        _winapi.CloseHandle(handle)


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows file locks")


@windows_only
@pytest.mark.parametrize("output_format", ["csv", "xlsx"])
def test_locked_rejected_file_keeps_previous_results(
    make_csv, tmp_path: Path, output_format: str
) -> None:
    first = run_check(make_csv(ROWS), None, options(tmp_path, output_format=output_format))
    before = first.outputs.clean.read_bytes()
    with locked(first.outputs.rejected), pytest.raises(OutputError) as error:
        run_check(make_csv(ROWS[:3]), None, options(tmp_path, output_format=output_format))
    assert first.outputs.rejected.name in str(error.value)
    assert "otwarty" in str(error.value)
    assert first.outputs.clean.read_bytes() == before
    names = {path.name for path in (tmp_path / "wynik").iterdir()}
    assert names == {first.outputs.clean.name, first.outputs.rejected.name, "dane_raport.html"}


@windows_only
def test_locked_report_is_detected_before_writing(make_csv, tmp_path: Path) -> None:
    first = run_check(make_csv(ROWS), None, options(tmp_path))
    assert first.outputs.report is not None
    with locked(first.outputs.report), pytest.raises(OutputError, match=r"dane_raport\.html"):
        run_check(make_csv(ROWS), None, options(tmp_path))


def test_folder_without_write_access_is_not_called_a_locked_file(
    make_csv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_args: object) -> None:
        raise PermissionError(13, "Odmowa dostępu")

    monkeypatch.setattr("walidator.engine.open_writers", denied)
    with pytest.raises(OutputError, match="Brak uprawnień do zapisu w folderze") as error:
        run_check(make_csv(ROWS), None, options(tmp_path))
    assert "otwarty" not in str(error.value)


def test_report_write_errors_are_polish(make_csv, tmp_path: Path) -> None:
    result = run_check(make_csv(ROWS), None, RunOptions(tmp_path / "wynik", write_report=False))
    with pytest.raises(OutputError, match="Nie można zapisać raportu"):
        write_report(result, tmp_path / "brak" / "raport.html")


def test_huge_amount_in_a_detected_amount_column_is_rejected(make_csv, tmp_path: Path) -> None:
    rows = [["Kwota", "Klient"], ["1" * 28, "Alfa"], ["5", "Beta"]]
    result = run_check(make_csv(rows), None, options(tmp_path))
    assert result.columns[0].rule.type is ColumnType.DECIMAL
    assert (result.rejected, result.accepted) == (1, 1)
