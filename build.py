"""
Build-Skript fuer KNX Arranger (Nuitka, NFA-012/NFA-071)
Erstellt ein standalone Windows-Bundle unter dist/KNiX_Arranger/

Nuitka uebersetzt den Python-Code in C und kompiliert ihn zu Maschinencode.
Im Bundle liegen keine .py/.pyc-Dateien des Programms -- der Quellcode ist
nicht lesbar und die Lizenzpruefung nicht mit einer geaenderten Zeile
auszuhebeln (anders als beim frueheren PyInstaller-Build).

Voraussetzungen:
    pip install -r requirements.txt
    C-Compiler: Visual Studio Build Tools (MSVC); auf GitHub Actions vorhanden

Ausfuehren:
    python build.py
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "KNiX_Arranger"
BUILD_DIR = ROOT / "build_nuitka"
ICO_PATH = ROOT / "icon.ico"

# Einzige Versionsquelle: knix_arranger/__init__.py
sys.path.insert(0, str(ROOT))
from knix_arranger import __version__ as _APP_VERSION
# Windows erwartet 4-teilige Version
_parts = _APP_VERSION.split(".")
VERSION = ".".join((_parts + ["0", "0", "0", "0"])[:4])

# Daten-Verzeichnisse die ins Bundle kopiert werden muessen
DATA_DIRS = [
    "knix_arranger/config",
    "knix_arranger/data",
    "knix_arranger/i18n",
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


def check_clean_environment():
    """Warnt/bricht ab, wenn nicht in einer frischen venv gebaut wird.

    Grund: Ein lokaler Build in der globalen/geteilten Python-Umgebung kann
    fremde, fuer andere Projekte installierte Pakete (z.B. numpy) versehentlich
    mitbuendeln. Genau das fuehrte im Release 1.1.5 zu einem Absturz, weil die
    lokale numpy-Installation beschaedigt war. Der GitHub-Actions-Build laeuft
    in einer sauberen Umgebung und ist davon nicht betroffen.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        return

    print("WARNUNG: Kein virtuelles Environment aktiv (globale Python-Umgebung).")
    print("Ein lokaler Build kann hier fremde Pakete aus anderen Projekten")
    print("versehentlich mitbuendeln (siehe Release-1.1.5-Bug mit numpy).")
    print("Empfohlen: python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt")
    print("           und den Build aus dieser venv heraus starten.")
    if "--force" not in sys.argv:
        print("Abbruch. Mit '--force' erzwingen, falls absichtlich gewollt.")
        sys.exit(1)
    print("--force gesetzt, fahre trotzdem fort.")


def _qt_translation(filename: str) -> Path:
    import PySide6
    return Path(PySide6.__file__).parent / "translations" / filename


def check_no_source_in_bundle():
    """Bricht ab, wenn Quellcode des Programms im Bundle gelandet ist."""
    leaked = [p for p in (DIST / "knix_arranger").rglob("*")
              if p.suffix in (".py", ".pyc")]
    if leaked:
        print("FEHLER: Quellcode im Bundle gefunden:")
        for p in leaked[:10]:
            print(f"  {p.relative_to(DIST)}")
        sys.exit(1)


def build():
    print(f"=== KNiX Arranger v{_APP_VERSION} – Nuitka Build ===")

    check_clean_environment()
    ensure_icon()

    # Altes dist-Verzeichnis bereinigen
    if DIST.exists():
        print(f"Loesche altes Build: {DIST}")
        shutil.rmtree(DIST)

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",                        # Ordner statt einzelne EXE (schneller Start)
        "--assume-yes-for-downloads",
        "--msvc=latest",
        "--enable-plugin=pyside6",
        "--include-qt-plugins=sensible,iconengines,imageformats",
        "--windows-console-mode=disable",      # Kein Konsolenfenster
        f"--windows-icon-from-ico={ICO_PATH}",
        f"--output-dir={BUILD_DIR}",
        "--output-filename=KNiX_Arranger.exe",
        "--include-package=knix_arranger",
        *[f"--include-data-dir={ROOT / d}={d}" for d in DATA_DIRS],
        "--nofollow-import-to=pytest,tkinter,numpy",
        # Die generierte MuPDF-Anbindung ist so gross, dass dem C-Compiler der
        # Speicher ausgeht -- Fremdbibliothek, bleibt als Bytecode im Bundle
        "--noinclude-custom-mode=pymupdf:bytecode",
        # Deutsche Standard-Dialoge (main.py laedt qtbase_de) -- Nuitka nimmt
        # Qt-Uebersetzungen von sich aus nur mit QtWebEngine mit
        f"--include-data-files={_qt_translation('qtbase_de.qm')}=PySide6/translations/qtbase_de.qm",
        # Metadaten
        "--company-name=Mueller SmartHome & EnergieManagement",
        "--product-name=KNiX Arranger",
        "--file-description=KNiX Arranger",
        f"--file-version={VERSION}",
        f"--product-version={VERSION}",
        str(ROOT / "run.py"),
    ]

    print("Starte Nuitka (kann 20-40 Minuten dauern)...")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print("FEHLER: Nuitka Build fehlgeschlagen.")
        sys.exit(1)

    # Nuitka legt das Bundle als <skript>.dist ab
    DIST.parent.mkdir(exist_ok=True)
    shutil.move(str(BUILD_DIR / "run.dist"), str(DIST))
    shutil.rmtree(BUILD_DIR, ignore_errors=True)

    check_no_source_in_bundle()

    print(f"\nFertig! Bundle liegt unter: {DIST}")
    print("Zum Weitergeben den gesamten Ordner als ZIP verpacken:")
    print(f"  python release.py  (oder manuell: {DIST})")


if __name__ == "__main__":
    build()
