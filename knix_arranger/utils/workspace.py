"""
Ordnerstruktur von KNiX Arranger.

    Arbeitsverzeichnis/
    ├── Projekte/<Projekt>/            Projektdatei, Berichte, Revisionen, Sicherungen
    └── Bibliothek/
        ├── Produkte KNX/              Herstellerdateien (.knxprod, product_folder)
        ├── Datenblätter/              herstellerweit, statt je Projekt kopiert
        └── Vorlagen/                  KO-Zuordnungen, GA-Bibliothek, Zeitprogramme
    %APPDATA%/KNiX Arranger/           nur Rechnerbezogenes: Einstellungen, Katalog-
                                       Cache, Lizenz, Logs, zuletzt verwendet

Liegt das Arbeitsverzeichnis in einer Cloud (Dropbox), teilen alle Rechner
Projekte und Bibliothek.

Neue Installationen richten diese Struktur ein (setup_workspace). Ältere
Installationen haben die Projekte direkt im Arbeitsverzeichnis und keine
Bibliothek: ohne die Einstellungen "projects_folder"/"library_folder" gilt
weiter das Arbeitsverzeichnis als Projektordner, Vorlagen bleiben in
%APPDATA%. Bestehendes wird nie automatisch verschoben (Cloud-Ordner); die
Bibliothek lässt sich bewusst einrichten (setup_library), der Vorschlag ist
ein Nachbarordner der Projekte.
"""
from __future__ import annotations

import logging
import os
import shutil

logger = logging.getLogger("knix_arranger.workspace")

PROJECTS = "Projekte"
LIBRARY = "Bibliothek"
PRODUCTS = "Produkte KNX"
DATASHEETS = "Datenblätter"
TEMPLATES = "Vorlagen"

# Vorlagen, die mit der Bibliothek geteilt werden (Dateiname -> bisheriger Ort)
_TEMPLATE_FILES = ("ko_templates.json", "custom_ga_library.json",
                   "time_program_templates.json")


def _get(key: str, default=""):
    from .app_settings import get_setting
    return get_setting(key, default) or default


def _set(**values) -> None:
    from .app_settings import load_settings, save_settings
    settings = load_settings()
    settings.update(values)
    save_settings(settings)


def appdata_dir() -> str:
    """%APPDATA%/KNiX Arranger -- Rechnerbezogenes."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(appdata, "KNiX Arranger")


def workspace_root() -> str:
    return _get("workspace_root_path")


def projects_folder() -> str:
    """Hier entstehen neue Projekte; ältere Installationen: das
    Arbeitsverzeichnis selbst."""
    return _get("projects_folder") or workspace_root()


def library_folder() -> str:
    """Bibliothek ("" = noch nicht eingerichtet)."""
    return _get("library_folder")


def library_subfolder(name: str) -> str:
    library = library_folder()
    return os.path.join(library, name) if library else ""


def templates_folder() -> str:
    """Vorlagen: in der Bibliothek, sonst wie bisher in %APPDATA%."""
    return library_subfolder(TEMPLATES) or appdata_dir()


def template_path(name: str) -> str:
    return os.path.join(templates_folder(), name)


def datasheets_folder() -> str:
    """Datenblätter der Bibliothek ("" ohne Bibliothek: je Projekt)."""
    return library_subfolder(DATASHEETS)


def _make_library(library: str) -> None:
    for name in (PRODUCTS, DATASHEETS, TEMPLATES):
        os.makedirs(os.path.join(library, name), exist_ok=True)


def setup_workspace(root: str) -> None:
    """Neue Installation: Arbeitsverzeichnis mit Projekte/ und Bibliothek/."""
    projects = os.path.join(root, PROJECTS)
    library = os.path.join(root, LIBRARY)
    os.makedirs(projects, exist_ok=True)
    _make_library(library)
    _set(workspace_root_path=root, projects_folder=projects, library_folder=library)
    _copy_templates_into(library)
    migrate_home_dir()


def suggested_library(projects: str | None = None) -> str:
    """Vorschlag für bestehende Installationen: neben dem Projektordner
    (Dropbox/…/Projekte -> Dropbox/…/Bibliothek)."""
    projects = projects or projects_folder()
    if not projects:
        return ""
    return os.path.join(os.path.dirname(os.path.normpath(projects)), LIBRARY)


def legacy_products_folder() -> str:
    """Bisheriger Produktordner (<Arbeitsverzeichnis>/Produkte KNX bzw.
    Einstellung products_folder), "" wenn keiner."""
    folder = _get("products_folder") or (
        os.path.join(workspace_root(), PRODUCTS) if workspace_root() else "")
    return folder if folder and os.path.isdir(folder) else ""


def setup_library(library: str, move_products: bool = True) -> dict:
    """Bibliothek für eine bestehende Installation einrichten: Unterordner
    anlegen, die Herstellerdateien des bisherigen Produktordners hinein
    verschieben (nur Dateien, die dort noch fehlen), die Vorlagen hinein
    kopieren (die bisherigen bleiben als Sicherung). Gibt eine Bilanz
    zurück: {"products": n, "templates": n}."""
    _make_library(library)
    moved = 0
    old = legacy_products_folder()
    target = os.path.join(library, PRODUCTS)
    if move_products and old and os.path.normcase(os.path.abspath(old)) != \
            os.path.normcase(os.path.abspath(target)):
        for root, _dirs, files in os.walk(old):
            for name in files:
                source = os.path.join(root, name)
                destination = os.path.join(target, os.path.relpath(source, old))
                if os.path.exists(destination):
                    continue
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                try:
                    shutil.move(source, destination)
                    moved += 1
                except OSError:
                    logger.warning("Nicht verschoben: %s", source, exc_info=True)
    copied = _copy_templates_into(library)
    from .app_settings import load_settings, save_settings
    settings = load_settings()
    settings["library_folder"] = library
    settings.pop("products_folder", None)    # gilt jetzt die Bibliothek
    save_settings(settings)
    return {"products": moved, "templates": copied}


def _copy_templates_into(library: str) -> int:
    """Vorlagen aus %APPDATA% bzw. ~/.knix_arranger in die Bibliothek
    kopieren, sofern dort noch keine liegen."""
    copied = 0
    for name in _TEMPLATE_FILES:
        target = os.path.join(library, TEMPLATES, name)
        if os.path.exists(target):
            continue
        for source in (os.path.join(appdata_dir(), name), os.path.join(_home_dir(), name)):
            if os.path.exists(source):
                try:
                    shutil.copy2(source, target)
                    copied += 1
                except OSError:
                    logger.warning("Vorlage nicht kopiert: %s", source, exc_info=True)
                break
    return copied


def _home_dir() -> str:
    """Früherer Ablageort einzelner Dateien (zuletzt verwendet, KO-Zuordnung)."""
    return os.path.join(os.path.expanduser("~"), ".knix_arranger")


def migrate_home_dir() -> None:
    """~/.knix_arranger einmalig auflösen: zuletzt verwendete Produkte nach
    %APPDATA%, die KO-Zuordnung zu den Vorlagen. Die alten Dateien bleiben."""
    moves = {"recent_products.json": os.path.join(appdata_dir(), "recent_products.json"),
             "ko_templates.json": template_path("ko_templates.json")}
    for name, target in moves.items():
        source = os.path.join(_home_dir(), name)
        if os.path.exists(source) and not os.path.exists(target):
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
            except OSError:
                logger.warning("Nicht übernommen: %s", source, exc_info=True)
