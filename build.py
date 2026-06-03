"""
Build-Skript fuer KNX Arranger (PyInstaller)
Erstellt ein standalone Windows-Bundle unter dist/KNiX_Arranger/

Voraussetzungen:
    pip install pyinstaller PySide6 pillow

Ausfuehren:
    python build.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "KNiX_Arranger"
ICO_PATH = ROOT / "icon.ico"

# Einzige Versionsquelle: knix_arranger/__init__.py
sys.path.insert(0, str(ROOT))
from knix_arranger import __version__ as _APP_VERSION
# Windows erwartet 4-teilige Version
_parts = _APP_VERSION.split(".")
VERSION = ".".join((_parts + ["0", "0", "0", "0"])[:4])

# Daten-Verzeichnisse die ins Bundle kopiert werden muessen
DATA_DIRS = [
    ("knix_arranger/config", "knix_arranger/config"),
]


def ensure_icon():
    if not ICO_PATH.exists():
        print("Erstelle icon.ico aus icon.svg ...")
        result = subprocess.run([sys.executable, str(ROOT / "create_icon.py")])
        if result.returncode != 0 or not ICO_PATH.exists():
            print("FEHLER: Icon-Erstellung fehlgeschlagen.")
            sys.exit(1)
    else:
        print(f"Icon vorhanden: {ICO_PATH}")


def build():
    print(f"=== KNiX Arranger v{_APP_VERSION} – PyInstaller Build ===")

    ensure_icon()

    # Altes dist-Verzeichnis bereinigen
    if DIST.exists():
        print(f"Loesche altes Build: {DIST}")
        shutil.rmtree(DIST)

    # --add-data Argumente fuer Konfigurationsdateien
    add_data = []
    for src, dst in DATA_DIRS:
        src_path = ROOT / src
        if src_path.exists():
            add_data += ["--add-data", f"{src_path}{':' if sys.platform != 'win32' else ';'}{dst}"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",                          # Kein Konsolenfenster
        "--onedir",                            # Ordner statt einzelne EXE (schneller, zuverlaessiger)
        f"--name=KNiX_Arranger",
        f"--icon={ICO_PATH}",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build_tmp'}",
        f"--specpath={ROOT}",
        # Metadaten
        f"--version-file=version_info.txt",    # wird unten erzeugt
        # Imports die PyInstaller nicht automatisch erkennt
        "--hidden-import=knix_arranger",
        "--hidden-import=PySide6.QtSvg",
        "--hidden-import=PySide6.QtPrintSupport",
        "--collect-all=knix_arranger",
        *add_data,
        str(ROOT / "run.py"),
    ]

    # Windows Version-Info-Datei erzeugen
    _write_version_info(ROOT / "version_info.txt")

    print("Starte PyInstaller (kann mehrere Minuten dauern)...")
    result = subprocess.run(cmd, cwd=ROOT)

    # Temporaere Dateien aufraeumen
    tmp = ROOT / "build_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    spec = ROOT / "KNiX_Arranger.spec"
    if spec.exists():
        spec.unlink()
    vi = ROOT / "version_info.txt"
    if vi.exists():
        vi.unlink()

    if result.returncode != 0:
        print("FEHLER: PyInstaller Build fehlgeschlagen.")
        sys.exit(1)

    print(f"\nFertig! Bundle liegt unter: {DIST}")
    print("Zum Weitergeben den gesamten Ordner als ZIP verpacken:")
    print(f"  python release.py  (oder manuell: {DIST})")


def _write_version_info(path: Path):
    """Erzeugt eine Windows-Versionsdatei fuer PyInstaller."""
    parts = (VERSION + ".0.0.0.0").split(".")[:4]
    v = ", ".join(parts)
    path.write_text(f"""
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v}),
    prodvers=({v}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(u'040704B0', [
        StringStruct(u'CompanyName', u'Mueller SmartHome & EnergieManagement'),
        StringStruct(u'FileDescription', u'KNiX Arranger'),
        StringStruct(u'FileVersion', u'{_APP_VERSION}'),
        StringStruct(u'InternalName', u'KNiX_Arranger'),
        StringStruct(u'ProductName', u'KNiX Arranger'),
        StringStruct(u'ProductVersion', u'{_APP_VERSION}'),
      ])
    ]),
    VarFileInfo([VarStruct(u'Translation', [0x0407, 1200])])
  ]
)
""", encoding="utf-8")


if __name__ == "__main__":
    build()
