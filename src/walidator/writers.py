"""Streaming writers for the cleaned file and the file with rejected rows (CSV or XLSX)."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import IO, Protocol

import xlsxwriter

from walidator.cleaners import as_text
from walidator.model import ColumnRule, ColumnType
from walidator.processing import Cell

ROW_NUMBER_HEADER = "Nr wiersza"
REASONS_HEADER = "Powody odrzucenia"
EXCEL_TEXT_LIMIT = 32_767

_CLEAN_HEADER_COLOR = "#1F4E8C"
_REJECTED_HEADER_COLOR = "#9B2C2C"
_COLUMN_WIDTHS = {
    ColumnType.EMAIL: 32,
    ColumnType.URL: 34,
    ColumnType.PHONE: 17,
    ColumnType.NIP: 13,
    ColumnType.DATE: 12,
    ColumnType.POSTAL_CODE: 10,
    ColumnType.BOOLEAN: 9,
}
_WORKBOOK_OPTIONS = {
    "constant_memory": True,  # rows go straight to disk, memory stays flat for big files
    "strings_to_numbers": False,
    "strings_to_formulas": False,
    "strings_to_urls": False,
    "nan_inf_to_errors": True,
}


class CleanWriter(Protocol):
    def write(self, cells: Sequence[Cell]) -> None: ...
    def close(self) -> None: ...


class RejectedWriter(Protocol):
    def write(
        self,
        row_number: int,
        raw: Sequence[object],
        cell_reasons: dict[int, str],
        row_reasons: Sequence[str],
    ) -> None: ...
    def close(self) -> None: ...


def join_reasons(cell_reasons: dict[int, str], row_reasons: Sequence[str]) -> str:
    return "; ".join([*(cell_reasons[index] for index in sorted(cell_reasons)), *row_reasons])


# --- CSV -------------------------------------------------------------------------------------


class _CsvBase:
    def __init__(self, path: Path, headers: Sequence[str], delimiter: str) -> None:
        # UTF-8 with BOM, so Excel shows Polish letters correctly when the file is double-clicked
        self._handle: IO[str] = path.open("w", encoding="utf-8-sig", newline="")
        self._writer = csv.writer(self._handle, delimiter=delimiter)
        self._writer.writerow(headers)

    def close(self) -> None:
        self._handle.close()


class CsvCleanWriter(_CsvBase):
    def write(self, cells: Sequence[Cell]) -> None:
        self._writer.writerow([cell.text for cell in cells])


class CsvRejectedWriter(_CsvBase):
    def __init__(self, path: Path, headers: Sequence[str], delimiter: str) -> None:
        super().__init__(path, [ROW_NUMBER_HEADER, *headers, REASONS_HEADER], delimiter)

    def write(
        self,
        row_number: int,
        raw: Sequence[object],
        cell_reasons: dict[int, str],
        row_reasons: Sequence[str],
    ) -> None:
        reasons = join_reasons(cell_reasons, row_reasons)
        self._writer.writerow([row_number, *map(as_text, raw), reasons])


# --- XLSX ------------------------------------------------------------------------------------


class _XlsxBase:
    def __init__(
        self, path: Path, title: str, headers: Sequence[str], widths: Sequence[int], color: str
    ) -> None:
        self._book = xlsxwriter.Workbook(str(path), _WORKBOOK_OPTIONS)
        self._sheet = self._book.add_worksheet(title)
        header = self._book.add_format(
            {"bold": True, "font_color": "#FFFFFF", "bg_color": color, "valign": "vcenter"}
        )
        self._date = self._book.add_format({"num_format": "yyyy-mm-dd"})
        for index, (name, width) in enumerate(zip(headers, widths, strict=True)):
            self._sheet.set_column(index, index, width)
            self._sheet.write_string(0, index, name, header)
        self._sheet.set_row(0, 20)
        self._sheet.freeze_panes(1, 0)
        self._width = len(headers)
        self._row = 1

    def _put(self, column: int, value: object, style: object = None) -> None:
        """Writes one cell with its native Excel type; empty values leave the cell blank."""
        sheet, row = self._sheet, self._row
        if value is None or value == "":
            if style is not None:
                sheet.write_blank(row, column, None, style)
        elif isinstance(value, bool):
            sheet.write_string(row, column, "tak" if value else "nie", style)
        elif isinstance(value, int | float | Decimal):
            sheet.write_number(row, column, float(value), style)
        elif isinstance(value, date):
            sheet.write_datetime(row, column, value, style or self._date)
        else:
            sheet.write_string(row, column, str(value)[:EXCEL_TEXT_LIMIT], style)

    def close(self) -> None:
        if self._row > 1:
            self._sheet.autofilter(0, 0, self._row - 1, self._width - 1)
        self._book.close()


class XlsxCleanWriter(_XlsxBase):
    """Writes native numbers and dates, so the cleaned sheet can be filtered and summed."""

    def __init__(self, path: Path, rules: Sequence[ColumnRule]) -> None:
        names = [rule.name for rule in rules]
        widths = [_width(rule) for rule in rules]
        super().__init__(path, "Dane czyste", names, widths, _CLEAN_HEADER_COLOR)
        self._styles = [self._style_for(rule) for rule in rules]

    def _style_for(self, rule: ColumnRule) -> object:
        if rule.type is ColumnType.DECIMAL and rule.decimals:
            return self._book.add_format({"num_format": "#,##0." + "0" * rule.decimals})
        return None

    def write(self, cells: Sequence[Cell]) -> None:
        for column, (cell, style) in enumerate(zip(cells, self._styles, strict=True)):
            value = cell.value
            native = isinstance(value, int | Decimal | date) and not isinstance(value, bool)
            self._put(column, value if native else cell.text, style)
        self._row += 1


class XlsxRejectedWriter(_XlsxBase):
    """Keeps the original values; invalid cells are red and carry the reason as a note."""

    def __init__(self, path: Path, rules: Sequence[ColumnRule]) -> None:
        headers = [ROW_NUMBER_HEADER, *(rule.name for rule in rules), REASONS_HEADER]
        widths = [11, *(_width(rule) for rule in rules), 70]
        super().__init__(path, "Odrzucone", headers, widths, _REJECTED_HEADER_COLOR)
        invalid = {"bg_color": "#FDE2E1", "font_color": "#9B1C1C"}
        self._invalid = self._book.add_format(invalid)
        self._invalid_date = self._book.add_format({**invalid, "num_format": "yyyy-mm-dd"})
        self._reasons = self._book.add_format({"font_color": "#9B1C1C"})

    def write(
        self,
        row_number: int,
        raw: Sequence[object],
        cell_reasons: dict[int, str],
        row_reasons: Sequence[str],
    ) -> None:
        self._put(0, row_number)
        for index, value in enumerate(raw):
            reason = cell_reasons.get(index)
            if reason is None:
                self._put(index + 1, value)
                continue
            style = self._invalid_date if isinstance(value, date) else self._invalid
            self._put(index + 1, value, style)
            self._sheet.write_comment(self._row, index + 1, reason, {"author": "Walidator"})
        self._put(len(raw) + 1, join_reasons(cell_reasons, row_reasons), self._reasons)
        self._row += 1


def _width(rule: ColumnRule) -> int:
    return max(_COLUMN_WIDTHS.get(rule.type, 14), min(len(rule.name) + 4, 40))


def open_writers(
    kind: str, clean_path: Path, rejected_path: Path, rules: Sequence[ColumnRule], delimiter: str
) -> tuple[CleanWriter, RejectedWriter]:
    """Creates both writers; ``kind`` is "csv" or "xlsx"."""
    if kind == "xlsx":
        return XlsxCleanWriter(clean_path, rules), XlsxRejectedWriter(rejected_path, rules)
    headers = [rule.name for rule in rules]
    clean = CsvCleanWriter(clean_path, headers, delimiter)
    try:
        rejected = CsvRejectedWriter(rejected_path, headers, delimiter)
    except OSError:
        clean.close()
        raise
    return clean, rejected
