from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import xlsxwriter

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "przyklady"

CsvFactory = Callable[..., Path]


@pytest.fixture
def make_csv(tmp_path: Path) -> CsvFactory:
    """Writes rows to a CSV file with the given delimiter and encoding."""

    def factory(
        rows: Sequence[Sequence[object]],
        name: str = "dane.csv",
        delimiter: str = ";",
        encoding: str = "utf-8",
    ) -> Path:
        path = tmp_path / name
        text = "\r\n".join(delimiter.join(str(value) for value in row) for row in rows)
        path.write_bytes(text.encode(encoding))
        return path

    return factory


@pytest.fixture
def make_xlsx(tmp_path: Path) -> Callable[..., Path]:
    """Writes rows (native values allowed) to an XLSX file, starting at the given row."""

    def factory(
        rows: Sequence[Sequence[object]],
        name: str = "dane.xlsx",
        first_row: int = 0,
        sheet: str = "Arkusz1",
    ) -> Path:
        path = tmp_path / name
        book = xlsxwriter.Workbook(str(path), {"strings_to_numbers": False})
        worksheet = book.add_worksheet(sheet)
        date_format = book.add_format({"num_format": "dd.mm.yyyy"})
        for offset, row in enumerate(rows):
            for column, value in enumerate(row):
                if value is None:
                    continue
                if hasattr(value, "year"):
                    worksheet.write_datetime(first_row + offset, column, value, date_format)
                else:
                    worksheet.write(first_row + offset, column, value)
        book.close()
        return path

    return factory
