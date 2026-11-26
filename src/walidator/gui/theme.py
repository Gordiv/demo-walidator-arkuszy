"""Colours and fonts of the desktop window. Every colour is a (light, dark) pair."""

from __future__ import annotations

import customtkinter as ctk

Color = tuple[str, str]

BACKGROUND: Color = ("#EEF1F6", "#14171D")
SURFACE: Color = ("#FFFFFF", "#1D2129")
SURFACE_ALT: Color = ("#F6F8FB", "#232832")
BORDER: Color = ("#DDE2EA", "#2E343F")
TEXT: Color = ("#141A26", "#E9EDF3")
MUTED: Color = ("#5D6878", "#9AA4B2")
ACCENT: Color = ("#3657D6", "#6383FA")
ACCENT_HOVER: Color = ("#2945B4", "#4F70EA")
ACCENT_SOFT: Color = ("#E6ECFC", "#27304A")
SEGMENT_TRACK: Color = ("#E4E8F0", "#2A303B")
SEGMENT_HOVER: Color = ("#D9DEE8", "#333A47")
SEGMENT_SELECTED: Color = ("#FFFFFF", "#434C5E")
FOCUS: Color = ("#F0A91F", "#F5BC4A")
DISABLED_TEXT: Color = ("#F2F4F8", "#7D8796")

OK: Color = ("#1F9D63", "#3CC489")
FIX: Color = ("#3A6FD9", "#6E97F2")
BAD: Color = ("#D64550", "#F2737C")
WARN: Color = ("#C58A19", "#E5AC3D")
NEUTRAL: Color = ("#8C96A5", "#7D8796")

FAMILY = "Segoe UI"
WINDOW_SIZE = (1260, 800)
MIN_SIZE = (1080, 700)


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)
