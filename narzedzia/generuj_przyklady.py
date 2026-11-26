"""Generates fictional, deliberately messy sample files in przyklady/.

The output is deterministic (fixed random seed), so the files and the reports built from them
are the same on every machine.

    python narzedzia/generuj_przyklady.py            # klienci.xlsx and zamowienia.csv
    python narzedzia/generuj_przyklady.py --duzy     # also duzy_100k.csv for the speed test
"""

from __future__ import annotations

import argparse
import csv
import random
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import xlsxwriter

OUTPUT = Path(__file__).resolve().parent.parent / "przyklady"

FIRST_NAMES = (
    "Anna",
    "Katarzyna",
    "Małgorzata",
    "Agnieszka",
    "Barbara",
    "Ewa",
    "Magdalena",
    "Joanna",
    "Zofia",
    "Aleksandra",
    "Natalia",
    "Julia",
    "Maria",
    "Jadwiga",
    "Elżbieta",
    "Krystyna",
    "Piotr",
    "Krzysztof",
    "Andrzej",
    "Tomasz",
    "Paweł",
    "Michał",
    "Marcin",
    "Grzegorz",
    "Łukasz",
    "Jakub",
    "Mateusz",
    "Wojciech",
    "Kamil",
    "Szymon",
    "Józef",
    "Rafał",
)
SURNAMES = (
    ("Nowak", "Nowak"),
    ("Kowalski", "Kowalska"),
    ("Wiśniewski", "Wiśniewska"),
    ("Wójcik", "Wójcik"),
    ("Kowalczyk", "Kowalczyk"),
    ("Kamiński", "Kamińska"),
    ("Lewandowski", "Lewandowska"),
    ("Zieliński", "Zielińska"),
    ("Szymański", "Szymańska"),
    ("Woźniak", "Woźniak"),
    ("Dąbrowski", "Dąbrowska"),
    ("Kozłowski", "Kozłowska"),
    ("Jankowski", "Jankowska"),
    ("Mazur", "Mazur"),
    ("Kwiatkowski", "Kwiatkowska"),
    ("Krawczyk", "Krawczyk"),
    ("Piotrowski", "Piotrowska"),
    ("Grabowski", "Grabowska"),
    ("Pawłowski", "Pawłowska"),
    ("Michalski", "Michalska"),
    ("Król", "Król"),
    ("Wieczorek", "Wieczorek"),
    ("Jabłoński", "Jabłońska"),
    ("Majewski", "Majewska"),
)
COMPANY_FIRST = (
    "Zielony",
    "Bursztynowy",
    "Srebrny",
    "Złoty",
    "Mazowiecki",
    "Bałtycki",
    "Górski",
    "Leśny",
    "Polny",
    "Nadwiślański",
    "Kujawski",
    "Śląski",
    "Warmiński",
    "Podhalański",
    "Kaszubski",
)
COMPANY_SECOND = (
    "Kłos",
    "Młyn",
    "Dąb",
    "Most",
    "Sad",
    "Warsztat",
    "Spichlerz",
    "Port",
    "Rynek",
    "Ogród",
    "Kamień",
    "Zdrój",
    "Gościniec",
    "Tartak",
    "Browar",
)
INDUSTRIES = (
    "Transport",
    "Serwis",
    "Instalacje",
    "Meble",
    "Druk",
    "Catering",
    "Logistyka",
    "Budownictwo",
    "Ogrody",
    "Elektro",
    "Software",
    "Doradztwo",
    "Medica",
    "Agro",
    "Tekstylia",
    "Stal",
)
LEGAL_FORMS = ("Sp. z o.o.", "S.A.", "sp.j.", "Sp. k.", "")
CITIES = (
    ("Warszawa", "00"),
    ("Kraków", "30"),
    ("Łódź", "90"),
    ("Wrocław", "50"),
    ("Poznań", "60"),
    ("Gdańsk", "80"),
    ("Szczecin", "70"),
    ("Bydgoszcz", "85"),
    ("Lublin", "20"),
    ("Białystok", "15"),
    ("Katowice", "40"),
    ("Gdynia", "81"),
    ("Częstochowa", "42"),
    ("Radom", "26"),
    ("Toruń", "87"),
    ("Kielce", "25"),
    ("Rzeszów", "35"),
    ("Olsztyn", "10"),
    ("Bielsko-Biała", "43"),
    ("Zielona Góra", "65"),
    ("Nowe Miasto nad Pilicą", "26"),
)
SEGMENTS = ("detaliczny", "hurtowy", "partner")
STATUSES = ("nowe", "opłacone", "wysłane", "anulowane")
NOTES = (
    "",
    "",
    "",
    "Dostawa po 15:00",
    "Proszę o fakturę zbiorczą",
    "Klient prosi o telefon",
    "Paczkomat przy ulicy Żółkiewskiego",
    "Zwrot częściowy – uszkodzone opakowanie",
    "Pilne!",
    "Odbiór osobisty w Łodzi",
    "Brak dzwonka – dzwonić na komórkę",
)
NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


class Messy:
    """Produces values the many ways people really type them, plus deliberate errors.

    ``mess`` is the share of values written in a non-standard (but fixable) way and ``error``
    the share of values that are really wrong.
    """

    def __init__(self, rng: random.Random, mess: float, error: float) -> None:
        self.rng = rng
        self.mess = mess
        self.error = error

    def chance(self, probability: float) -> bool:
        return self.rng.random() < probability

    def pick(self, options: tuple) -> object:
        return self.rng.choice(options)

    def variant(self, canonical: object, variants: tuple, errors: tuple) -> object:
        if errors and self.chance(self.error):
            return self.rng.choice(errors)
        if self.chance(self.mess):
            return self.rng.choice(variants)
        return canonical

    def spaces(self, text: str) -> str:
        if not self.chance(self.mess / 2):
            return text
        return f"  {text} " if " " not in text else text.replace(" ", "   ", 1)

    def case(self, text: str) -> str:
        if not self.chance(self.mess / 2):
            return text
        return text.upper() if self.chance(0.6) else text.lower()

    def nip(self, valid: bool = True) -> str:
        while True:
            digits = [self.rng.randint(1, 9)] + [self.rng.randint(0, 9) for _ in range(8)]
            control = sum(d * w for d, w in zip(digits, NIP_WEIGHTS, strict=True)) % 11
            if control != 10:
                break
        if not valid:
            control = (control + self.rng.randint(1, 9)) % 10
        text = "".join(map(str, digits)) + str(control)
        return str(
            self.variant(
                text,
                (
                    f"{text[:3]}-{text[3:6]}-{text[6:8]}-{text[8:]}",
                    f"PL{text}",
                    f"{text[:3]} {text[3:6]} {text[6:8]} {text[8:]}",
                ),
                (text[:-1],),
            )
        )

    def phone(self) -> object:
        number = str(self.rng.choice((5, 6, 7, 8))) + "".join(
            str(self.rng.randint(0, 9)) for _ in range(8)
        )
        canonical = f"+48 {number[:3]} {number[3:6]} {number[6:]}"
        return self.variant(
            canonical,
            (
                f"{number[:3]} {number[3:6]} {number[6:]}",
                f"+48{number}",
                f"0048 {number[:3]}-{number[3:6]}-{number[6:]}",
                f"({number[:2]}) {number[2:5]} {number[5:7]} {number[7:]}",
                int(number),  # stored as a number in Excel
                f"{number[:3]}-{number[3:6]}-{number[6:]}",
            ),
            (number[:-1], "+49 " + number, "brak"),
        )

    def postal(self, prefix: str) -> object:
        code = f"{prefix}-{self.rng.randint(0, 999):03d}"
        return self.variant(code, (code.replace("-", ""), code.replace("-", " ")), (code[1:],))

    def email(self, first: str, last: str, domain: str, number: int | None = None) -> str:
        local = _ascii(f"{first}.{last}".lower()) + ("" if number is None else str(number))
        address = f"{local}@{domain}"
        head, tld = address.rsplit(".", 1)
        return str(
            self.variant(
                address,
                (
                    address.upper(),
                    f" {address} ",
                    f"{head},{tld}",
                    f"mailto:{address}",
                ),
                (
                    address.replace("@", ""),
                    f"{first.lower()}.{last.lower()}@{domain}",  # Polish letters
                    address.replace(".", "..", 1),
                    address.replace("@", "@@"),
                ),
            )
        )

    def day(self, start: date, end: date) -> date:
        return start + timedelta(days=self.rng.randint(0, (end - start).days))

    def date_value(self, value: date, canonical: object) -> object:
        return self.variant(
            canonical,
            (
                value.strftime("%d.%m.%Y"),
                value.isoformat(),
                f"{value.day}/{value.month}/{value.year}",
                f"{value.day} {_MONTHS_GENITIVE[value.month - 1]} {value.year}",
                f"{value.day}.{value.month}.{value.year}",
            ),
            (
                f"31.02.{value.year}",
                f"{value.month:02d}/{max(value.day, 13)}/{value.year}",  # US order
                value.strftime("%d.%m.%y"),
            ),
        )

    def amount(self, value: float, canonical: object) -> object:
        whole, cents = f"{value:.2f}".split(".")
        grouped = f"{int(whole):,}".replace(",", " ")
        return self.variant(
            canonical,
            (
                f"{grouped},{cents}",
                f"{grouped},{cents} zł",
                f"{whole}.{cents}",
                f"{int(whole):,}".replace(",", ".") + f",{cents}",
            ),
            ("do ustalenia", "12,34,56"),
        )


_MONTHS_GENITIVE = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)
_ASCII = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _ascii(text: str) -> str:
    return text.translate(_ASCII)


def _slug(text: str) -> str:
    return "".join(char for char in _ascii(text).lower() if char.isalnum())


# --- klienci.xlsx ------------------------------------------------------------------------------

CLIENT_HEADERS = (
    "ID klienta",
    "Imię",
    "Nazwisko",
    "Firma",
    "NIP",
    "E-mail",
    "Telefon",
    "Kod pocztowy",
    "Miasto",
    "Data rejestracji",
    "Limit kredytowy",
    "Strona WWW",
    "Zgoda marketingowa",
    "Segment",
)


def client_rows(count: int, rng: random.Random) -> list[list[object]]:
    messy = Messy(rng, mess=0.10, error=0.012)
    companies: list[str] = []
    rows: list[list[object]] = []
    for index in range(1, count + 1):
        female = messy.chance(0.5)
        first = str(rng.choice(FIRST_NAMES[:16] if female else FIRST_NAMES[16:]))
        last = rng.choice(SURNAMES)[1 if female else 0]
        company, slug = _company(messy, companies)
        city, prefix = rng.choice(CITIES)
        domain = (
            f"{slug}.example"
            if company and messy.chance(0.5)
            else rng.choice(("example.com", "example.org", "example.net"))
        )
        registered = messy.day(date(2016, 1, 1), date(2026, 10, 31))
        limit = (
            rng.choice((0, 1000, 2500, 5000, 10000, 15000, 25000, 50000)) + rng.randint(0, 99) * 10
        )
        consent = rng.choice(("tak", "nie"))
        segment = str(rng.choice(SEGMENTS))
        rows.append(
            [
                index if not messy.chance(0.006) else max(index - 7, 1),  # a few repeated IDs
                messy.spaces(messy.case(first)),
                "" if messy.chance(0.006) else messy.spaces(messy.case(last)),
                company,
                messy.nip(valid=not messy.chance(0.015)) if company else "",
                "" if messy.chance(0.006) else messy.email(first[0], last, domain, index),
                messy.phone(),
                messy.postal(prefix),
                messy.spaces(messy.case(city)),
                messy.date_value(
                    registered, datetime(registered.year, registered.month, registered.day)
                ),
                messy.amount(limit if not messy.chance(0.006) else 250_000, float(limit)),
                _website(messy, slug) if company else "",
                messy.variant(
                    consent,
                    (consent.upper(), consent[0], "1" if consent == "tak" else "0"),
                    ("może",),
                ),
                messy.variant(segment, (segment.capitalize(), segment.upper()), ("VIP",)),
            ]
        )
    _add_duplicates(rows, rng, share=0.008, cleanup=lambda row: _with_spaces(row, messy))
    return rows


def _company(messy: Messy, known: list[str]) -> tuple[str, str]:
    if messy.chance(0.45):
        return "", ""
    if known and messy.chance(0.04):
        base = str(messy.pick(tuple(known)))
        variant = base.upper() if messy.chance(0.5) else base.replace(".", "").replace("Sp", "sp")
        return variant, _slug(_without_form(base))
    name = _company_name(messy, {_without_form(company) for company in known})
    full = f"{name} {messy.pick(LEGAL_FORMS)}".strip()
    known.append(full)
    return full, _slug(name)


def _company_name(messy: Messy, taken: set[str]) -> str:
    """A fictional two-word company name, unique within the file while combinations last."""
    for _ in range(50):
        surname = str(messy.pick(SURNAMES)[0])
        pattern = messy.rng.randrange(4)
        if pattern == 0:
            name = f"{messy.pick(COMPANY_FIRST)} {messy.pick(COMPANY_SECOND)}"
        elif pattern == 1:
            name = f"{surname} {messy.pick(INDUSTRIES)}"
        elif pattern == 2:
            name = f"{messy.pick(INDUSTRIES)}-{messy.pick(CITIES)[0].split()[0]}"
        else:
            name = f"{messy.pick(COMPANY_SECOND)} {surname}"
        if name not in taken:
            return name
    return name


def _without_form(company: str) -> str:
    for form in filter(None, LEGAL_FORMS):
        if company.endswith(" " + form):
            return company.removesuffix(" " + form)
    return company


def _website(messy: Messy, slug: str) -> object:
    if messy.chance(0.4):
        return ""
    canonical = f"https://www.{slug}.example"
    return messy.variant(
        canonical,
        (f"www.{slug}.example", f"HTTPS://WWW.{slug.upper()}.EXAMPLE/kontakt", f"{slug}.example"),
        (f"{slug} kropka example", f"www.{slug}"),
    )


def _with_spaces(row: list[object], messy: Messy) -> list[object]:
    return [
        f" {value}" if isinstance(value, str) and value and messy.chance(0.3) else value
        for value in row
    ]


def _add_duplicates(
    rows: list[list[object]],
    rng: random.Random,
    share: float,
    cleanup: Callable[[list[object]], list[object]],
) -> None:
    for _ in range(int(len(rows) * share)):
        source = rng.randrange(len(rows))
        rows.insert(rng.randrange(source, len(rows)) + 1, cleanup(list(rows[source])))


def write_clients(path: Path, count: int = 2000) -> None:
    rng = random.Random(2026)
    book = xlsxwriter.Workbook(str(path), {"strings_to_numbers": False, "strings_to_urls": False})
    sheet = book.add_worksheet("Klienci")
    header = book.add_format({"bold": True, "bg_color": "#DDE6F3"})
    as_date = book.add_format({"num_format": "dd.mm.yyyy"})
    widths = (10, 13, 16, 30, 16, 34, 20, 12, 22, 16, 16, 38, 18, 12)
    for column, (name, width) in enumerate(zip(CLIENT_HEADERS, widths, strict=True)):
        sheet.set_column(column, column, width)
        sheet.write_string(0, column, name, header)
    sheet.freeze_panes(1, 0)
    row_index = 1
    for number, row in enumerate(client_rows(count, rng), start=1):
        for column, value in enumerate(row):
            if isinstance(value, datetime):
                sheet.write_datetime(row_index, column, value, as_date)
            elif isinstance(value, int | float):
                sheet.write_number(row_index, column, value)
            elif value:
                sheet.write_string(row_index, column, str(value))
        row_index += 2 if number in {640, 1310} else 1  # stray empty rows
    book.close()


# --- zamowienia.csv ----------------------------------------------------------------------------

ORDER_HEADERS = (
    "Nr zamówienia",
    "Data zamówienia",
    "NIP nabywcy",
    "Nabywca",
    "E-mail kontaktowy",
    "Kwota netto",
    "Ilość",
    "Status",
    "Kod pocztowy dostawy",
    "Faktura VAT",
    "Uwagi",
)


def order_rows(count: int, rng: random.Random) -> list[list[str]]:
    messy = Messy(rng, mess=0.12, error=0.01)
    buyers = []
    for _ in range(max(count // 12, 40)):
        name = f"{messy.pick(COMPANY_FIRST)} {messy.pick(COMPANY_SECOND)}"
        full = f"{name} {messy.pick(LEGAL_FORMS)}".strip()
        buyers.append((full, messy.nip(), _slug(name)))
    rows = []
    for index in range(1, count + 1):
        buyer, nip, slug = rng.choice(buyers)
        _, prefix = rng.choice(CITIES)
        ordered = messy.day(date(2025, 1, 1), date(2026, 11, 20))
        net = rng.choice((19.99, 49.5, 120, 349.99, 1299, 2450.4, 18750)) * rng.randint(1, 4)
        whole, cents = f"{net:.2f}".split(".")
        status = str(rng.choice(STATUSES))
        number = index if not messy.chance(0.004) else max(index - 3, 1)
        row = [
            f"ZAM/{ordered.year}/{number:05d}",
            str(messy.date_value(ordered, ordered.strftime("%d.%m.%Y"))),
            ""
            if messy.chance(0.006)
            else (nip if not messy.chance(0.01) else messy.nip(valid=False)),
            messy.spaces(buyer),
            messy.email("biuro", "zamowienia", f"{slug}.example") if not messy.chance(0.01) else "",
            str(messy.amount(net, f"{whole},{cents}")) if not messy.chance(0.004) else "-120,00",
            str(messy.variant(str(rng.randint(1, 40)), (" 12 ",), ("1,5", "2 szt.", "kilka"))),
            str(
                messy.variant(
                    status, (status.upper(), status.capitalize()), ("w realizacji", "oplacone")
                )
            ),
            str(messy.postal(prefix)),
            str(messy.variant(rng.choice(("tak", "nie")), ("T", "N", "TAK", "Nie"), ())),
            str(rng.choice(NOTES)),
        ]
        if messy.chance(0.003):
            row.append("pole przesunięte przez dodatkowy średnik")
        rows.append(row)
    _add_duplicates(rows, rng, share=0.006, cleanup=list)
    return rows


def write_orders(path: Path, count: int = 3000, seed: int = 1250) -> None:
    rng = random.Random(seed)
    with path.open("w", encoding="cp1250", errors="replace", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(ORDER_HEADERS)
        writer.writerows(order_rows(count, rng))


def main() -> None:
    parser = argparse.ArgumentParser(description="Tworzy przykładowe, celowo błędne pliki danych.")
    parser.add_argument("--duzy", action="store_true", help="utwórz też plik 100 000 wierszy")
    args = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    write_clients(OUTPUT / "klienci.xlsx")
    write_orders(OUTPUT / "zamowienia.csv")
    print(f"Zapisano {OUTPUT / 'klienci.xlsx'} i {OUTPUT / 'zamowienia.csv'}")
    if args.duzy:
        write_orders(OUTPUT / "duzy_100k.csv", count=100_000, seed=100_000)
        print(f"Zapisano {OUTPUT / 'duzy_100k.csv'}")


if __name__ == "__main__":
    main()
