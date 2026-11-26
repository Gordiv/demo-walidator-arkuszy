from datetime import date, datetime
from decimal import Decimal

import pytest

from walidator.model import ColumnRule, ColumnType, TextCase
from walidator.processing import (
    MISSING,
    NOT_ALLOWED,
    OUT_OF_RANGE,
    ColumnProcessor,
    is_changed,
    similarity_key,
)


def process(rule: ColumnRule, raw: object, separator: str = ","):
    return ColumnProcessor(rule, separator).process(raw)


def test_valid_value_is_normalised_and_marked_as_changed() -> None:
    cell = process(ColumnRule("Tel", ColumnType.PHONE), " 600-123-456 ")
    assert (cell.value, cell.text, cell.changed, cell.error) == (
        "+48 600 123 456",
        "+48 600 123 456",
        True,
        None,
    )


def test_canonical_value_is_not_changed() -> None:
    assert not process(ColumnRule("Kod", ColumnType.POSTAL_CODE), "00-950").changed


def test_empty_cells() -> None:
    optional = ColumnRule("Uwagi")
    assert process(optional, None).error is None
    assert process(optional, "   ").changed  # whitespace was removed
    required = process(ColumnRule("Nazwisko", required=True), " ")
    assert required.error is not None
    assert required.error.category == MISSING


def test_invalid_value_keeps_original_text() -> None:
    cell = process(ColumnRule("NIP", ColumnType.NIP), "123")
    assert cell.value is None
    assert cell.text == "123"
    assert cell.error is not None


def test_allowed_values_are_matched_without_case_and_get_canonical_spelling() -> None:
    rule = ColumnRule("Status", allowed=("nowe", "opłacone"))
    assert process(rule, "OPŁACONE").value == "opłacone"
    error = process(rule, "w realizacji").error
    assert error is not None
    assert error.category == NOT_ALLOWED
    assert "nowe, opłacone" in error.reason


def test_allowed_values_for_numbers() -> None:
    rule = ColumnRule("Rabat", ColumnType.INTEGER, allowed=("5", "10"))
    assert process(rule, "10").value == 10
    assert process(rule, "7").error is not None


def test_long_allowed_list_is_shortened_in_the_message() -> None:
    rule = ColumnRule("Kod", allowed=tuple("abcdefgh"))
    error = process(rule, "z").error
    assert error is not None
    assert error.reason.endswith("…")


@pytest.mark.parametrize(
    ("rule", "raw", "fragment"),
    [
        (ColumnRule("K", ColumnType.DECIMAL, maximum=Decimal(100)), "150,5", "maksimum (100)"),
        (ColumnRule("I", ColumnType.INTEGER, minimum=Decimal(1)), "0", "minimum (1)"),
        (ColumnRule("D", ColumnType.DATE, minimum=date(2020, 1, 1)), "31.12.2019", "2020-01-01"),
        (ColumnRule("T", minimum=Decimal(3)), "ab", "za krótki (3 znaków)"),
        (ColumnRule("T", maximum=Decimal(3)), "abcd", "za długi"),
    ],
)
def test_ranges(rule: ColumnRule, raw: str, fragment: str) -> None:
    error = process(rule, raw).error
    assert error is not None
    assert error.category == OUT_OF_RANGE
    assert fragment in error.reason


def test_values_inside_range_pass() -> None:
    rule = ColumnRule("K", ColumnType.DECIMAL, minimum=Decimal(0), maximum=Decimal(100))
    assert process(rule, "100").error is None


def test_text_case_and_decimals() -> None:
    assert process(ColumnRule("Miasto", case=TextCase.TITLE), "ŁÓDŹ").value == "Łódź"
    cell = process(ColumnRule("Kwota", ColumnType.DECIMAL, decimals=2), "1 234,5 zł", ".")
    assert cell.text == "1234.50"


def test_cache_returns_the_same_result_for_repeated_text() -> None:
    processor = ColumnProcessor(ColumnRule("Miasto", case=TextCase.TITLE))
    assert processor.process("KRAKÓW") is processor.process("KRAKÓW")


@pytest.mark.parametrize(
    ("raw", "value", "text", "expected"),
    [
        ("1234,50", Decimal("1234.50"), "1234,50", False),
        ("1234.50", Decimal("1234.50"), "1234,50", True),
        (datetime(2026, 2, 1), date(2026, 2, 1), "2026-02-01", False),
        (datetime(2026, 2, 1, 9, 0), date(2026, 2, 1), "2026-02-01", True),
        (date(2026, 2, 1), date(2026, 2, 1), "2026-02-01", False),
        (1000.0, Decimal("1000.00"), "1000,00", False),
        (12, 12, "12", False),
        (950, "00-950", "00-950", True),
        (True, True, "tak", False),
    ],
)
def test_is_changed(raw: object, value: object, text: str, expected: bool) -> None:
    assert is_changed(raw, value, text) is expected


def test_similarity_key_ignores_legal_form_case_and_diacritics() -> None:
    assert similarity_key("Zielony Kłos Sp. z o.o.") == similarity_key("ZIELONY KŁOS SP Z OO")
    assert similarity_key("Zielony Kłos S.A.") == similarity_key("zielony klos")
    assert similarity_key("Sp. z o.o.") != ""
