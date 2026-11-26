# PyInstaller build: one folder with two programs sharing the same libraries.
#   WalidatorArkuszy.exe - the window (no console)
#   walidator.exe        - the command line
# Build:  .venv\Scripts\pyinstaller packaging\walidator.spec --noconfirm

from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "src" / "walidator" / "gui" / "ikona.ico")
VERSION = str(ROOT / "packaging" / "wersja.txt")
EXCLUDES = ["unittest", "pydoc", "doctest", "pytest", "PIL", "numpy"]


def analysis(script: str) -> Analysis:
    return Analysis(
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT / "src")],
        datas=[(ICON, "walidator/gui")],
        excludes=EXCLUDES,
        noarchive=False,
    )


window = analysis("start_okno.py")
console = analysis("start_cli.py")


def executable(built: Analysis, name: str, windowed: bool) -> EXE:
    return EXE(
        PYZ(built.pure),
        built.scripts,
        exclude_binaries=True,
        name=name,
        icon=ICON,
        version=VERSION,
        console=not windowed,
        upx=False,
    )


coll = COLLECT(
    executable(window, "WalidatorArkuszy", windowed=True),
    executable(console, "walidator", windowed=False),
    window.binaries,
    window.datas,
    console.binaries,
    console.datas,
    name="WalidatorArkuszy",
    upx=False,
)
