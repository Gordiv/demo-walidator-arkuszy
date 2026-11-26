"""Command line interface: ``walidator dane.xlsx --reguly reguly.json --wyjscie wynik``."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from walidator import APP_NAME, __version__
from walidator.engine import Analysis, RunOptions, analyze, run_check
from walidator.errors import CancelledError, WalidatorError
from walidator.logs import LOG_FILE, setup_logging
from walidator.report import num, pct, seconds
from walidator.results import RunResult
from walidator.rules import load_rules, save_rules

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_ERROR = 2

log = logging.getLogger(__name__)

_ARGPARSE_MESSAGES = (
    (r"unrecognized arguments: (.*)", r"nieznane argumenty: \1"),
    (r"the following arguments are required: (.*)", r"brak wymaganego argumentu: \1"),
    (r"argument (\S+): expected one argument", r"opcja \1 wymaga wartości"),
    (
        r"argument (\S+): invalid choice: (.*?) \(choose from (.*)\)",
        r"opcja \1: niedozwolona wartość \2 (dozwolone: \3)",
    ),
    (r"argument (\S+): ignored explicit argument (.*)", r"opcja \1 nie przyjmuje wartości \2"),
    (r"argument (\S+): not allowed with argument (\S+)", r"opcji \1 nie można łączyć z \2"),
)

DESCRIPTION = f"""\
{APP_NAME} – sprawdza i czyści dane z plików XLSX i CSV.
Tworzy plik z poprawnymi danymi, plik z odrzuconymi wierszami (z powodami)
i raport HTML."""

EPILOG = """\
kody wyjścia:
  0  wszystkie wiersze są poprawne (po ewentualnych poprawkach)
  1  część wierszy odrzucono – zobacz plik *_odrzucone i raport
  2  błąd użycia, pliku wejściowego lub pliku reguł

przykłady:
  walidator klienci.xlsx
  walidator zamowienia.csv --reguly reguly.json --wyjscie wynik --format xlsx
  walidator klienci.xlsx --zapisz-reguly moje_reguly.json --tylko-analiza
"""


class PolishArgumentParser(argparse.ArgumentParser):
    """argparse with Polish help headings and error messages."""

    def format_help(self) -> str:
        text = super().format_help()
        for english, polish in (
            ("usage:", "Użycie:"),
            ("positional arguments:", "Argumenty:"),
            ("options:", "Opcje:"),
        ):
            text = text.replace(english, polish)
        return text

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "Użycie:")

    def error(self, message: str) -> NoReturn:
        for pattern, replacement in _ARGPARSE_MESSAGES:
            message = re.sub(pattern, replacement, message)
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, f"Błąd: {message}\nPomoc: walidator --help\n")


def build_parser() -> PolishArgumentParser:
    parser = PolishArgumentParser(
        prog="walidator",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("plik", type=Path, help="plik do sprawdzenia (.xlsx albo .csv)")
    parser.add_argument(
        "-r",
        "--reguly",
        type=Path,
        metavar="PLIK.json",
        help="plik reguł JSON; kolumny, których nie opisuje, są wykrywane same",
    )
    parser.add_argument(
        "-o",
        "--wyjscie",
        type=Path,
        metavar="FOLDER",
        help="folder na wyniki (domyślnie: „wynik” obok pliku wejściowego)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("jak-wejscie", "xlsx", "csv"),
        default="jak-wejscie",
        help="format plików wynikowych (domyślnie: jak wejście)",
    )
    parser.add_argument(
        "-a", "--arkusz", metavar="NAZWA", help="arkusz pliku XLSX (domyślnie: pierwszy)"
    )
    parser.add_argument(
        "--zapisz-reguly",
        type=Path,
        metavar="PLIK.json",
        help="zapisz użyte reguły do pliku JSON, aby powtórzyć sprawdzenie",
    )
    parser.add_argument(
        "--tylko-analiza",
        action="store_true",
        help="pokaż wykryte kolumny i typy bez sprawdzania całego pliku",
    )
    parser.add_argument("--bez-raportu", action="store_true", help="nie twórz raportu HTML")
    loudness = parser.add_mutually_exclusive_group()
    loudness.add_argument(
        "-q",
        "--cicho",
        action="store_true",
        help="nie wypisuj nic poza błędami (wynik tylko w kodzie wyjścia)",
    )
    loudness.add_argument(
        "-v",
        "--szczegolowo",
        action="store_true",
        help="pokaż wykryte kolumny, ostrzeżenia i pierwsze problemy",
    )
    parser.add_argument(
        "--wersja",
        action="version",
        version=f"{APP_NAME} {__version__}",
        help="pokaż wersję programu",
    )
    parser.add_argument("-h", "--help", action="help", help="pokaż tę pomoc")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _prepare_streams()
    args = build_parser().parse_args(argv)
    setup_logging(verbose=args.szczegolowo)
    out = _Printer(sys.stdout, quiet=args.cicho)
    try:
        return _run(args, out)
    except WalidatorError as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\nPrzerwano.", file=sys.stderr)
        return EXIT_ERROR
    except Exception:
        log.exception("Nieoczekiwany błąd")
        print(
            f"Nieoczekiwany błąd programu. Szczegóły zapisano w pliku: {LOG_FILE}", file=sys.stderr
        )
        return EXIT_ERROR


def _prepare_streams() -> None:
    """Uses UTF-8 when output is redirected to a file, so Polish letters are not lost."""
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        if stream.isatty():
            stream.reconfigure(errors="replace")
        else:
            stream.reconfigure(encoding="utf-8", errors="replace")


def _run(args: argparse.Namespace, out: _Printer) -> int:
    rules = load_rules(args.reguly) if args.reguly else None

    def show_analysis(analysis: Analysis) -> None:
        if not (args.tylko_analiza or args.zapisz_reguly or args.szczegolowo):
            return
        out.header(f"{APP_NAME} {__version__} – {args.plik.name} ({analysis.info.description})")
        if args.tylko_analiza or args.szczegolowo:
            _print_columns(analysis, out)
        if args.zapisz_reguly:
            save_rules(analysis.rules, args.zapisz_reguly)
            out.line(f"Zapisano reguły: {args.zapisz_reguly}")

    if args.tylko_analiza:
        analysis = analyze(args.plik, args.arkusz, rules)
        show_analysis(analysis)
        _print_warnings(analysis.warnings, out)
        return EXIT_OK

    options = RunOptions(
        output_dir=args.wyjscie or args.plik.resolve().parent / "wynik",
        output_format=args.format.replace("-", "_"),
        sheet=args.arkusz,
        write_report=not args.bez_raportu,
        rules_source=args.reguly.name if args.reguly else None,
    )
    progress = _ProgressBar(sys.stderr) if not args.cicho and sys.stderr.isatty() else None
    try:
        result = run_check(args.plik, rules, options, progress, on_analysis=show_analysis)
    except CancelledError:
        return EXIT_ERROR
    finally:
        if progress:
            progress.clear()
    _print_summary(result, out, verbose=args.szczegolowo)
    return EXIT_REJECTED if result.rejected else EXIT_OK


class _Printer:
    def __init__(self, stream: TextIO, quiet: bool) -> None:
        self.stream, self.quiet = stream, quiet

    def line(self, text: str = "") -> None:
        if not self.quiet:
            print(text, file=self.stream)

    def header(self, text: str) -> None:
        self.line(text)
        self.line("─" * min(len(text), 78))


class _ProgressBar:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    def __call__(self, fraction: float | None, rows: int) -> None:
        if fraction is None:
            text = f"  sprawdzono {num(rows)} wierszy…"
        else:
            filled = round(fraction * 30)
            text = f"  [{'█' * filled}{'░' * (30 - filled)}] {fraction:4.0%}  {num(rows)} wierszy"
        self.stream.write("\r" + text.ljust(70))
        self.stream.flush()

    def clear(self) -> None:
        self.stream.write("\r" + " " * 70 + "\r")
        self.stream.flush()


def _print_columns(analysis: Analysis, out: _Printer) -> None:
    out.line(f"{'Kolumna':<26} {'Typ':<18} {'Wymagane':<9} {'Unikalne':<9} Wykryto na podstawie")
    for name, rule in analysis.rules.columns.items():
        out.line(
            f"{name[:25]:<26} {rule.type.label:<18} {'tak' if rule.required else '–':<9} "
            f"{'tak' if rule.unique else '–':<9} {analysis.detected_by.get(name, '')}"
        )
    if analysis.rules.similarity_key:
        out.line(f"Klucz podobieństwa: {analysis.rules.similarity_key}")
    out.line()


def _print_warnings(warnings: list[str], out: _Printer) -> None:
    for warning in warnings:
        out.line(f"Uwaga: {warning}")


def _print_summary(result: RunResult, out: _Printer, verbose: bool) -> None:
    total = result.total
    out.header(f"Wynik sprawdzenia: {result.source.path.name}")
    out.line(f"  Wiersze:     {num(total):>9}")
    out.line(f"  Poprawne:    {num(result.unchanged):>9}  {pct(result.unchanged, total)}")
    out.line(f"  Poprawione:  {num(result.fixed):>9}  {pct(result.fixed, total)}")
    out.line(
        f"  Odrzucone:   {num(result.rejected):>9}  {pct(result.rejected, total)}"
        f"  (w tym duplikaty: {num(result.duplicates)})"
    )
    out.line(
        f"  Czas:        {seconds(result.elapsed):>9}  "
        f"({num(round(result.rows_per_second))} wierszy/s)"
    )
    if verbose and result.categories:
        out.line("\nNajczęstsze błędy:")
        for category, count in result.categories.most_common(8):
            out.line(f"  {num(count):>7}  {category}")
        out.line("\nPierwsze problemy:")
        for problem in result.problems[:10]:
            out.line(f"  wiersz {problem.row:>6}  {problem.column[:20]:<20}  {problem.reason}")
    if result.warnings:
        out.line()
        _print_warnings(result.warnings, out)
    out.line("\nPliki wynikowe:")
    for path in (result.outputs.clean, result.outputs.rejected, result.outputs.report):
        if path:
            out.line(f"  {path}")


if __name__ == "__main__":
    sys.exit(main())
