"""End-to-end checks on the committed sample files in przyklady/."""

from pathlib import Path

import pytest

from walidator.cli import EXIT_REJECTED, main
from walidator.engine import RunOptions, analyze, run_check
from walidator.rules import load_rules

from .conftest import SAMPLES

EVERY_CATEGORY = {
    "Niepoprawny NIP",
    "Niepoprawny e-mail",
    "Niepoprawny telefon",
    "Niepoprawny kod pocztowy",
    "Niepoprawna data",
    "Niepoprawna liczba",
    "Niepoprawny adres WWW",
    "Niepoprawna wartość tak/nie",
    "Brak wymaganej wartości",
    "Wartość spoza zakresu",
    "Wartość niedozwolona",
    "Powtórzona wartość unikalna",
    "Duplikat wiersza",
}


@pytest.fixture(scope="module")
def clients(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("klienci")
    rules = load_rules(SAMPLES / "reguly_klienci.json")
    return run_check(SAMPLES / "klienci.xlsx", rules, RunOptions(output, rules_source="reguly"))


def test_clients_sample_contains_every_kind_of_error(clients) -> None:
    assert clients.total == 2016
    assert set(clients.categories) >= EVERY_CATEGORY
    assert 0 < clients.rejected < clients.total * 0.2
    assert clients.fixed > clients.total * 0.4
    assert clients.near_duplicates


def test_clients_outputs_exist(clients) -> None:
    for path in (clients.outputs.clean, clients.outputs.rejected, clients.outputs.report):
        assert path is not None
        assert path.stat().st_size > 1000


def test_orders_sample_is_cp1250_with_semicolons() -> None:
    info = analyze(SAMPLES / "zamowienia.csv").info
    assert (info.encoding, info.delimiter) == ("cp1250", ";")
    assert "Nr zamówienia" in info.headers


def test_orders_sample_through_cli(tmp_path: Path) -> None:
    code = main(
        [
            str(SAMPLES / "zamowienia.csv"),
            "--reguly",
            str(SAMPLES / "reguly_zamowienia.json"),
            "--wyjscie",
            str(tmp_path),
            "--format",
            "xlsx",
            "-q",
        ]
    )
    assert code == EXIT_REJECTED
    assert (tmp_path / "zamowienia_czyste.xlsx").is_file()
    assert (tmp_path / "zamowienia_raport.html").is_file()


def test_generator_is_deterministic(tmp_path: Path) -> None:
    import random
    import sys

    sys.path.insert(0, str(SAMPLES.parent / "narzedzia"))
    try:
        from generuj_przyklady import order_rows
    finally:
        sys.path.pop(0)
    first = order_rows(200, random.Random(1))
    assert first == order_rows(200, random.Random(1))
    assert len(first) > 200  # duplicates were added on purpose
