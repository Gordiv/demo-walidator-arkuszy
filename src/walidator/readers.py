"""Reading spreadsheets (XLSX, XLS, ODS) and CSV files row by row, with friendly Polish errors."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from python_calamine import CalamineError, CalamineSheet, CalamineWorkbook, PasswordError

from walidator.cleaners import as_text, clean_whitespace, plural
from walidator.detection import detect_delimiter, detect_encoding
from walidator.errors import FileReadError

SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm", ".xlsb", ".xls", ".ods")
TEXT_SUFFIXES = (".csv", ".txt", ".tsv")
SNIFF_BYTES = 64 * 1024
HEADER_SEARCH_ROWS = 20
_REPLACEMENT = "�"  # what errors="replace" puts in place of unreadable bytes

Row = list[object]

ENCODING_NAMES = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 z BOM",
    "cp1250": "Windows-1250",
    "iso-8859-2": "ISO-8859-2",
}
DELIMITER_NAMES = {";": "średnik", ",": "przecinek", "\t": "tabulator", "|": "kreska |"}


@dataclass(slots=True)
class SourceInfo:
    path: Path
    kind: Literal["csv", "xlsx"]  # "xlsx" stands for any spreadsheet format
    headers: list[str]
    header_row: int
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    sheets: list[str] = field(default_factory=list)
    estimated_rows: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        """Short description of the detected format, e.g. "CSV, Windows-1250, średnik"."""
        if self.kind == "xlsx":
            return f"{self.path.suffix.lstrip('.').upper()}, arkusz „{self.sheet}”"
        encoding = ENCODING_NAMES.get(self.encoding or "", self.encoding)
        return f"CSV, {encoding}, {DELIMITER_NAMES.get(self.delimiter or '', self.delimiter)}"


class TableSource:
    """An opened table. Use it as a context manager; rows can be iterated more than once."""

    def __init__(self, path: Path, sheet: str | None = None) -> None:
        self.path = path
        self._requested_sheet = sheet
        self._workbook: CalamineWorkbook | None = None
        self._sheets: dict[str, CalamineSheet] = {}
        self.info: SourceInfo
        # Characters of a CSV file that the detected encoding could not read (shown as "�")
        self.unreadable_chars = 0
        self.first_unreadable_row: int | None = None

    def __enter__(self) -> Self:
        if not self.path.is_file():
            raise FileReadError(f"Nie znaleziono pliku: {self.path}")
        suffix = self.path.suffix.lower()
        if suffix not in SPREADSHEET_SUFFIXES + TEXT_SUFFIXES:
            raise FileReadError(f"Nieobsługiwany typ pliku „{suffix}”. Wybierz plik XLSX albo CSV.")
        try:
            self.info = (
                self._open_spreadsheet() if suffix in SPREADSHEET_SUFFIXES else self._open_csv()
            )
        except PermissionError as error:
            raise FileReadError(
                f"Brak dostępu do pliku {self.path.name}. Jeśli jest otwarty w innym programie, "
                "zamknij go i spróbuj ponownie."
            ) from error
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._workbook is not None:
            self._sheets.clear()
            self._workbook.close()
            self._workbook = None

    # --- opening -------------------------------------------------------------------------

    def _open_csv(self) -> SourceInfo:
        with self.path.open("rb") as handle:
            head = handle.read(SNIFF_BYTES)
        if not head.strip():
            raise FileReadError(f"Plik {self.path.name} jest pusty.")
        encoding = detect_encoding(head)
        text = head.decode(encoding, errors="ignore")
        delimiter = "\t" if self.path.suffix.lower() == ".tsv" else detect_delimiter(text)
        info = SourceInfo(
            path=self.path,
            kind="csv",
            headers=[],
            header_row=0,
            encoding=encoding,
            delimiter=delimiter,
        )
        self._read_header(info, self._csv_rows(encoding, delimiter))
        info.estimated_rows = max(_count_lines(self.path) - info.header_row, 0)
        return info

    def _open_spreadsheet(self) -> SourceInfo:
        try:
            self._workbook = CalamineWorkbook.from_path(str(self.path))
        except PasswordError as error:
            raise FileReadError(f"Plik {self.path.name} jest zabezpieczony hasłem.") from error
        except CalamineError as error:
            raise FileReadError(
                f"Plik {self.path.name} nie jest poprawnym arkuszem (może jest uszkodzony)."
            ) from error
        sheets = list(self._workbook.sheet_names)
        sheet = self._requested_sheet or (sheets[0] if sheets else "")
        if sheet not in sheets:
            available = ", ".join(sheets) or "brak"
            raise FileReadError(f"W pliku nie ma arkusza „{sheet}”. Dostępne arkusze: {available}.")
        info = SourceInfo(
            path=self.path, kind="xlsx", headers=[], header_row=0, sheet=sheet, sheets=sheets
        )
        if len(sheets) > 1 and self._requested_sheet is None:
            count = plural(len(sheets), "arkusz", "arkusze", "arkuszy")
            info.warnings.append(
                f"Plik ma {len(sheets)} {count} – sprawdzono tylko pierwszy („{sheet}”). "
                "Inny arkusz można sprawdzić w wierszu poleceń opcją --arkusz NAZWA."
            )
        self._read_header(info, self._sheet_rows(sheet))
        height = self._sheet(sheet).total_height
        info.estimated_rows = max(height - info.header_row, 0)
        return info

    def _read_header(self, info: SourceInfo, raw_rows: Iterator[tuple[int, Row]]) -> None:
        for number, row in islice(raw_rows, HEADER_SEARCH_ROWS):
            if not _is_empty(row):
                info.header_row = number
                info.headers = _unique_headers(row, info.warnings)
                return
        raise FileReadError(f"Plik {self.path.name} nie zawiera nagłówka ani danych.")

    # --- rows ----------------------------------------------------------------------------

    def _csv_rows(self, encoding: str, delimiter: str) -> Iterator[tuple[int, Row]]:
        self.unreadable_chars, self.first_unreadable_row = 0, None
        with self.path.open(encoding=encoding, errors="replace", newline="") as handle:
            lines = self._count_unreadable(handle)
            for number, row in enumerate(csv.reader(lines, delimiter=delimiter), start=1):
                if self.unreadable_chars and self.first_unreadable_row is None:
                    self.first_unreadable_row = number
                yield number, row

    def _count_unreadable(self, lines: Iterable[str]) -> Iterator[str]:
        """Counts "�" put in place of bytes the encoding could not read (mixed encodings)."""
        for line in lines:
            if _REPLACEMENT in line:
                self.unreadable_chars += line.count(_REPLACEMENT)
            yield line

    def _sheet(self, name: str) -> CalamineSheet:
        """Parses a sheet once and keeps it, so the sample and the full pass share the work."""
        assert self._workbook is not None
        if name not in self._sheets:
            self._sheets[name] = self._workbook.get_sheet_by_name(name)
        return self._sheets[name]

    def _sheet_rows(self, sheet: str) -> Iterator[tuple[int, Row]]:
        yield from enumerate(self._sheet(sheet).iter_rows(), start=1)

    def rows(self) -> Iterator[tuple[int, Row]]:
        """Yields ``(row number in the file, cell values)`` for every data row after the header.

        Completely empty rows are skipped. Rows keep their real length, so rows with too many
        fields can be reported.
        """
        info = self.info
        raw = (
            self._sheet_rows(info.sheet or "")
            if info.kind == "xlsx"
            else self._csv_rows(info.encoding or "utf-8", info.delimiter or ";")
        )
        for number, row in raw:
            if number > info.header_row and not _is_empty(row):
                yield number, row

    def sample(self, size: int = 500) -> list[Row]:
        return [row for _, row in islice(self.rows(), size)]


def open_table(path: str | Path, sheet: str | None = None) -> TableSource:
    return TableSource(Path(path), sheet)


def _is_empty(row: Row) -> bool:
    return all(value is None or (isinstance(value, str) and not value.strip()) for value in row)


def _unique_headers(row: Row, warnings: list[str]) -> list[str]:
    while row and not as_text(row[-1]).strip():
        row = row[:-1]
    headers: list[str] = []
    for index, value in enumerate(row, start=1):
        name = clean_whitespace(as_text(value)) or f"Kolumna {index}"
        if name in headers:
            renamed = f"{name} ({headers.count(name) + 1})"
            warnings.append(f"Nagłówek „{name}” powtarza się – kolumna {index} to „{renamed}”.")
            name = renamed
        headers.append(name)
    return headers


def _count_lines(path: Path) -> int:
    """Counts line breaks quickly in binary mode (used only for the progress bar)."""
    count = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            count += chunk.count(b"\n")
    return count
