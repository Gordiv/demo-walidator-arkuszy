"""Reusable widgets: cards, statistic tiles, the column table and keyboard support."""

from __future__ import annotations

import tkinter
from collections.abc import Callable
from dataclasses import dataclass

import customtkinter as ctk

from walidator.gui import theme
from walidator.model import ColumnRule, ColumnType

TYPE_LABELS = [kind.label for kind in ColumnType]


# --- keyboard support ------------------------------------------------------------------------
# CustomTkinter widgets are drawn on canvases and are skipped by Tab. These helpers put them
# into the Tab order, draw a visible focus ring and map Space/Enter/arrows to their actions.


def _focusable(widget: ctk.CTkBaseClass, on_focus: Callable[[bool], None]) -> None:
    tkinter.Frame.configure(widget, takefocus=1)  # type: ignore[arg-type]
    tkinter.Misc.bind(widget, "<FocusIn>", lambda _event: on_focus(True), add="+")
    tkinter.Misc.bind(widget, "<FocusOut>", lambda _event: on_focus(False), add="+")


def _keys(widget: ctk.CTkBaseClass, keys: tuple[str, ...], action: Callable[[], object]) -> None:
    def handler(_event: tkinter.Event) -> str:
        action()
        return "break"

    for key in keys:
        tkinter.Misc.bind(widget, key, handler)


def keyboard_button(button: ctk.CTkButton) -> ctk.CTkButton:
    normal_width = button.cget("border_width")
    normal_color = button.cget("border_color")

    def ring(on: bool) -> None:
        button.configure(
            border_width=2 if on else normal_width,
            border_color=theme.FOCUS if on else normal_color,
        )

    _focusable(button, ring)
    _keys(
        button,
        ("<space>", "<Return>"),
        lambda: button.invoke() if button.cget("state") == "normal" else None,
    )
    return button


def keyboard_checkbox(box: ctk.CTkCheckBox) -> ctk.CTkCheckBox:
    """The ring colours the frame and the tick, so it is visible on ticked boxes too."""
    normal = box.cget("border_color"), box.cget("fg_color"), box.cget("hover_color")

    def ring(on: bool) -> None:
        border, fill, hover = (theme.FOCUS,) * 3 if on else normal
        box.configure(border_color=border, fg_color=fill, hover_color=hover)

    _focusable(box, ring)
    _keys(box, ("<space>",), box.toggle)
    return box


def keyboard_option_menu(
    menu: ctk.CTkOptionMenu, command: Callable[[str], None]
) -> ctk.CTkOptionMenu:
    """Up/Down arrows change the value; the focus ring is drawn on the menu's button part."""
    normal = menu.cget("button_color")

    def step(delta: int) -> None:
        values = menu.cget("values")
        index = (values.index(menu.get()) + delta) % len(values)
        menu.set(values[index])
        command(values[index])

    _focusable(menu, lambda on: menu.configure(button_color=theme.FOCUS if on else normal))
    _keys(menu, ("<Down>", "<Right>"), lambda: step(1))
    _keys(menu, ("<Up>", "<Left>"), lambda: step(-1))
    return menu


def keyboard_segmented(control: ctk.CTkSegmentedButton, command: Callable[[str], None]) -> None:
    normal = control.cget("fg_color")

    def step(delta: int) -> None:
        values = control.cget("values")
        value = values[(values.index(control.get()) + delta) % len(values)]
        control.set(value)
        command(value)

    _focusable(control, lambda on: control.configure(fg_color=theme.FOCUS if on else normal))
    _keys(control, ("<Right>", "<Down>"), lambda: step(1))
    _keys(control, ("<Left>", "<Up>"), lambda: step(-1))


# --- building blocks -------------------------------------------------------------------------


class Card(ctk.CTkFrame):
    """White rounded panel with an optional title row."""

    def __init__(self, master: tkinter.Misc, title: str | None = None, **kwargs: object) -> None:
        super().__init__(
            master,
            fg_color=theme.SURFACE,
            border_color=theme.BORDER,
            border_width=1,
            corner_radius=12,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        if title:
            self.header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
            self.header.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                self.header, text=title, font=theme.font(15, "bold"), text_color=theme.TEXT
            ).grid(row=0, column=0, sticky="w")


class StatTile(ctk.CTkFrame):
    """A number with a caption and a coloured stripe, used in the summary."""

    def __init__(self, master: tkinter.Misc, caption: str, color: theme.Color) -> None:
        super().__init__(master, fg_color=theme.SURFACE_ALT, corner_radius=10)
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(self, width=4, height=40, corner_radius=2, fg_color=color).grid(
            row=0, column=0, rowspan=2, sticky="ns", padx=(9, 9), pady=11
        )
        ctk.CTkLabel(
            self,
            text=caption.upper(),
            font=theme.font(10, "bold"),
            text_color=theme.MUTED,
            anchor="w",
            height=16,
        ).grid(row=0, column=1, sticky="ew", pady=(10, 0))
        self.value = ctk.CTkLabel(
            self,
            text="–",
            font=theme.font(20, "bold"),
            text_color=theme.TEXT,
            anchor="w",
            height=28,
        )
        self.value.grid(row=1, column=1, sticky="ew", pady=(0, 9))

    def set(self, text: str) -> None:
        self.value.configure(text=text)


# --- column table ----------------------------------------------------------------------------

COLUMN_SPECS = (  # (title, min width, weight)
    ("Kolumna", 200, 3),
    ("Typ danych", 176, 0),
    ("Wymagane", 92, 0),
    ("Unikalne", 92, 0),
    ("Wykryto na podstawie", 160, 1),
)
SCROLLBAR_ALLOWANCE = 18


def _configure_columns(frame: tkinter.Misc) -> None:
    for index, (_title, width, weight) in enumerate(COLUMN_SPECS):
        frame.grid_columnconfigure(index, minsize=width, weight=weight)


@dataclass(slots=True)
class ColumnRow:
    rule: ColumnRule
    type_menu: ctk.CTkOptionMenu
    required: ctk.CTkCheckBox
    unique: ctk.CTkCheckBox


class ColumnTable(ctk.CTkFrame):
    """Detected columns with an editable type and "required"/"unique" switches."""

    def __init__(self, master: tkinter.Misc) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color=theme.SURFACE_ALT, corner_radius=8, height=34)
        header.grid(row=0, column=0, sticky="ew")
        _configure_columns(header)
        header.grid_columnconfigure(len(COLUMN_SPECS), minsize=SCROLLBAR_ALLOWANCE)
        for index, (title, _width, _weight) in enumerate(COLUMN_SPECS):
            anchor = "center" if index in (2, 3) else "w"
            ctk.CTkLabel(
                header,
                text=title.upper(),
                font=theme.font(10, "bold"),
                text_color=theme.MUTED,
                anchor=anchor,
            ).grid(row=0, column=index, sticky="ew", padx=(14 if index == 0 else 6, 6), pady=6)
        self.body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=theme.BORDER,
        )
        self.body.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.body.grid_columnconfigure(0, weight=1)
        self.rows: list[ColumnRow] = []
        self.placeholder = ctk.CTkLabel(
            self.body,
            text="Tu pojawią się kolumny wykryte w pliku.\nMożesz zmienić typ i zaznaczyć reguły.",
            font=theme.font(13),
            text_color=theme.MUTED,
            justify="center",
        )
        self.placeholder.grid(row=0, column=0, pady=60)

    def show(
        self, rules: list[ColumnRule], examples: dict[str, str], sources: dict[str, str]
    ) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.rows = [
            self._add_row(index, rule, examples.get(rule.name, ""), sources.get(rule.name, ""))
            for index, rule in enumerate(rules)
        ]
        self.body._parent_canvas.yview_moveto(0)

    def _add_row(self, index: int, rule: ColumnRule, example: str, source: str) -> ColumnRow:
        row = ctk.CTkFrame(
            self.body, fg_color=theme.SURFACE_ALT if index % 2 else "transparent", corner_radius=8
        )
        row.grid(row=index, column=0, sticky="ew", pady=1)
        _configure_columns(row)

        names = ctk.CTkFrame(row, fg_color="transparent")
        names.grid(row=0, column=0, sticky="ew", padx=(14, 6), pady=6)
        ctk.CTkLabel(
            names,
            text=_shorten(rule.name, 30),
            font=theme.font(13, "bold"),
            text_color=theme.TEXT,
            anchor="w",
            height=18,
        ).pack(fill="x")
        ctk.CTkLabel(
            names,
            text=f"np. {_shorten(example, 34)}" if example else "brak danych",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
            height=16,
        ).pack(fill="x")

        type_menu = ctk.CTkOptionMenu(
            row,
            values=TYPE_LABELS,
            width=168,
            height=30,
            font=theme.font(12),
            dropdown_font=theme.font(12),
            fg_color=theme.SURFACE,
            text_color=theme.TEXT,
            button_color=theme.ACCENT_SOFT,
            button_hover_color=theme.BORDER,
            corner_radius=7,
        )
        type_menu.set(rule.type.label)
        type_menu.grid(row=0, column=1, sticky="w", padx=6)

        required = self._checkbox(row, rule.required, 2)
        unique = self._checkbox(row, rule.unique, 3)
        from_rules = source == "plik reguł"
        ctk.CTkLabel(
            row,
            text=source,
            font=theme.font(11, "bold" if from_rules else "normal"),
            text_color=theme.ACCENT if from_rules else theme.MUTED,
            anchor="w",
        ).grid(row=0, column=4, sticky="ew", padx=6)

        item = ColumnRow(rule, type_menu, required, unique)
        type_menu.configure(command=lambda label, item=item: self._type_changed(item, label))
        keyboard_option_menu(type_menu, lambda label, item=item: self._type_changed(item, label))
        for widget in (type_menu, required, unique):
            tkinter.Misc.bind(
                widget, "<FocusIn>", lambda _e, frame=row: self._scroll_to(frame), add="+"
            )
        return item

    def _checkbox(self, row: ctk.CTkFrame, value: bool, column: int) -> ctk.CTkCheckBox:
        box = ctk.CTkCheckBox(
            row,
            text="",
            width=24,
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=5,
            border_width=2,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.NEUTRAL,
        )
        if value:
            box.select()
        box.grid(row=0, column=column)
        return keyboard_checkbox(box)

    def _type_changed(self, item: ColumnRow, label: str) -> None:
        new_type = ColumnType.from_label(label)
        if new_type is not item.rule.type:
            item.rule = ColumnRule(item.rule.name, new_type)

    def _scroll_to(self, frame: ctk.CTkFrame) -> None:
        """Keeps the focused row visible while moving through the table with Tab."""
        canvas = self.body._parent_canvas
        content_height = max(self.body.winfo_height(), 1)
        top, bottom = frame.winfo_y(), frame.winfo_y() + frame.winfo_height()
        view_top, view_bottom = (fraction * content_height for fraction in canvas.yview())
        if top < view_top:
            canvas.yview_moveto(top / content_height)
        elif bottom > view_bottom:
            canvas.yview_moveto((bottom - (view_bottom - view_top)) / content_height)

    def current_rules(self) -> list[ColumnRule]:
        """Rules as set in the table; extra settings from a rules file are kept."""
        for item in self.rows:
            item.rule.required = bool(item.required.get())
            item.rule.unique = bool(item.unique.get())
        return [item.rule for item in self.rows]


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
