"""Package metadata: the window entry point, its data files and dependency pins."""

import sys
import tomllib

import pytest

from .conftest import ROOT

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_window_icon_is_package_data() -> None:
    package_data = PYPROJECT["tool"]["setuptools"]["package-data"]
    assert "ikona.ico" in package_data["walidator.gui"]
    assert (ROOT / "src" / "walidator" / "gui" / "ikona.ico").is_file()


def test_gui_dependencies_are_pinned_to_tested_major_versions() -> None:
    gui = PYPROJECT["project"]["optional-dependencies"]["gui"]
    assert "customtkinter>=6,<7" in gui
    assert any(item.startswith("tkinterdnd2>=") and ",<" in item for item in gui)


def test_window_entry_point_explains_missing_gui_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from walidator import gui

    assert PYPROJECT["project"]["gui-scripts"]["walidator-gui"] == "walidator.gui:main"
    shown: list[str] = []
    monkeypatch.delitem(sys.modules, "walidator.gui.app", raising=False)
    monkeypatch.setitem(sys.modules, "customtkinter", None)
    monkeypatch.setattr(gui, "_show_error", shown.append)
    assert gui.main([]) == 1
    assert 'pip install -e ".[gui]"' in shown[0]
    assert 'pip install -e ".[gui]"' in capsys.readouterr().err
