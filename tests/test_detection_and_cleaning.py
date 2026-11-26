import codecs

import pytest

from walidator.cleaners import apply_case, as_text, clean_whitespace, fold_key, smart_title
from walidator.detection import (
    detect_delimiter,
    detect_encoding,
    guess_column,
    header_hint,
    suggest_similarity_key,
)
from walidator.model import ColumnRule, ColumnType, TextCase

POLISH = "Zażółć gęślą jaźń; Łódź; Świętokrzyskie"


# --- encodings and delimiters ----------------------------------------------------------------


def test_detect_encoding_recognises_bom() -> None:
    assert detect_encoding(codecs.BOM_UTF8 + POLISH.encode()) == "utf-8-sig"


def test_detect_encoding_recognises_utf8_without_bom() -> None:
    assert detect_encoding(POLISH.encode("utf-8")) == "utf-8"


def test_detect_encoding_survives_a_character_cut_at_the_end_of_the_sample() -> None:
    assert detect_encoding(POLISH.encode("utf-8")[:-1]) == "utf-8"


def test_detect_encoding_recognises_windows_1250() -> None:
    assert detect_encoding(POLISH.encode("cp1250")) == "cp1250"


def test_detect_encoding_recognises_iso_8859_2() -> None:
    assert detect_encoding(POLISH.encode("iso-8859-2")) == "iso-8859-2"


def test_detect_encoding_prefers_cp1250_for_plain_ascii_with_one_odd_byte() -> None:
    assert detect_encoding(b"abc;def\x80") == "cp1250"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a;b;c\n1,5;2,5;3\n4;5;6,75\n", ";"),
        ("a,b,c\n1.5,2.5,3\n4,5,6\n", ","),
        ("a\tb\tc\n1\t2\t3\n", "\t"),
        ("a|b|c\n1|2|3\n", "|"),
        ('"x;y",b\n"1;2",3\n', ","),
        ("", ";"),
    ],
)
def test_detect_delimiter(text: str, expected: str) -> None:
    assert detect_delimiter(text) == expected


# --- column types ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("NIP nabywcy", ColumnType.NIP),
        ("Adres e-mail", ColumnType.EMAIL),
        ("Nr telefonu", ColumnType.PHONE),
        ("Kod pocztowy dostawy", ColumnType.POSTAL_CODE),
        ("Strona WWW", ColumnType.URL),
        ("Data urodzenia", ColumnType.DATE),
        ("Zgoda marketingowa", ColumnType.BOOLEAN),
        ("Kwota brutto", ColumnType.DECIMAL),
        ("Ilość sztuk", ColumnType.INTEGER),
        ("Uwagi", None),
    ],
)
def test_header_hint(header: str, expected: ColumnType | None) -> None:
    assert header_hint(header) is expected


def test_guess_column_uses_header_and_content() -> None:
    guess = guess_column("Telefon", ["600 123 456", "+48 601 222 333", "502-111-222"])
    assert guess.rule.type is ColumnType.PHONE
    assert guess.source == "nagłówek i zawartość"
    assert guess.example == "600 123 456"


def test_guess_column_ignores_header_when_content_disagrees() -> None:
    guess = guess_column("Nr zamówienia", ["ZAM/2026/001", "ZAM/2026/002", "ZAM/2026/003"])
    assert guess.rule.type is ColumnType.TEXT
    assert guess.rule.unique  # identifier column without repeats


def test_guess_column_from_content_only() -> None:
    assert guess_column("Kolumna 3", ["jan@example.com", "ewa@example.org"]).rule.type is (
        ColumnType.EMAIL
    )
    assert guess_column("X", ["00-950", "30-001", "50765"]).rule.type is ColumnType.POSTAL_CODE
    assert guess_column("X", ["12", "7", "30"]).rule.type is ColumnType.INTEGER
    assert guess_column("X", ["12,50", "7", "30,99"]).rule.type is ColumnType.DECIMAL


def test_guess_column_suggests_rules() -> None:
    city = guess_column("Miasto", ["Warszawa", "KRAKÓW", "łódź"])
    assert city.rule.case is TextCase.TITLE
    assert city.rule.required
    amount = guess_column("Kwota netto", ["12,50", "", "", "7"])
    assert amount.rule.decimals == 2
    assert not amount.rule.required
    assert guess_column("E-mail", ["a@example.com", "a@example.com"]).rule.unique is False


def test_guess_column_without_data() -> None:
    assert guess_column("Data", [None, ""]).source == "nagłówek"
    assert guess_column("Uwagi", []).source == "brak danych"


def test_suggest_similarity_key_picks_company_column() -> None:
    headers = ["ID", "Nazwa firmy", "E-mail"]
    rules = [
        ColumnRule("ID", ColumnType.INTEGER),
        ColumnRule("Nazwa firmy"),
        ColumnRule("E-mail", ColumnType.EMAIL),
    ]
    assert suggest_similarity_key(headers, rules) == "Nazwa firmy"
    assert suggest_similarity_key(["E-mail"], [rules[2]]) is None


# --- cleaning helpers ------------------------------------------------------------------------


def test_clean_whitespace() -> None:
    assert clean_whitespace("  Jan \u00a0 \t Kowalski\u200b ") == "Jan Kowalski"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NOWE MIASTO NAD PILICĄ", "Nowe Miasto nad Pilicą"),
        ("bielsko-biała", "Bielsko-Biała"),
        ("McDonald", "McDonald"),
        ("ZIELONA GÓRA", "Zielona Góra"),
    ],
)
def test_smart_title(text: str, expected: str) -> None:
    assert smart_title(text) == expected


def test_apply_case() -> None:
    assert apply_case("Abc", TextCase.LOWER) == "abc"
    assert apply_case("Abc", TextCase.UPPER) == "ABC"
    assert apply_case("Abc", TextCase.KEEP) == "Abc"


def test_fold_key_ignores_case_diacritics_and_punctuation() -> None:
    assert fold_key("Łódzki Młyn, Sp. z o.o.") == fold_key("LODZKI MLYN SP Z OO")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), (True, "tak"), (12.0, "12"), (12.5, "12.5"), (7, "7"), ("x", "x")],
)
def test_as_text(value: object, expected: str) -> None:
    assert as_text(value) == expected


def test_as_text_for_dates() -> None:
    from datetime import date, datetime

    assert as_text(datetime(2026, 2, 1)) == "2026-02-01"
    assert as_text(datetime(2026, 2, 1, 8, 30)) == "2026-02-01 08:30:00"
    assert as_text(date(2026, 2, 1)) == "2026-02-01"
