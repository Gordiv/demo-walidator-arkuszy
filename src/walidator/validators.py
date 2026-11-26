"""Parsers that check one value of a given type and return it in a normalised form.

Every parser takes a cell value (text already trimmed, or a native value read from XLSX)
and either returns the normalised Python value or raises :class:`InvalidValue`
with a reason written in Polish.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from walidator.cleaners import as_text
from walidator.model import ColumnType


class InvalidValue(Exception):  # noqa: N818 - reads naturally at raise sites
    """A value that cannot be accepted. ``category`` groups reasons in the report."""

    def __init__(self, category: str, reason: str) -> None:
        super().__init__(reason)
        self.category = category
        self.reason = reason


Parser = Callable[[object], object]

# --- numbers ---------------------------------------------------------------------------------

NUMBER_ERROR = "Niepoprawna liczba"
_NUMBER_NOISE = re.compile(r"[\s'\u00a0\u202f]")
_CURRENCY = re.compile(r"^(?:pln|zł|zl|eur|€|usd|\$)|(?:pln|zł|zl|eur|€|usd|\$)$", re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_DOT_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})+$")
_COMMA_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+$")


def parse_decimal(value: object) -> Decimal:
    """Reads amounts like "1 234,56 zł", "1.234,56", "1,234.56" or "1234.5"."""
    if isinstance(value, bool):
        raise InvalidValue(NUMBER_ERROR, "Wartość logiczna zamiast liczby")
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    compact = _NUMBER_NOISE.sub("", str(value)).replace("\u2212", "-")
    text = _unify_separators(_CURRENCY.sub("", compact))
    if not _PLAIN_NUMBER.match(text):
        raise InvalidValue(NUMBER_ERROR, f"„{value}” nie jest liczbą")
    return Decimal(text)


def _unify_separators(text: str) -> str:
    """Leaves a single "." as the decimal separator; the other symbol is a thousands mark."""
    if "," in text and "." in text:
        decimal_mark = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal_mark == "," else ","
        return text.replace(thousands, "").replace(",", ".")
    if text.count(",") > 1 and _COMMA_THOUSANDS.match(text):
        return text.replace(",", "")
    if text.count(".") > 1 and _DOT_THOUSANDS.match(text):
        return text.replace(".", "")
    return text.replace(",", ".")


def parse_integer(value: object) -> int:
    """Reads whole numbers; "1 200" and "1.200" (Polish thousands) both give 1200."""
    if isinstance(value, bool):
        raise InvalidValue(NUMBER_ERROR, "Wartość logiczna zamiast liczby")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        compact = _NUMBER_NOISE.sub("", value)
        if _DOT_THOUSANDS.match(compact):
            return int(compact.replace(".", ""))
    number = parse_decimal(value)
    if number != number.to_integral_value():
        raise InvalidValue(NUMBER_ERROR, f"„{as_text(value)}” nie jest liczbą całkowitą")
    return int(number)


def round_decimal(number: Decimal, places: int) -> Decimal:
    return number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


# --- dates -----------------------------------------------------------------------------------

DATE_ERROR = "Niepoprawna data"
_TIME = r"(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"
_ISO_DATE = re.compile(rf"^(\d{{4}})[-./](\d{{1,2}})[-./](\d{{1,2}}){_TIME}$")
_DAY_FIRST = re.compile(rf"^(\d{{1,2}})[-./](\d{{1,2}})[-./](\d{{4}}){_TIME}$")
_SHORT_YEAR = re.compile(r"^\d{1,2}[-./]\d{1,2}[-./]\d{2}$")
_WORDS_DATE = re.compile(r"^(\d{1,2})\s+([^\W\d_]+)\.?\s+(\d{4})(?:\s*r\.?)?$")
_MONTH_NAMES = (
    ("styczeń", "stycznia", "sty"),
    ("luty", "lutego", "lut"),
    ("marzec", "marca", "mar"),
    ("kwiecień", "kwietnia", "kwi"),
    ("maj", "maja"),
    ("czerwiec", "czerwca", "cze"),
    ("lipiec", "lipca", "lip"),
    ("sierpień", "sierpnia", "sie"),
    ("wrzesień", "września", "wrz"),
    ("październik", "października", "paź", "paz"),
    ("listopad", "listopada", "lis"),
    ("grudzień", "grudnia", "gru"),
)
_MONTHS = {name: number for number, names in enumerate(_MONTH_NAMES, 1) for name in names}


def parse_date(value: object) -> date:
    """Reads 01.02.2026, 1/2/2026, 2026-02-01 or "1 lutego 2026" (the day comes first)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = as_text(value).strip()
    if match := _ISO_DATE.match(text):
        year, month, day = (int(part) for part in match.groups())
    elif match := _DAY_FIRST.match(text):
        day, month, year = (int(part) for part in match.groups())
    elif match := _WORDS_DATE.match(text.lower()):
        day, year = int(match[1]), int(match[3])
        month = _MONTHS.get(match[2], 0)
        if not month:
            raise InvalidValue(DATE_ERROR, f"Nieznana nazwa miesiąca „{match[2]}”")
    elif _SHORT_YEAR.match(text):
        raise InvalidValue(DATE_ERROR, f"Rok zapisany dwiema cyframi jest niejednoznaczny: {text}")
    else:
        raise InvalidValue(DATE_ERROR, f"„{text}” nie wygląda jak data")
    return _build_date(year, month, day, text)


def _build_date(year: int, month: int, day: int, text: str) -> date:
    if month > 12 >= day:
        raise InvalidValue(DATE_ERROR, f"Miesiąc {month} nie istnieje – zapis MM/DD? ({text})")
    try:
        return date(year, month, day)
    except ValueError as error:
        raise InvalidValue(DATE_ERROR, f"Nie ma takiej daty: {text}") from error


# --- contact and company data ----------------------------------------------------------------

EMAIL_ERROR = "Niepoprawny e-mail"
_EMAIL = re.compile(
    r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$"
)
_COMMA_BEFORE_TLD = re.compile(r",([a-z]{2,24})$")


def parse_email(value: object) -> str:
    """Lower-cases the address and fixes safe typos: spaces, "mailto:", a comma before the TLD."""
    text = as_text(value).strip().strip("<>").lower().replace(" ", "").removeprefix("mailto:")
    text = _COMMA_BEFORE_TLD.sub(r".\1", text)
    if "@" not in text:
        raise InvalidValue(EMAIL_ERROR, "Brak znaku @")
    if text.count("@") > 1:
        raise InvalidValue(EMAIL_ERROR, "Więcej niż jeden znak @")
    local, domain = text.split("@")
    if not local or not domain:
        raise InvalidValue(EMAIL_ERROR, "Brak nazwy przed @ lub domeny po @")
    if ".." in text:
        raise InvalidValue(EMAIL_ERROR, "Dwie kropki obok siebie")
    if "." not in domain:
        raise InvalidValue(EMAIL_ERROR, f"Domena „{domain}” nie ma kropki")
    if not text.isascii():
        raise InvalidValue(EMAIL_ERROR, "Polskie znaki w adresie e-mail")
    if not _EMAIL.match(text):
        raise InvalidValue(EMAIL_ERROR, "Niedozwolone znaki w adresie")
    return text


PHONE_ERROR = "Niepoprawny telefon"
_PHONE_NOISE = re.compile(r"[\s\-().\/\u00a0]")


def parse_phone(value: object) -> str:
    """Accepts Polish numbers with or without +48 / 0048 and returns "+48 600 123 456"."""
    digits = _PHONE_NOISE.sub("", as_text(value))
    if digits.startswith("+") and not digits.startswith("+48"):
        raise InvalidValue(PHONE_ERROR, f"Numer zagraniczny ({digits[:3]}…), oczekiwano polskiego")
    for prefix in ("+48", "0048"):
        digits = digits.removeprefix(prefix)
    if len(digits) == 11 and digits.startswith("48"):
        digits = digits[2:]
    if not digits.isdigit():
        raise InvalidValue(PHONE_ERROR, "Niedozwolone znaki w numerze")
    if len(digits) != 9:
        raise InvalidValue(PHONE_ERROR, f"Numer ma {len(digits)} cyfr zamiast 9")
    if digits[0] == "0":
        raise InvalidValue(PHONE_ERROR, "Numer nie może zaczynać się od 0")
    return f"+48 {digits[:3]} {digits[3:6]} {digits[6:]}"


POSTAL_ERROR = "Niepoprawny kod pocztowy"
_POSTAL = re.compile(r"^(\d{2})[-\u2010\u2011–]?(\d{3})$")


def parse_postal_code(value: object) -> str:
    text = as_text(value).replace(" ", "")
    if isinstance(value, int | float) and text.isdigit():
        text = text.zfill(5)  # Excel drops the leading zero of codes like 00-950
    if not (match := _POSTAL.match(text)):
        raise InvalidValue(POSTAL_ERROR, f"„{as_text(value)}” – oczekiwano formatu 00-000")
    return f"{match[1]}-{match[2]}"


NIP_ERROR = "Niepoprawny NIP"
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_NIP_NOISE = re.compile(r"[\s\-.]")


def nip_checksum_ok(digits: str) -> bool:
    """Checks the NIP control digit: weighted sum of the first nine digits modulo 11."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    control = (
        sum(int(digit) * weight for digit, weight in zip(digits, _NIP_WEIGHTS, strict=False)) % 11
    )
    return control != 10 and control == int(digits[9])


def parse_nip(value: object) -> str:
    """Accepts "PL 123-456-32-18" or "1234563218" and returns the ten digits."""
    text = _NIP_NOISE.sub("", as_text(value)).upper().removeprefix("PL")
    if not text.isdigit():
        raise InvalidValue(NIP_ERROR, "NIP może zawierać tylko cyfry")
    if len(text) != 10:
        raise InvalidValue(NIP_ERROR, f"NIP musi mieć 10 cyfr (ma {len(text)})")
    if not nip_checksum_ok(text):
        raise InvalidValue(NIP_ERROR, "Zła cyfra kontrolna NIP")
    return text


URL_ERROR = "Niepoprawny adres WWW"
_HOST = re.compile(r"^(?:[^\W_](?:[^\W_]|-)*\.)+[^\W\d_]{2,}$")
_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]*)://", re.IGNORECASE)
_AFTER_HOST = re.compile(r"[/?#]")


def parse_url(value: object) -> str:
    """Adds a missing https:// and lower-cases the host: "WWW.Firma.pl" -> "https://www.firma.pl"."""
    text = as_text(value).strip()
    if " " in text or "@" in text:
        raise InvalidValue(URL_ERROR, "Adres WWW nie może zawierać spacji ani @")
    scheme_match = _SCHEME.match(text)
    scheme = scheme_match[1].lower() if scheme_match else "https"
    if scheme not in {"http", "https"}:
        raise InvalidValue(URL_ERROR, f"Nieobsługiwany protokół „{scheme}”")
    rest = text[scheme_match.end() :] if scheme_match else text
    split = _AFTER_HOST.search(rest)
    host_port, tail = (rest[: split.start()], rest[split.start() :]) if split else (rest, "")
    host, _, port = host_port.partition(":")
    if not _HOST.match(host.lower()) or (port and not port.isdigit()):
        raise InvalidValue(URL_ERROR, f"„{text}” nie jest adresem strony")
    return f"{scheme}://{host.lower()}{':' + port if port else ''}{tail}"


BOOLEAN_ERROR = "Niepoprawna wartość tak/nie"
_TRUE = frozenset({"tak", "t", "yes", "y", "true", "prawda", "1", "x", "✓", "✔"})
_FALSE = frozenset({"nie", "n", "no", "false", "fałsz", "falsz", "0", "-"})


def parse_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = as_text(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise InvalidValue(BOOLEAN_ERROR, f"„{as_text(value)}” – oczekiwano „tak” lub „nie”")


def parse_text(value: object) -> str:
    return as_text(value)


PARSERS: dict[ColumnType, Parser] = {
    ColumnType.TEXT: parse_text,
    ColumnType.INTEGER: parse_integer,
    ColumnType.DECIMAL: parse_decimal,
    ColumnType.DATE: parse_date,
    ColumnType.EMAIL: parse_email,
    ColumnType.PHONE: parse_phone,
    ColumnType.POSTAL_CODE: parse_postal_code,
    ColumnType.NIP: parse_nip,
    ColumnType.URL: parse_url,
    ColumnType.BOOLEAN: parse_boolean,
}


def accepts(column_type: ColumnType, value: object) -> bool:
    """True when the value parses as the given type (used by type detection)."""
    try:
        PARSERS[column_type](value)
    except InvalidValue:
        return False
    return True


def format_value(value: object, decimal_separator: str = ",") -> str:
    """Formats a normalised value for CSV files, the report and before/after examples."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "tak" if value else "nie"
    if isinstance(value, Decimal):
        return format(value, "f").replace(".", decimal_separator)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
