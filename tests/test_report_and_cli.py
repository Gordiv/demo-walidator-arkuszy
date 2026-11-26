import json
import re
from pathlib import Path

import pytest

from walidator import __version__
from walidator.cli import EXIT_ERROR, EXIT_OK, EXIT_REJECTED, main
from walidator.engine import RunOptions, run_check
from walidator.model import ColumnRule, ColumnType, RuleSet
from walidator.report import num, pct, render_report, seconds

GOOD = [["Nazwa", "E-mail"], ["Alfa", "alfa@example.com"], ["Beta", "beta@example.com"]]
BAD = [["Nazwa", "E-mail"], ["Alfa", "<script>alert(1)</script>"], ["Beta", "b@example.com"]]
EMAIL_RULES = RuleSet(columns={"E-mail": ColumnRule("E-mail", ColumnType.EMAIL)})


# --- report ----------------------------------------------------------------------------------


def test_report_is_self_contained_and_escapes_data(make_csv, tmp_path: Path) -> None:
    result = run_check(make_csv(BAD), EMAIL_RULES, RunOptions(tmp_path / "wynik"))
    html = render_report(result)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert not re.search(r"<(link|script|img)\b|src=|@import|url\(", html)
    for section in ("Struktura wierszy", "Rodzaje błędów", "Statystyki kolumn", "Problemy"):
        assert section in html
    assert "Brak znaku @" in html
    assert "<svg" in html
    assert "@media print" in html


def test_report_for_clean_data_has_no_problem_table(make_csv, tmp_path: Path) -> None:
    html = render_report(run_check(make_csv(GOOD), None, RunOptions(tmp_path / "wynik")))
    assert "Brak błędów" in html
    assert "<h2>Problemy" not in html


def test_report_limits_problem_list(make_csv, tmp_path: Path) -> None:
    rows = [["E-mail"]] + [[f"zly{i}"] for i in range(600)]
    result = run_check(make_csv(rows), EMAIL_RULES, RunOptions(tmp_path / "wynik"))
    html = render_report(result)
    assert "Pokazano 500 z 600 problemów" in html


def test_polish_number_formatting() -> None:
    assert num(1234567) == "1\u00a0234\u00a0567"
    assert pct(1, 3) == "33,3\u00a0%"
    assert pct(1, 0) == "0,0\u00a0%"
    assert seconds(1.5) == "1,50\u00a0s"


# --- command line ----------------------------------------------------------------------------


def test_cli_exit_code_ok(make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(make_csv(GOOD)), "--wyjscie", str(tmp_path / "w")])
    assert code == EXIT_OK
    output = capsys.readouterr().out
    assert "Poprawne:" in output
    assert "dane_czyste.csv" in output


def test_cli_exit_code_when_rows_are_rejected(make_csv, tmp_path: Path) -> None:
    assert main([str(make_csv(BAD)), "-o", str(tmp_path / "w"), "-q"]) == EXIT_REJECTED


def test_cli_quiet_prints_nothing(
    make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([str(make_csv(BAD)), "-o", str(tmp_path / "w"), "--cicho"])
    assert capsys.readouterr().out == ""


def test_cli_verbose_shows_columns_and_problems(
    make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([str(make_csv(BAD)), "-o", str(tmp_path / "w"), "-v", "--format", "xlsx"])
    output = capsys.readouterr().out
    assert "Wykryto na podstawie" in output
    assert "Najczęstsze błędy" in output
    assert "dane_czyste.xlsx" in output


def test_cli_missing_file_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "brak.xlsx")]) == EXIT_ERROR
    assert "Nie znaleziono pliku" in capsys.readouterr().err


def test_cli_bad_rules_file(make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rules = tmp_path / "r.json"
    rules.write_text('{"kolumny": {"E-mail": {"typ": "mail"}}}', encoding="utf-8")
    assert main([str(make_csv(GOOD)), "--reguly", str(rules)]) == EXIT_ERROR
    assert "Nieznany typ „mail”" in capsys.readouterr().err


def test_cli_analysis_only_and_save_rules(
    make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rules = tmp_path / "zapisane.json"
    code = main([str(make_csv(GOOD)), "--tylko-analiza", "--zapisz-reguly", str(rules)])
    assert code == EXIT_OK
    assert json.loads(rules.read_text(encoding="utf-8"))["kolumny"]["E-mail"]["typ"] == "email"
    assert not (tmp_path / "wynik").exists()
    assert "Zapisano reguły" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["a.csv", "--nieznana"], "nieznane argumenty: --nieznana"),
        (["a.csv", "--format", "pdf"], "niedozwolona wartość"),
        (["a.csv", "--reguly"], "wymaga wartości"),
        ([], "brak wymaganego argumentu: plik"),
    ],
)
def test_cli_usage_errors_are_polish(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == EXIT_ERROR
    assert message in capsys.readouterr().err


def test_cli_help_is_polish(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    text = capsys.readouterr().out
    assert "Użycie:" in text
    assert "kody wyjścia" in text
    assert "usage" not in text


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--wersja"])
    assert __version__ in capsys.readouterr().out


def test_cli_unexpected_error_points_to_log(
    monkeypatch: pytest.MonkeyPatch, make_csv, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("awaria")

    monkeypatch.setattr("walidator.cli.run_check", broken)
    assert main([str(make_csv(GOOD))]) == EXIT_ERROR
    error = capsys.readouterr().err
    assert "Nieoczekiwany błąd" in error
    assert "awaria" not in error


# --- regressions -----------------------------------------------------------------------------


def test_cli_save_rules_to_a_folder_is_a_polish_error(
    make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([str(make_csv(GOOD)), "--tylko-analiza", "--zapisz-reguly", str(tmp_path)])
    assert code == EXIT_ERROR
    error = capsys.readouterr().err
    assert "to folder" in error
    assert "Nieoczekiwany" not in error


def test_cli_save_rules_to_a_missing_folder_is_a_polish_error(
    make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "brak" / "reguly.json"
    assert main([str(make_csv(GOOD)), "--zapisz-reguly", str(target)]) == EXIT_ERROR
    assert "nie istnieje" in capsys.readouterr().err


def test_cli_quiet_and_verbose_conflict_is_polish(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["a.csv", "-q", "-v"])
    error = capsys.readouterr().err
    assert "nie można łączyć" in error
    assert "not allowed" not in error


def test_cli_verbose_reads_the_file_once(
    make_csv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from walidator import engine

    opened: list[object] = []
    original = engine.open_table

    def counting(*args: object) -> object:
        opened.append(args)
        return original(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(engine, "open_table", counting)
    rules = tmp_path / "r.json"
    main([str(make_csv(BAD)), "-o", str(tmp_path / "w"), "-v", "--zapisz-reguly", str(rules)])
    assert len(opened) == 1
    assert rules.is_file()


def test_cli_summary_shows_warnings(
    make_csv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [["A", "B"], ["1"]]
    main([str(make_csv(rows)), "-o", str(tmp_path / "w")])
    assert "Uwaga: 1 wiersz ma mniej pól" in capsys.readouterr().out


def test_report_shows_near_duplicate_groups_without_note_when_all_fit(
    make_csv, tmp_path: Path
) -> None:
    rows = [["Firma"], ["Alfa Sp. z o.o."], ["ALFA SP Z OO"]]
    html = render_report(run_check(make_csv(rows), None, RunOptions(tmp_path / "wynik")))
    assert "ALFA SP Z OO" in html
    assert "Pokazano" not in html
