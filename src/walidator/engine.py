"""The check itself: analyse a file, then validate, clean and write every row in one pass."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, NamedTuple

from xlsxwriter.exceptions import FileCreateError

from walidator.cleaners import as_text, plural
from walidator.detection import guess_column, suggest_similarity_key
from walidator.errors import CancelledError, OutputError, RulesError
from walidator.model import ColumnRule, ColumnType, RuleSet
from walidator.processing import (
    BAD_STRUCTURE,
    DUPLICATE_ROW,
    NOT_UNIQUE,
    Cell,
    ColumnProcessor,
    similarity_key,
)
from walidator.readers import ENCODING_NAMES, SourceInfo, TableSource, open_table
from walidator.report import num, write_report
from walidator.results import (
    MAX_NEAR_DUPLICATE_GROUPS,
    ColumnStats,
    NearDuplicateGroup,
    OutputPaths,
    Problem,
    RunResult,
)
from walidator.writers import EXCEL_TEXT_LIMIT, CleanWriter, RejectedWriter, open_writers

log = logging.getLogger(__name__)

OutputFormat = Literal["jak_wejscie", "xlsx", "csv"]
ProgressCallback = Callable[[float | None, int], None]

SAMPLE_ROWS = 500
PROGRESS_EVERY = 2_000


@dataclass(slots=True)
class Analysis:
    """What the program detected in a file, ready to be shown and adjusted by the user."""

    info: SourceInfo
    rules: RuleSet
    detected_by: dict[str, str] = field(default_factory=dict)
    examples: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunOptions:
    output_dir: Path
    output_format: OutputFormat = "jak_wejscie"
    sheet: str | None = None
    write_report: bool = True
    rules_source: str | None = None


def analyze(path: str | Path, sheet: str | None = None, rules: RuleSet | None = None) -> Analysis:
    with open_table(path, sheet) as source:
        return _analyze_source(source, rules)


def _analyze_source(source: TableSource, loaded: RuleSet | None) -> Analysis:
    info = source.info
    sample = source.sample(SAMPLE_ROWS)
    analysis = Analysis(info=info, rules=RuleSet(), warnings=list(info.warnings))
    for index, header in enumerate(info.headers):
        guess = guess_column(header, [row[index] if index < len(row) else None for row in sample])
        analysis.examples[header] = guess.example
        from_file = loaded.find(header) if loaded else None
        if from_file:
            rule = _copy_rule(from_file, header)
            analysis.detected_by[header] = "plik reguł"
        else:
            rule = guess.rule
            analysis.detected_by[header] = guess.source
        analysis.rules.columns[header] = rule

    if loaded:
        _check_rules_against_headers(loaded, info.headers, analysis.warnings)
        analysis.rules.remove_duplicates = loaded.remove_duplicates
        analysis.rules.description = loaded.description
        analysis.rules.similarity_key = _matching_header(loaded.similarity_key, info.headers)
        if loaded.similarity_key and not analysis.rules.similarity_key:
            analysis.warnings.append(
                f"Kolumna podobieństwa „{loaded.similarity_key}” nie istnieje w pliku – pominięto."
            )
    else:
        rules = list(analysis.rules.columns.values())
        analysis.rules.similarity_key = suggest_similarity_key(info.headers, rules)
    return analysis


def _copy_rule(rule: ColumnRule, header: str) -> ColumnRule:
    return ColumnRule(
        name=header,
        type=rule.type,
        required=rule.required,
        unique=rule.unique,
        minimum=rule.minimum,
        maximum=rule.maximum,
        allowed=rule.allowed,
        case=rule.case,
        decimals=rule.decimals,
    )


def _check_rules_against_headers(rules: RuleSet, headers: list[str], warnings: list[str]) -> None:
    present = RuleSet(columns={header: ColumnRule(header) for header in headers})
    missing = [rule for name, rule in rules.columns.items() if present.find(name) is None]
    required = [rule.name for rule in missing if rule.required]
    if required:
        raise RulesError(
            "W pliku brakuje kolumn wymaganych przez reguły: "
            + ", ".join(f"„{n}”" for n in required)
        )
    warnings.extend(
        f"Kolumna „{rule.name}” z pliku reguł nie występuje w arkuszu." for rule in missing
    )


def _matching_header(name: str | None, headers: list[str]) -> str | None:
    if not name:
        return None
    wanted = RuleSet(columns={name: ColumnRule(name)})
    return next((header for header in headers if wanted.find(header)), None)


# --- running a check -------------------------------------------------------------------------


def run_check(
    path: str | Path,
    rules: RuleSet | None,
    options: RunOptions,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    *,
    on_analysis: Callable[[Analysis], None] | None = None,
) -> RunResult:
    """Checks the whole file and writes the cleaned file, rejected rows and the HTML report.

    ``rules`` may be partial (e.g. loaded from JSON); columns it does not mention are detected.
    ``on_analysis`` sees the detected columns before the check starts (the file is read once).
    """
    started = time.perf_counter()
    with open_table(path, options.sheet) as source:
        analysis = _analyze_source(source, rules)
        if on_analysis:
            on_analysis(analysis)
        result = _run(source, analysis, options, progress, cancel)
    result.elapsed = time.perf_counter() - started
    if options.write_report and result.outputs.report:
        write_report(result, result.outputs.report)
        result.elapsed = time.perf_counter() - started
    log.info("Sprawdzono %s: %d wierszy w %.2f s", source.path.name, result.total, result.elapsed)
    return result


def output_paths(info: SourceInfo, options: RunOptions) -> tuple[OutputPaths, str]:
    kind = options.output_format if options.output_format != "jak_wejscie" else info.kind
    suffix = ".xlsx" if kind == "xlsx" else ".csv"
    folder, stem = options.output_dir, info.path.stem
    report = folder / f"{stem}_raport.html" if options.write_report else None
    paths = OutputPaths(
        folder / f"{stem}_czyste{suffix}", folder / f"{stem}_odrzucone{suffix}", report
    )
    return paths, kind


def _run(
    source: TableSource,
    analysis: Analysis,
    options: RunOptions,
    progress: ProgressCallback | None,
    cancel: threading.Event | None,
) -> RunResult:
    info = source.info
    rules = [analysis.rules.columns[header] for header in info.headers]
    delimiter = info.delimiter if info.kind == "csv" and info.delimiter else ";"
    paths, kind = output_paths(info, options)
    result = RunResult(
        source=info,
        columns=[ColumnStats(rule) for rule in rules],
        outputs=paths,
        started_at=datetime.now(),
        rules_source=options.rules_source,
        similarity_key=analysis.rules.similarity_key,
        warnings=analysis.warnings,
    )
    checker = RowChecker(rules, analysis.rules, decimal_separator="." if delimiter == "," else ",")
    _check_replaceable(paths)
    # Results go to temporary files first, so an error never leaves old results half-written.
    temp = OutputPaths(_temp_path(paths.clean), _temp_path(paths.rejected), None)
    clean, rejected = _open_outputs(kind, temp, rules, delimiter)
    try:
        for number, raw in source.rows():
            checker.check(number, raw, result, clean, rejected)
            if result.total % PROGRESS_EVERY == 0:
                if cancel is not None and cancel.is_set():
                    raise CancelledError
                if progress:
                    progress(_fraction(result.total, info.estimated_rows), result.total)
    except BaseException:
        _close_quietly(clean, rejected)
        _remove(temp.clean, temp.rejected)
        raise
    try:
        _close_outputs(clean, rejected, temp)
        _check_replaceable(paths)
        for done, final in ((temp.clean, paths.clean), (temp.rejected, paths.rejected)):
            _replace(done, final)
    except BaseException:
        _remove(temp.clean, temp.rejected)
        raise
    checker.finish(result)
    _add_output_warnings(result, source, clean, rejected)
    if progress:
        progress(1.0, result.total)
    return result


def _fraction(done: int, estimated: int | None) -> float | None:
    return min(done / estimated, 0.99) if estimated else None


def _add_output_warnings(
    result: RunResult, source: TableSource, clean: CleanWriter, rejected: RejectedWriter
) -> None:
    if source.unreadable_chars:
        encoding = ENCODING_NAMES.get(source.info.encoding or "", source.info.encoding)
        count = source.unreadable_chars
        chars = plural(count, "znak nie pasuje", "znaki nie pasują", "znaków nie pasuje")
        result.warnings.append(
            f"{num(count)} {chars} do kodowania {encoding} i zastąpiono je znakiem „�” "
            f"(pierwszy raz: wiersz {source.first_unreadable_row}). Plik ma prawdopodobnie "
            "mieszane kodowanie – zapisz go ponownie w UTF-8 i sprawdź jeszcze raz."
        )
    truncated = clean.truncated_cells + rejected.truncated_cells
    if truncated:
        cells = plural(truncated, "komórka miała", "komórki miały", "komórek miało")
        result.warnings.append(
            f"{num(truncated)} {cells} ponad {num(EXCEL_TEXT_LIMIT)} znaków – w pliku XLSX tekst "
            "skrócono do tej długości (Excel nie mieści więcej). Pełny tekst zachowuje wynik w CSV."
        )


class Issue(NamedTuple):
    index: int | None  # column index, None for problems with the whole row
    category: str
    reason: str


class RowChecker:
    """Applies column rules, unique checks, duplicate removal and the near-duplicate search."""

    def __init__(
        self, rules: Sequence[ColumnRule], rule_set: RuleSet, decimal_separator: str
    ) -> None:
        self.rules = rules
        self.width = len(rules)
        self.processors = [ColumnProcessor(rule, decimal_separator) for rule in rules]
        self.remove_duplicates = rule_set.remove_duplicates
        self.unique_seen = {
            index: dict[str, int]() for index, rule in enumerate(rules) if rule.unique
        }
        self.row_hashes: dict[bytes, int] = {}
        names = [rule.name for rule in rules]
        key = rule_set.similarity_key
        self.similarity_index = names.index(key) if key in names else None
        self.similar: dict[str, list[tuple[int, str]]] = {}
        self.short_rows = 0
        self.first_short_row: int | None = None
        self.dropped_times = dict.fromkeys(
            (index for index, rule in enumerate(rules) if rule.type is ColumnType.DATE), 0
        )

    def check(
        self,
        number: int,
        raw: list[object],
        result: RunResult,
        clean: CleanWriter,
        rejected: RejectedWriter,
    ) -> None:
        result.total += 1
        extra = [value for value in raw[self.width :] if value not in (None, "")]
        if len(raw) < self.width:  # missing trailing fields are read as empty cells
            self.short_rows += 1
            self.first_short_row = self.first_short_row or number
        raw = raw[: self.width] + [None] * (self.width - len(raw))
        cells = [
            processor.process(value) for processor, value in zip(self.processors, raw, strict=True)
        ]

        first = self._duplicate_of(number, cells) if self.remove_duplicates else None
        if first is not None:
            result.duplicates += 1
            issue = Issue(None, DUPLICATE_ROW, f"Duplikat wiersza {first}")
            self._reject(number, raw, [issue], result, rejected)
            return

        issues = self._find_issues(cells, len(raw) + len(extra) if extra else 0)
        self._update_stats(result, cells, raw)
        if issues:
            self._reject(number, raw, issues, result, rejected)
            return
        self._accept(number, cells, result)
        clean.write(cells)

    def _duplicate_of(self, number: int, cells: list[Cell]) -> int | None:
        # A 16-byte digest instead of the row itself keeps memory low for large files.
        digest = hashlib.blake2b(
            "\x1f".join(c.text for c in cells).encode(), digest_size=16
        ).digest()
        first = self.row_hashes.setdefault(digest, number)
        return first if first != number else None

    def _find_issues(self, cells: list[Cell], field_count: int) -> list[Issue]:
        issues = [
            Issue(index, cell.error.category, cell.error.reason)
            for index, cell in enumerate(cells)
            if cell.error is not None
        ]
        for index, seen in self.unique_seen.items():
            cell = cells[index]
            if cell.error is None and cell.text in seen:
                reason = f"Wartość już wystąpiła w wierszu {seen[cell.text]}"
                issues.append(Issue(index, NOT_UNIQUE, reason))
        if field_count:
            fields = plural(field_count, "pole", "pola", "pól")
            reason = f"Wiersz ma {field_count} {fields} zamiast {self.width}"
            issues.append(Issue(None, BAD_STRUCTURE, reason))
        return issues

    def _accept(self, number: int, cells: list[Cell], result: RunResult) -> None:
        if any(cell.changed for cell in cells):
            result.fixed += 1
        for index in self.dropped_times:
            if cells[index].time_dropped:
                self.dropped_times[index] += 1
        for index, seen in self.unique_seen.items():
            if text := cells[index].text:
                seen.setdefault(text, number)
        if self.similarity_index is not None and (text := cells[self.similarity_index].text):
            self.similar.setdefault(similarity_key(text), []).append((number, text))

    def _reject(
        self,
        number: int,
        raw: list[object],
        issues: list[Issue],
        result: RunResult,
        rejected: RejectedWriter,
    ) -> None:
        result.rejected += 1
        cell_reasons: dict[int, str] = {}
        row_reasons: list[str] = []
        for issue in issues:
            result.categories[issue.category] += 1
            column = self.rules[issue.index].name if issue.index is not None else None
            value = raw[issue.index] if issue.index is not None else ""
            result.add_problem(
                Problem(number, column or "—", as_text(value), issue.reason, issue.category)
            )
            if column is None:
                row_reasons.append(issue.reason)
            else:
                cell_reasons[issue.index] = f"{column}: {issue.reason}"  # type: ignore[index]
        rejected.write(number, raw, cell_reasons, row_reasons)

    def _update_stats(self, result: RunResult, cells: list[Cell], raw: list[object]) -> None:
        for stats, cell, original in zip(result.columns, cells, raw, strict=True):
            if cell.error is not None:
                stats.filled += 1
                stats.invalid += 1
                continue
            if cell.value is None:
                stats.empty += 1
            else:
                stats.filled += 1
                stats.record_value(cell.text, cell.value)
            if cell.changed:
                stats.record_fix(as_text(original), cell.text)

    def finish(self, result: RunResult) -> None:
        self._add_warnings(result)
        groups = [rows for rows in self.similar.values() if len(rows) > 1]
        result.near_duplicate_rows = sum(len(rows) for rows in groups)
        result.near_duplicate_groups = len(groups)
        if self.similarity_index is None:
            return
        column = self.rules[self.similarity_index].name
        result.near_duplicates = [
            NearDuplicateGroup(column, rows) for rows in groups[:MAX_NEAR_DUPLICATE_GROUPS]
        ]

    def _add_warnings(self, result: RunResult) -> None:
        if self.short_rows:
            rows = plural(self.short_rows, "wiersz ma", "wiersze mają", "wierszy ma")
            result.warnings.append(
                f"{num(self.short_rows)} {rows} mniej pól niż nagłówek (pierwszy: wiersz "
                f"{self.first_short_row}) – brakujące pola potraktowano jako puste."
            )
        for index, count in self.dropped_times.items():
            if count:
                rule = self.rules[index]
                cells = plural(count, "komórce", "komórkach", "komórkach")
                result.warnings.append(
                    f"Kolumna „{rule.name}”: w {num(count)} {cells} była też godzina – "
                    "w czystym pliku zapisano samą datę."
                )


# --- output files ----------------------------------------------------------------------------


def _open_outputs(
    kind: str, paths: OutputPaths, rules: Sequence[ColumnRule], delimiter: str
) -> tuple[CleanWriter, RejectedWriter]:
    """Opens the writers on new (temporary) files, so an error here concerns the folder."""
    folder = paths.clean.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return open_writers(kind, paths.clean, paths.rejected, rules, delimiter)
    except PermissionError as error:
        raise OutputError(
            f"Brak uprawnień do zapisu w folderze {folder}. Wybierz inny folder na wyniki."
        ) from error
    except OSError as error:
        raise OutputError(
            f"Nie można utworzyć plików wyniku w folderze {folder}: {error.strerror or error}"
        ) from error


def _close_outputs(clean: CleanWriter, rejected: RejectedWriter, paths: OutputPaths) -> None:
    for writer, path in ((clean, paths.clean), (rejected, paths.rejected)):
        try:
            writer.close()
        except (OSError, FileCreateError) as error:
            raise OutputError(f"Nie można zapisać pliku {path.name}: {error}") from error


def _temp_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.tmp{path.suffix}")


def _locked_message(path: Path) -> str:
    return (
        f"Plik {path.name} jest otwarty w innym programie (np. w Excelu) albo zablokowany. "
        "Zamknij go i spróbuj ponownie – poprzednie wyniki nie zostały zmienione."
    )


def _check_replaceable(paths: OutputPaths) -> None:
    """Fails early when an existing result file is open in another program."""
    for path in (paths.clean, paths.rejected, paths.report):
        if path is None or not path.is_file():
            continue
        try:
            with path.open("r+b"):
                pass
        except PermissionError as error:
            raise OutputError(_locked_message(path)) from error


def _replace(done: Path, final: Path) -> None:
    try:
        done.replace(final)
    except PermissionError as error:
        raise OutputError(_locked_message(final)) from error


def _close_quietly(*writers: CleanWriter | RejectedWriter) -> None:
    for writer in writers:
        try:
            writer.close()
        except Exception:
            log.debug("Nie udało się zamknąć pliku wyniku", exc_info=True)


def _remove(*paths: Path) -> None:
    """Deletes temporary files; a failure here must not hide the error being reported."""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("Nie udało się usunąć pliku tymczasowego %s", path, exc_info=True)
