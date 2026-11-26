"""Window state after loading files. Background work runs synchronously in these tests."""

from __future__ import annotations

import tkinter
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest

ctk = pytest.importorskip("customtkinter")

from walidator.gui import app as gui_app  # noqa: E402 - after the optional dependency check

CSV_TEXT = "Nazwa;E-mail\r\nAlfa;alfa@example.com\r\n"


def write_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CSV_TEXT, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def window() -> Iterator[gui_app.App]:
    """One window for the module: Tk does not like being created many times in one process."""
    try:
        created = gui_app.App()
    except tkinter.TclError as error:  # pragma: no cover - no display available
        pytest.skip(f"Tk is not available: {error}")
    created.withdraw()
    yield created
    created._close()


@pytest.fixture
def app(window: gui_app.App, monkeypatch: pytest.MonkeyPatch) -> gui_app.App:
    window.file = window.analysis = window.result = window.loaded_rules = None
    window.busy = False
    window.auto_output_dir = ""
    window.output_dir.set("")
    window._refresh_buttons()
    errors: list[tuple[Any, ...]] = []
    monkeypatch.setattr(gui_app.messagebox, "showerror", lambda *args, **_: errors.append(args))

    def run_now(_message: str, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        future: Future[Any] = Future()
        try:
            future.set_result(work())
        except Exception as error:
            future.set_exception(error)
        window._finish_task(future, done)

    monkeypatch.setattr(window, "_start_task", run_now)
    window.shown_errors = errors  # type: ignore[attr-defined]
    return window


def test_output_folder_follows_each_opened_file(app: gui_app.App, tmp_path: Path) -> None:
    first = write_csv(tmp_path / "a" / "dane.csv")
    second = write_csv(tmp_path / "b" / "dane.csv")
    app.open_file(first)
    assert Path(app.output_dir.get()) == first.parent / "wynik"
    app.open_file(second)
    assert Path(app.output_dir.get()) == second.parent / "wynik"


def test_output_folder_chosen_by_the_user_is_kept(app: gui_app.App, tmp_path: Path) -> None:
    app.open_file(write_csv(tmp_path / "a" / "dane.csv"))
    app.output_dir.set(str(tmp_path / "moje wyniki"))
    app.open_file(write_csv(tmp_path / "b" / "dane.csv"))
    assert Path(app.output_dir.get()) == tmp_path / "moje wyniki"


def test_failed_load_keeps_the_previous_file(app: gui_app.App, tmp_path: Path) -> None:
    good = write_csv(tmp_path / "dobry.csv")
    bad = tmp_path / "zly.pdf"
    bad.write_text("x")
    app.open_file(good)
    app.open_file(bad)
    assert app.shown_errors  # type: ignore[attr-defined]
    assert app.file == good
    assert app.analysis is not None
    assert app.analysis.info.path == good
    assert app.file_title.cget("text") == good.name
    assert Path(app.output_dir.get()) == good.parent / "wynik"
    assert app.run_button.cget("state") == "normal"


def test_failed_first_load_leaves_check_disabled(app: gui_app.App, tmp_path: Path) -> None:
    app.open_file(tmp_path / "brak.csv")
    assert app.file is None
    assert app.run_button.cget("state") == "disabled"


def test_events_keep_being_polled_when_a_callback_fails(
    app: gui_app.App, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[Callable[[], None]] = []
    monkeypatch.setattr(app, "after", lambda _ms, callback: scheduled.append(callback))
    finished: Future[None] = Future()
    finished.set_result(None)

    def broken(_value: object) -> None:
        raise RuntimeError("awaria")

    app.busy = True
    app.events.put(("done", (finished, broken)))
    with pytest.raises(RuntimeError):
        app._poll_events()
    assert scheduled == [app._poll_events]
    assert not app.busy
    assert app.open_button.cget("state") == "normal"


def test_similarity_caption_does_not_promise_typo_detection(app: gui_app.App) -> None:
    def texts(widget: tkinter.Misc) -> Iterator[str]:
        if isinstance(widget, ctk.CTkLabel):
            yield str(widget.cget("text"))
        for child in widget.winfo_children():
            yield from texts(child)

    captions = list(texts(app))
    assert not any("literówki" in caption for caption in captions)
    assert any(caption.startswith("Podobne zapisy") for caption in captions)
