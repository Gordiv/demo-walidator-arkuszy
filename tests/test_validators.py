from datetime import date, datetime
from decimal import Decimal

import pytest

from walidator.validators import (
    InvalidValue,
    format_value,
    nip_checksum_ok,
    parse_boolean,
    parse_date,
    parse_decimal,
    parse_email,
    parse_integer,
    parse_nip,
    parse_phone,
    parse_postal_code,
    parse_url,
    round_decimal,
)


def reason_of(parser, value) -> str:
    with pytest.raises(InvalidValue) as error:
        parser(value)
    return error.value.reason


# --- NIP -------------------------------------------------------------------------------------


def make_nip(prefix: str) -> str:
    """Builds a fictional NIP with a correct control digit."""
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    return prefix + str(sum(int(d) * w for d, w in zip(prefix, weights, strict=True)) % 11)


@pytest.mark.parametrize("nip", ["1234563218", make_nip("987654321"), make_nip("111222333")])
def test_nip_checksum_accepts_valid_numbers(nip: str) -> None:
    assert nip_checksum_ok(nip)


@pytest.mark.parametrize("nip", ["1234563219", "123456321", "12345632180", "12345a3218", ""])
def test_nip_checksum_rejects_invalid_numbers(nip: str) -> None:
    assert not nip_checksum_ok(nip)


@pytest.mark.parametrize("last_digit", range(10))
def test_nip_checksum_rejects_prefixes_whose_control_would_be_ten(last_digit: int) -> None:
    # 2 x weight 5 = 10, and 10 % 11 = 10 cannot be written as one digit
    assert not nip_checksum_ok(f"000000200{last_digit}")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234563218", "1234563218"),
        ("123-456-32-18", "1234563218"),
        ("PL 123 456 32 18", "1234563218"),
        ("pl1234563218", "1234563218"),
        (1234563218, "1234563218"),
        (1234563218.0, "1234563218"),
    ],
)
def test_parse_nip_normalises_formats(raw: object, expected: str) -> None:
    assert parse_nip(raw) == expected


def test_parse_nip_explains_errors() -> None:
    assert reason_of(parse_nip, "1234563219") == "Zła cyfra kontrolna NIP"
    assert "ma 9" in reason_of(parse_nip, "123456321")
    assert "tylko cyfry" in reason_of(parse_nip, "12345X3218")


# --- phones and postal codes -----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "600123456",
        "600 123 456",
        "600-123-456",
        "+48 600 123 456",
        "+48600123456",
        "0048 600-123-456",
        "48600123456",
        "(60) 012 34 56",
        600123456,
        600123456.0,
    ],
)
def test_parse_phone_accepts_polish_formats(raw: object) -> None:
    assert parse_phone(raw) == "+48 600 123 456"


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("60012345", "8 cyfr"),
        ("6001234567", "10 cyfr"),
        ("+49 600 123 456", "zagraniczny"),
        ("060 012 345", "od 0"),
        ("brak", "Niedozwolone znaki"),
    ],
)
def test_parse_phone_explains_errors(raw: str, fragment: str) -> None:
    assert fragment in reason_of(parse_phone, raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00-950", "00-950"),
        ("00950", "00-950"),
        ("00 950", "00-950"),
        ("00–950", "00-950"),
        (950, "00-950"),
        (30001, "30-001"),
    ],
)
def test_parse_postal_code(raw: object, expected: str) -> None:
    assert parse_postal_code(raw) == expected


@pytest.mark.parametrize("raw", ["0-950", "000-950", "00-95", "AB-123"])
def test_parse_postal_code_rejects_bad_codes(raw: str) -> None:
    assert "00-000" in reason_of(parse_postal_code, raw)


# --- dates -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "01.02.2026",
        "1.2.2026",
        "2026-02-01",
        "2026/02/01",
        "1/2/2026",
        "01-02-2026",
        "1 lutego 2026",
        "1 lut 2026",
        "1 luty 2026 r.",
        "2026-02-01 13:45",
        "01.02.2026 08:00:00",
        datetime(2026, 2, 1, 0, 0),
        date(2026, 2, 1),
    ],
)
def test_parse_date_normalises_to_one_day(raw: object) -> None:
    assert parse_date(raw) == date(2026, 2, 1)


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("31.02.2026", "Nie ma takiej daty"),
        ("12/25/2025", "MM/DD"),
        ("01.02.26", "dwiema cyframi"),
        ("1 smarca 2026", "Nieznana nazwa miesiąca"),
        ("wczoraj", "nie wygląda jak data"),
    ],
)
def test_parse_date_explains_errors(raw: str, fragment: str) -> None:
    assert fragment in reason_of(parse_date, raw)


# --- numbers ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1\u00a0234,56 zł", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1234.5", "1234.5"),
        ("PLN 100", "100"),
        ("1.234.567", "1234567"),
        ("1,234,567", "1234567"),
        ("\u22125,5", "-5.5"),
        ("-0,99", "-0.99"),
        (12.5, "12.5"),
        (7, "7"),
    ],
)
def test_parse_decimal_understands_polish_and_english_notation(raw: object, expected: str) -> None:
    assert parse_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["do ustalenia", "12,34,56", "1.2.3", "", "zł"])
def test_parse_decimal_rejects_text(raw: str) -> None:
    assert "nie jest liczbą" in reason_of(parse_decimal, raw)


def test_parse_decimal_rejects_booleans() -> None:
    assert "logiczna" in reason_of(parse_decimal, True)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("12", 12), ("1 200", 1200), ("1.200", 1200), ("12,0", 12), (12.0, 12), (5, 5), ("+3", 3)],
)
def test_parse_integer(raw: object, expected: int) -> None:
    assert parse_integer(raw) == expected


def test_parse_integer_rejects_fractions_and_booleans() -> None:
    assert "całkowitą" in reason_of(parse_integer, "1,5")
    assert "logiczna" in reason_of(parse_integer, False)


def test_round_decimal_rounds_half_up() -> None:
    assert round_decimal(Decimal("2.345"), 2) == Decimal("2.35")
    assert str(round_decimal(Decimal("10"), 2)) == "10.00"


# --- e-mail, URL, yes/no ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jan.Kowalski@Example.com", "jan.kowalski@example.com"),
        ("  jan@example.com ", "jan@example.com"),
        ("jan @ example.com", "jan@example.com"),
        ("mailto:jan@example.com", "jan@example.com"),
        ("<jan@example.com>", "jan@example.com"),
        ("jan@example,pl", "jan@example.pl"),
        ("jan@poczta.example", "jan@poczta.example"),
    ],
)
def test_parse_email_cleans_safe_mistakes(raw: str, expected: str) -> None:
    assert parse_email(raw) == expected


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("jan.example.com", "Brak znaku @"),
        ("jan@@example.com", "Więcej niż jeden"),
        ("@example.com", "Brak nazwy"),
        ("jan..nowak@example.com", "Dwie kropki"),
        ("jan@example", "nie ma kropki"),
        ("józef@example.com", "Polskie znaki"),
        ("jan(at)x@example.com", "Niedozwolone"),
    ],
)
def test_parse_email_explains_errors(raw: str, fragment: str) -> None:
    assert fragment in reason_of(parse_email, raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("www.firma.pl", "https://www.firma.pl"),
        ("HTTPS://WWW.Firma.PL/Kontakt", "https://www.firma.pl/Kontakt"),
        ("http://sklep.example:8080/a?b=1", "http://sklep.example:8080/a?b=1"),
        ("łódź.pl", "https://łódź.pl"),
    ],
)
def test_parse_url(raw: str, expected: str) -> None:
    assert parse_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("firma kropka pl", "spacji"),
        ("ftp://firma.pl", "protokół"),
        ("firma", "adresem"),
        ("www.firma.pl:abc", "adresem"),
    ],
)
def test_parse_url_explains_errors(raw: str, fragment: str) -> None:
    assert fragment in reason_of(parse_url, raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("tak", True),
        ("TAK", True),
        ("t", True),
        ("1", True),
        (1, True),
        ("x", True),
        ("nie", False),
        ("N", False),
        ("0", False),
        ("fałsz", False),
        (False, False),
    ],
)
def test_parse_boolean(raw: object, expected: bool) -> None:
    assert parse_boolean(raw) is expected


def test_parse_boolean_rejects_other_words() -> None:
    assert "tak" in reason_of(parse_boolean, "może")


def test_format_value() -> None:
    assert format_value(Decimal("1234.50")) == "1234,50"
    assert format_value(Decimal("1234.50"), ".") == "1234.50"
    assert format_value(date(2026, 2, 1)) == "2026-02-01"
    assert format_value(True) == "tak"
    assert format_value(None) == ""
    assert format_value(17) == "17"


# --- regressions -----------------------------------------------------------------------------


@pytest.mark.parametrize("nip", ["0000000000", "1111111111", "PL 999-999-99-99"])
def test_parse_nip_rejects_identical_digits(nip: str) -> None:
    assert "takich samych cyfr" in reason_of(parse_nip, nip)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("22 123 45 67", "+48 22 123 45 67"),
        ("(85) 178 83 65", "+48 85 178 83 65"),
        ("+48 12 345 67 89", "+48 12 345 67 89"),
        ("600 123 456", "+48 600 123 456"),
        ("(66) 079 11 35", "+48 660 791 135"),
    ],
)
def test_parse_phone_formats_landlines_with_area_code(raw: str, expected: str) -> None:
    assert parse_phone(raw) == expected


@pytest.mark.parametrize("raw", ["2026-02-01 25:99", "01.02.2026 24:00", "2026-02-01 12:60"])
def test_parse_date_rejects_impossible_times(raw: str) -> None:
    assert "godzina" in reason_of(parse_date, raw)


def test_round_decimal_rejects_numbers_too_long_to_round() -> None:
    error = reason_of(lambda value: round_decimal(value, 2), Decimal("1" * 28))
    assert "za dużo cyfr" in error
