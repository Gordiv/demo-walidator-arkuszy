"""Desktop window. All checking is done by the core library in a background thread."""

from __future__ import annotations

import argparse
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from walidator import APP_NAME, __version__
from walidator.engine import Analysis, OutputFormat, RunOptions, analyze, run_check
from walidator.errors import CancelledError, WalidatorError
from walidator.gui import theme
from walidator.gui.widgets import (
    Card,
    ColumnTable,
    StatTile,
    keyboard_button,
    keyboard_checkbox,
    keyboard_option_menu,
    keyboard_segmented,
)
from walidator.logs import LOG_FILE, setup_logging
from walidator.model import ColumnType, RuleSet
from walidator.report import num, seconds
from walidator.results import RunResult
from walidator.rules import load_rules, save_rules

log = logging.getLogger(__name__)

try:  # drag and drop is optional: the window works without it
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DnDWrapper: type = TkinterDnD.DnDWrapper
    DND_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the installation
    DnDWrapper = object
    DND_AVAILABLE = False

FILE_TYPES = [
    ("Arkusze i pliki CSV", "*.xlsx *.xlsm *.xls *.ods *.csv *.txt *.tsv"),
    ("Wszystkie pliki", "*.*"),
]
FORMATS: dict[str, OutputFormat] = {"Jak wejście": "jak_wejscie", "XLSX": "xlsx", "CSV": "csv"}
THEMES = {"Jasny": "light", "Ciemny": "dark"}
NO_KEY = "(nie szukaj)"
POLL_MS = 60


class App(ctk.CTk, DnDWrapper):  # type: ignore[misc]
    def __init__(self, start_file: Path | None = None, rules_file: Path | None = None) -> None:
        super().__init__(fg_color=theme.BACKGROUND)
        self.dnd = _enable_drag_and_drop(self)
        self.title(APP_NAME)
        self.geometry("{}x{}".format(*theme.WINDOW_SIZE))
        self.minsize(*theme.MIN_SIZE)
        _set_icon(self)

        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="walidator")
        self.events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self.cancel = threading.Event()
        self.file: Path | None = None
        self.analysis: Analysis | None = None
        self.loaded_rules: RuleSet | None = None
        self.rules_name: str | None = None
        self.result: RunResult | None = None
        self.busy = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()
        self._build_status_bar()
        self._bind_shortcuts()
        self._refresh_buttons()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(POLL_MS, self._poll_events)
        if rules_file:
            self.after(50, lambda: self._load_rules_file(rules_file))
        if start_file:
            self.after(100, lambda: self.open_file(start_file))

    # --- layout ------------------------------------------------------------------------------

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, height=64)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        logo = ctk.CTkLabel(
            bar,
            text="✓",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=theme.ACCENT,
            text_color="#FFFFFF",
            font=theme.font(20, "bold"),
        )
        logo.grid(row=0, column=0, rowspan=2, padx=(22, 12), pady=12)
        ctk.CTkLabel(
            bar,
            text=APP_NAME,
            font=theme.font(18, "bold"),
            text_color=theme.TEXT,
            anchor="w",
            height=22,
        ).grid(row=0, column=1, sticky="sw", pady=(12, 0))
        ctk.CTkLabel(
            bar,
            text="Sprawdzanie i czyszczenie danych z plików XLSX i CSV",
            font=theme.font(12),
            text_color=theme.MUTED,
            anchor="w",
            height=18,
        ).grid(row=1, column=1, sticky="nw", pady=(0, 12))
        ctk.CTkLabel(bar, text="Motyw", font=theme.font(12), text_color=theme.MUTED).grid(
            row=0, column=2, rowspan=2, padx=(0, 10)
        )
        self.theme_switch = _segmented(bar, list(THEMES), self._set_theme)
        self.theme_switch.set("Ciemny" if ctk.get_appearance_mode() == "Dark" else "Jasny")
        self.theme_switch.grid(row=0, column=3, rowspan=2, padx=(0, 22))
        keyboard_segmented(self.theme_switch, self._set_theme)
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER, corner_radius=0).grid(
            row=0, column=0, sticky="sew"
        )

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(16, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, minsize=372)
        body.grid_rowconfigure(1, weight=1)
        self._build_file_card(body)
        self._build_columns_card(body)
        side = ctk.CTkFrame(body, fg_color="transparent")
        side.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(16, 0))
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(1, weight=1)
        self._build_settings_card(side)
        self._build_results_card(side)

    def _build_file_card(self, parent: ctk.CTkFrame) -> None:
        card = Card(parent, "1. Plik z danymi")
        card.grid(row=0, column=0, sticky="ew")
        self.drop_zone = ctk.CTkFrame(
            card,
            fg_color=theme.ACCENT_SOFT,
            corner_radius=10,
            border_width=2,
            border_color=theme.BORDER,
        )
        self.drop_zone.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 16))
        self.drop_zone.grid_columnconfigure(1, weight=1)
        self.file_icon = ctk.CTkLabel(
            self.drop_zone,
            text="⇩",
            width=44,
            height=44,
            corner_radius=22,
            fg_color=theme.SURFACE,
            text_color=theme.ACCENT,
            font=theme.font(20, "bold"),
        )
        self.file_icon.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=14)
        hint = "Przeciągnij tutaj plik XLSX lub CSV" if self.dnd else "Wybierz plik XLSX lub CSV"
        self.file_title = ctk.CTkLabel(
            self.drop_zone,
            text=hint,
            font=theme.font(14, "bold"),
            text_color=theme.TEXT,
            anchor="w",
            height=20,
        )
        self.file_title.grid(row=0, column=1, sticky="sw", pady=(14, 0))
        self.file_details = ctk.CTkLabel(
            self.drop_zone,
            text="Obsługiwane: .xlsx, .xls, .ods, .csv (UTF-8 lub Windows-1250)",
            font=theme.font(12),
            text_color=theme.MUTED,
            anchor="w",
            height=18,
        )
        self.file_details.grid(row=1, column=1, sticky="nw", pady=(0, 14))
        self.open_button = keyboard_button(
            ctk.CTkButton(
                self.drop_zone,
                text="Wybierz plik…",
                command=self.choose_file,
                height=36,
                width=132,
                font=theme.font(13, "bold"),
                fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER,
                corner_radius=8,
            )
        )
        self.open_button.grid(row=0, column=2, rowspan=2, padx=16)
        if self.dnd:
            for widget in (self, self.drop_zone):  # the whole window accepts dropped files
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

    def _build_columns_card(self, parent: ctk.CTkFrame) -> None:
        card = Card(parent, "2. Kolumny i reguły")
        card.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        card.grid_rowconfigure(1, weight=1)
        actions = ctk.CTkFrame(card.header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        self.rules_label = ctk.CTkLabel(
            actions, text="", font=theme.font(12), text_color=theme.MUTED
        )
        self.rules_label.grid(row=0, column=0, padx=(0, 10))
        self.load_rules_button = self._secondary_button(
            actions, "Wczytaj reguły…", self.choose_rules
        )
        self.load_rules_button.grid(row=0, column=1, padx=(0, 8))
        self.save_rules_button = self._secondary_button(actions, "Zapisz reguły…", self.save_rules)
        self.save_rules_button.grid(row=0, column=2)
        self.table = ColumnTable(card)
        self.table.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 14))

    def _build_settings_card(self, parent: ctk.CTkFrame) -> None:
        card = Card(parent, "3. Wynik")
        card.grid(row=0, column=0, sticky="ew")
        form = ctk.CTkFrame(card, fg_color="transparent")
        form.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        form.grid_columnconfigure(0, weight=1)

        self._caption(form, "Folder na wyniki").grid(row=0, column=0, sticky="w")
        folder_row = ctk.CTkFrame(form, fg_color="transparent")
        folder_row.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        folder_row.grid_columnconfigure(0, weight=1)
        self.output_dir = ctk.StringVar()
        ctk.CTkEntry(
            folder_row,
            textvariable=self.output_dir,
            height=34,
            font=theme.font(12),
            border_color=theme.BORDER,
            fg_color=theme.SURFACE_ALT,
            placeholder_text="obok pliku, folder „wynik”",
        ).grid(row=0, column=0, sticky="ew")
        self._secondary_button(folder_row, "…", self.choose_output_dir, width=40).grid(
            row=0, column=1, padx=(8, 0)
        )

        self._caption(form, "Format plików wynikowych").grid(row=2, column=0, sticky="w")
        self.format_switch = _segmented(form, list(FORMATS), None)
        self.format_switch.set("Jak wejście")
        self.format_switch.grid(row=3, column=0, sticky="ew", pady=(4, 10))
        keyboard_segmented(self.format_switch, lambda _value: None)

        self._caption(form, "Podobne rekordy (literówki, wielkość liter) wg kolumny").grid(
            row=4, column=0, sticky="w"
        )
        self.key_menu = ctk.CTkOptionMenu(
            form,
            values=[NO_KEY],
            height=32,
            font=theme.font(12),
            dropdown_font=theme.font(12),
            fg_color=theme.SURFACE_ALT,
            text_color=theme.TEXT,
            button_color=theme.ACCENT_SOFT,
            button_hover_color=theme.BORDER,
        )
        self.key_menu.grid(row=5, column=0, sticky="ew", pady=(4, 10))
        keyboard_option_menu(self.key_menu, lambda _value: None)

        options = ctk.CTkFrame(form, fg_color="transparent")
        options.grid(row=6, column=0, sticky="ew")
        self.remove_duplicates = self._checkbox(options, "Usuń duplikaty wierszy", True)
        self.remove_duplicates.grid(row=0, column=0, sticky="w", padx=(0, 18))
        self.make_report = self._checkbox(options, "Raport HTML", True)
        self.make_report.grid(row=0, column=1, sticky="w")

        self.run_button = keyboard_button(
            ctk.CTkButton(
                card,
                text="Sprawdź i wyczyść",
                command=self.start_check,
                height=44,
                font=theme.font(15, "bold"),
                fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER,
                corner_radius=10,
            )
        )
        self.run_button.grid(row=2, column=0, sticky="ew", padx=18)
        self.progress = ctk.CTkProgressBar(
            card, height=8, corner_radius=4, progress_color=theme.ACCENT, fg_color=theme.BORDER
        )
        self.progress.set(0)
        self.progress.grid(row=3, column=0, sticky="ew", padx=18, pady=(12, 2))
        self.progress_label = ctk.CTkLabel(
            card,
            text="Wybierz plik, aby zacząć.",
            font=theme.font(12),
            text_color=theme.MUTED,
            anchor="w",
        )
        self.progress_label.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 10))

    def _build_results_card(self, parent: ctk.CTkFrame) -> None:
        card = Card(parent, "Podsumowanie")
        card.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        tiles = ctk.CTkFrame(card, fg_color="transparent")
        tiles.grid(row=1, column=0, sticky="ew", padx=14)
        tiles.grid_columnconfigure((0, 1, 2), weight=1, uniform="tile")
        specs = (
            ("rows", "Wiersze", theme.NEUTRAL),
            ("valid", "Poprawne", theme.OK),
            ("fixed", "Poprawione", theme.FIX),
            ("rejected", "Odrzucone", theme.BAD),
            ("duplicates", "Duplikaty", theme.WARN),
            ("time", "Czas", theme.ACCENT),
        )
        self.tiles: dict[str, StatTile] = {}
        for index, (key, caption, color) in enumerate(specs):
            tile = StatTile(tiles, caption, color)
            tile.grid(row=index // 3, column=index % 3, sticky="ew", padx=3, pady=3)
            self.tiles[key] = tile
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=17, pady=(8, 16))
        buttons.grid_columnconfigure((0, 1, 2), weight=1, uniform="button")
        self.report_button = self._secondary_button(buttons, "Otwórz raport", self.open_report)
        self.output_button = self._secondary_button(buttons, "Otwórz wynik", self.open_output)
        self.folder_button = self._secondary_button(buttons, "Pokaż folder", self.show_folder)
        for column, button in enumerate(
            (self.report_button, self.output_button, self.folder_button)
        ):
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0))

    def _build_status_bar(self) -> None:
        dnd = "przeciągnij plik do okna · " if self.dnd else ""
        text = (
            f"Skróty: Ctrl+O plik · Ctrl+Enter sprawdź · Ctrl+R raport · Ctrl+L reguły · "
            f"Ctrl+T motyw · Esc przerwij · {dnd}Tab przechodzi między polami"
        )
        bar = ctk.CTkFrame(self, fg_color="transparent", height=28)
        bar.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 8))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text=text, font=theme.font(11), text_color=theme.MUTED, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(
            bar, text=f"wersja {__version__}", font=theme.font(11), text_color=theme.MUTED
        ).grid(row=0, column=1, sticky="e")

    def _secondary_button(
        self, parent: tkinter.Misc, text: str, command: Callable[[], None], width: int = 120
    ) -> ctk.CTkButton:
        return keyboard_button(
            ctk.CTkButton(
                parent,
                text=text,
                command=command,
                width=width,
                height=34,
                font=theme.font(12),
                fg_color=theme.SURFACE,
                hover_color=theme.ACCENT_SOFT,
                text_color=theme.TEXT,
                text_color_disabled=theme.MUTED,
                border_width=1,
                border_color=theme.BORDER,
                corner_radius=8,
            )
        )

    def _checkbox(self, parent: tkinter.Misc, text: str, value: bool) -> ctk.CTkCheckBox:
        box = ctk.CTkCheckBox(
            parent,
            text=text,
            font=theme.font(12),
            text_color=theme.TEXT,
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=5,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.NEUTRAL,
            border_width=2,
        )
        if value:
            box.select()
        return keyboard_checkbox(box)

    def _caption(self, parent: tkinter.Misc, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            font=theme.font(12, "bold"),
            text_color=theme.MUTED,
            anchor="w",
            height=18,
        )

    def _bind_shortcuts(self) -> None:
        shortcuts = {
            "<Control-o>": self.choose_file,
            "<Control-Return>": self.start_check,
            "<F5>": self.start_check,
            "<Control-r>": self.open_report,
            "<Control-l>": self.choose_rules,
            "<Control-s>": self.save_rules,
            "<Control-t>": self.toggle_theme,
            "<Escape>": self.cancel_check,
        }
        for sequence, action in shortcuts.items():
            self.bind_all(sequence, lambda _event, action=action: action() or "break")

    # --- actions -----------------------------------------------------------------------------

    def choose_file(self) -> None:
        if self.busy:
            return
        name = filedialog.askopenfilename(
            parent=self, title="Wybierz plik do sprawdzenia", filetypes=FILE_TYPES
        )
        if name:
            self.open_file(Path(name))

    def _on_drop(self, event: tkinter.Event) -> str:
        paths = self.tk.splitlist(event.data)
        if paths and not self.busy:
            self.open_file(Path(paths[0]))
        return "copy"

    def open_file(self, path: Path) -> None:
        self.file = path
        self.result = None
        self._show_result(None)
        if not self.output_dir.get():
            self.output_dir.set(str(path.resolve().parent / "wynik"))
        self._start_task(
            "Wczytywanie pliku…", lambda: analyze(path, rules=self.loaded_rules), self._file_loaded
        )

    def _file_loaded(self, analysis: Analysis) -> None:
        self.analysis = analysis
        info = analysis.info
        rows = info.estimated_rows
        size = f"ok. {num(rows)} wierszy" if rows else ""
        details = " · ".join(filter(None, [info.description, size, f"{len(info.headers)} kolumn"]))
        self.file_title.configure(text=info.path.name)
        self.file_details.configure(text=details)
        self.file_icon.configure(text="✓", fg_color=theme.OK, text_color="#FFFFFF")
        self.drop_zone.configure(border_color=theme.OK)
        self.open_button.configure(text="Zmień plik…")
        rules = list(analysis.rules.columns.values())
        self.table.show(rules, analysis.examples, analysis.detected_by)
        text_columns = [rule.name for rule in rules if rule.type is ColumnType.TEXT]
        self.key_menu.configure(values=[NO_KEY, *text_columns])
        self.key_menu.set(analysis.rules.similarity_key or NO_KEY)
        if analysis.rules.remove_duplicates:
            self.remove_duplicates.select()
        else:
            self.remove_duplicates.deselect()
        self._set_progress(0, "Sprawdź typy kolumn i kliknij „Sprawdź i wyczyść”.")
        for warning in analysis.warnings:
            log.info("Ostrzeżenie: %s", warning)

    def choose_rules(self) -> None:
        if self.busy:
            return
        name = filedialog.askopenfilename(
            parent=self, title="Wczytaj plik reguł", filetypes=[("Reguły JSON", "*.json")]
        )
        if name:
            self._load_rules_file(Path(name))

    def _load_rules_file(self, path: Path) -> None:
        try:
            self.loaded_rules = load_rules(path)
        except WalidatorError as error:
            messagebox.showerror("Nie można wczytać reguł", str(error), parent=self)
            return
        self.rules_name = path.name
        self.rules_label.configure(text=f"reguły: {path.name}")
        if self.file:
            self.open_file(self.file)

    def save_rules(self) -> None:
        rules = self._rules_from_form()
        if rules is None or self.busy:
            return
        name = filedialog.asksaveasfilename(
            parent=self,
            title="Zapisz reguły",
            defaultextension=".json",
            initialfile=f"reguly_{self.file.stem if self.file else 'arkusza'}.json",
            filetypes=[("Reguły JSON", "*.json")],
        )
        if not name:
            return
        try:
            save_rules(rules, name)
        except OSError as error:
            messagebox.showerror(
                "Nie można zapisać reguł", f"{name}\n{error.strerror}", parent=self
            )
            return
        self._set_progress(None, f"Zapisano reguły: {Path(name).name}")

    def _rules_from_form(self) -> RuleSet | None:
        if self.analysis is None:
            return None
        key = self.key_menu.get()
        return RuleSet(
            columns={rule.name: rule for rule in self.table.current_rules()},
            similarity_key=None if key == NO_KEY else key,
            remove_duplicates=bool(self.remove_duplicates.get()),
            description=self.analysis.rules.description,
        )

    def choose_output_dir(self) -> None:
        folder = filedialog.askdirectory(
            parent=self, title="Folder na wyniki", initialdir=self.output_dir.get() or None
        )
        if folder:
            self.output_dir.set(folder)

    def start_check(self) -> None:
        rules = self._rules_from_form()
        if self.busy or rules is None or self.file is None:
            return
        folder = Path(self.output_dir.get().strip() or self.file.resolve().parent / "wynik")
        options = RunOptions(
            output_dir=folder,
            output_format=FORMATS[self.format_switch.get()],
            sheet=self.analysis.info.sheet if self.analysis else None,
            write_report=bool(self.make_report.get()),
            rules_source=self.rules_name,
        )
        self.cancel.clear()
        path = self.file

        def progress(fraction: float | None, rows: int) -> None:
            self.events.put(("progress", (fraction, rows)))

        self._start_task(
            "Sprawdzanie…",
            lambda: run_check(path, rules, options, progress, self.cancel),
            self._check_finished,
        )

    def _check_finished(self, result: RunResult) -> None:
        self.result = result
        self._show_result(result)
        self.progress.configure(progress_color=theme.OK)
        self._set_progress(1, f"Gotowe: {num(result.total)} wierszy w {seconds(result.elapsed)}.")

    def cancel_check(self) -> None:
        if self.busy:
            self.cancel.set()
            self._set_progress(None, "Przerywanie…")

    def open_report(self) -> None:
        if self.result and self.result.outputs.report:
            _open_path(self.result.outputs.report)

    def open_output(self) -> None:
        if self.result:
            _open_path(self.result.outputs.clean)

    def show_folder(self) -> None:
        if self.result:
            subprocess.Popen(["explorer", "/select,", str(self.result.outputs.clean)])

    def toggle_theme(self) -> None:
        self._set_theme("Jasny" if ctk.get_appearance_mode() == "Dark" else "Ciemny")

    def _set_theme(self, name: str) -> None:
        ctk.set_appearance_mode(THEMES[name])
        self.theme_switch.set(name)

    # --- background work ---------------------------------------------------------------------

    def _start_task(
        self, message: str, work: Callable[[], Any], done: Callable[[Any], None]
    ) -> None:
        self.busy = True
        self._refresh_buttons()
        self.progress.configure(mode="indeterminate", progress_color=theme.ACCENT)
        self.progress.start()
        self.progress_label.configure(text=message)
        future = self.executor.submit(work)
        future.add_done_callback(lambda finished: self.events.put(("done", (finished, done))))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    fraction, rows = payload
                    self._set_progress(fraction, f"Sprawdzono {num(rows)} wierszy…")
                else:
                    self._finish_task(*payload)
        except queue.Empty:
            pass
        self.after(POLL_MS, self._poll_events)

    def _finish_task(self, future: Future[Any], done: Callable[[Any], None]) -> None:
        self.busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        try:
            value = future.result()
        except CancelledError:
            self._set_progress(0, "Przerwano. Pliki częściowe zostały usunięte.")
        except WalidatorError as error:
            self._set_progress(0, "Nie udało się – szczegóły w komunikacie.")
            messagebox.showerror(APP_NAME, str(error), parent=self)
        except Exception:
            log.exception("Nieoczekiwany błąd w zadaniu w tle")
            self._set_progress(0, "Wystąpił nieoczekiwany błąd.")
            messagebox.showerror(APP_NAME, _unexpected_message(), parent=self)
        else:
            done(value)
        self._refresh_buttons()

    def _set_progress(self, fraction: float | None, text: str) -> None:
        if fraction is not None and self.progress.cget("mode") == "determinate":
            self.progress.set(fraction)
        elif fraction is not None:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(fraction)
        self.progress_label.configure(text=text)

    def _show_result(self, result: RunResult | None) -> None:
        values = (
            {
                "rows": num(result.total),
                "valid": num(result.unchanged),
                "fixed": num(result.fixed),
                "rejected": num(result.rejected),
                "duplicates": num(result.duplicates),
                "time": seconds(result.elapsed),
            }
            if result
            else dict.fromkeys(self.tiles, "–")
        )
        for key, tile in self.tiles.items():
            tile.set(values[key])
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        def state(enabled: bool) -> str:
            return "normal" if enabled else "disabled"

        ready = self.analysis is not None and not self.busy
        has_result = self.result is not None and not self.busy
        self.run_button.configure(state=state(ready))
        self.save_rules_button.configure(state=state(ready))
        self.load_rules_button.configure(state=state(not self.busy))
        self.open_button.configure(state=state(not self.busy))
        self.report_button.configure(
            state=state(has_result and bool(self.result and self.result.outputs.report))
        )
        self.output_button.configure(state=state(has_result))
        self.folder_button.configure(state=state(has_result))

    def report_callback_exception(
        self, exc: type[BaseException], value: BaseException, traceback: Any
    ) -> None:
        log.error("Błąd w oknie programu", exc_info=(exc, value, traceback))
        messagebox.showerror(APP_NAME, _unexpected_message(), parent=self)

    def _close(self) -> None:
        self.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def _segmented(
    parent: tkinter.Misc, values: list[str], command: Callable[[str], None] | None
) -> ctk.CTkSegmentedButton:
    return ctk.CTkSegmentedButton(
        parent,
        values=values,
        command=command,
        font=theme.font(12),
        height=32,
        fg_color=theme.SEGMENT_TRACK,
        unselected_color=theme.SEGMENT_TRACK,
        unselected_hover_color=theme.SEGMENT_HOVER,
        selected_color=theme.SEGMENT_SELECTED,
        selected_hover_color=theme.SEGMENT_SELECTED,
        text_color=theme.TEXT,
        corner_radius=8,
    )


def _unexpected_message() -> str:
    return (
        "Wystąpił nieoczekiwany błąd programu. Twoje pliki nie zostały zmienione.\n\n"
        f"Szczegóły techniczne zapisano w pliku:\n{LOG_FILE}"
    )


def _open_path(path: Path) -> None:
    try:
        os.startfile(path)
    except OSError as error:
        messagebox.showerror(APP_NAME, f"Nie można otworzyć pliku {path.name}.\n{error.strerror}")


def _enable_drag_and_drop(window: ctk.CTk) -> bool:
    if not DND_AVAILABLE:
        return False
    try:
        TkinterDnD._require(window)
    except (RuntimeError, tkinter.TclError):
        log.warning("Przeciąganie plików niedostępne", exc_info=True)
        return False
    return True


def _set_icon(window: ctk.CTk) -> None:
    icon = Path(__file__).parent / "ikona.ico"  # also inside the .exe (added by the build)
    if icon.is_file():
        window.after(250, lambda: window.iconbitmap(str(icon)))  # CTk sets its own icon first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="walidator-gui", description=f"{APP_NAME} – okno programu"
    )
    parser.add_argument("plik", nargs="?", type=Path, help="plik do otwarcia od razu")
    parser.add_argument("--reguly", type=Path, help="plik reguł JSON do wczytania")
    parser.add_argument("--motyw", choices=("jasny", "ciemny", "systemowy"), default="jasny")
    args = parser.parse_args(argv)
    setup_logging()
    ctk.set_appearance_mode({"jasny": "light", "ciemny": "dark", "systemowy": "system"}[args.motyw])
    ctk.set_default_color_theme("blue")
    app = App(args.plik, args.reguly)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
