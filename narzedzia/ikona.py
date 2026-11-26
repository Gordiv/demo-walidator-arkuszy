"""Draws the application icon (src/walidator/gui/ikona.ico). Needs Pillow (dev dependency)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

TARGET = Path(__file__).resolve().parent.parent / "src" / "walidator" / "gui" / "ikona.ico"
SIZE = 1024  # drawn large, then scaled down for smooth edges
ACCENT = (54, 87, 214, 255)
GRID = (122, 146, 232, 255)
WHITE = (255, 255, 255, 255)
GREEN = (31, 157, 99, 255)


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    margin = 64
    pen.rounded_rectangle((margin, margin, SIZE - margin, SIZE - margin), radius=200, fill=ACCENT)
    # a faint spreadsheet grid
    for x in (380, 640):
        pen.line((x, 200, x, 824), fill=GRID, width=18)
    for y in (380, 600):
        pen.line((200, y, 824, y), fill=GRID, width=18)
    # a check mark in a green badge
    pen.ellipse((520, 520, 900, 900), fill=GREEN, outline=WHITE, width=34)
    pen.line([(612, 712), (690, 790), (820, 632)], fill=WHITE, width=58, joint="curve")
    return image


def main() -> None:
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    draw().save(TARGET, sizes=sizes)
    print(f"Zapisano {TARGET}")


if __name__ == "__main__":
    main()
