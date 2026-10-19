"""
Produktordner: die Sammlung der Herstellerdateien (.knxprod), aus der der
eigene Produktkatalog entsteht.

Standard ist Bibliothek/Produkte KNX (utils/workspace), bei älteren
Installationen ohne Bibliothek <Arbeitsverzeichnis>/Produkte KNX; der
ETS-Import legt die Produktdaten dort ab; in den Einstellungen
"products_folder" änderbar. Liegt das Arbeitsverzeichnis in einer Cloud
(Dropbox), haben alle Rechner dieselbe Sammlung.

Neue oder geänderte Dateien legt man einfach in den Ordner; die
Produktauswahl meldet sie (pending_files) und liest sie auf Klick ein.
Welche Dateien eingelesen sind, steht in %APPDATA%/KNiX Arranger/
product_folder_index.json (relativer Pfad -> Grösse, Änderungszeit,
Anzahl Produkte). Dateien, die über die Produktauswahl importiert werden
(Datei, Ziehen, Strg+V), legt add_to_folder zusätzlich in den Ordner.
"""
from __future__ import annotations

import json
import logging
import os
import shutil

from .knxprod_catalog_service import READER_VERSION

logger = logging.getLogger("knix_arranger.product_folder")

FOLDER_NAME = "Produkte KNX"
SETTING = "products_folder"


def products_folder() -> str:
    """Pfad des Produktordners: eigene Einstellung, sonst Bibliothek/Produkte
    KNX, sonst (ältere Installation) <Arbeitsverzeichnis>/Produkte KNX;
    "" ohne Arbeitsverzeichnis (siehe utils/workspace)."""
    from ..utils.app_settings import get_setting
    from ..utils.workspace import library_subfolder
    folder = get_setting(SETTING, "") or library_subfolder(FOLDER_NAME)
    if folder:
        return folder
    workspace = get_setting("workspace_root_path", "") or ""
    return os.path.join(workspace, FOLDER_NAME) if workspace else ""


def set_products_folder(folder: str) -> None:
    from ..utils.app_settings import load_settings, save_settings
    settings = load_settings()
    settings[SETTING] = folder
    save_settings(settings)


def _index_path() -> str:
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(appdata, "KNiX Arranger", "product_folder_index.json")


def load_index() -> dict:
    try:
        with open(_index_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_index(index: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_index_path()), exist_ok=True)
        with open(_index_path(), "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
    except OSError:
        logger.warning("Produktordner-Index nicht gespeichert.", exc_info=True)


def folder_files(folder: str | None = None) -> list[str]:
    """Alle .knxprod-Dateien des Ordners (inkl. Unterordner), sortiert."""
    folder = products_folder() if folder is None else folder
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(root, name)
                  for root, _dirs, files in os.walk(folder)
                  for name in files if name.lower().endswith(".knxprod"))


def _stamp(path: str) -> dict:
    stat = os.stat(path)
    return {"size": stat.st_size, "mtime": int(stat.st_mtime)}


def _inside(path: str, folder: str) -> bool:
    root = os.path.normcase(os.path.abspath(folder))
    return os.path.normcase(os.path.abspath(path)).startswith(root + os.sep)


def _rel(path: str, folder: str) -> str:
    return os.path.relpath(path, folder).replace("\\", "/")


def pending_files(folder: str | None = None) -> list[str]:
    """Dateien, die noch nicht oder in einer älteren Fassung eingelesen sind."""
    folder = products_folder() if folder is None else folder
    index = load_index().get(os.path.normcase(os.path.abspath(folder)), {}) if folder else {}
    result = []
    for path in folder_files(folder):
        known = index.get(_rel(path, folder))
        try:
            stamp = _stamp(path)
        except OSError:
            continue
        if not known or (known.get("size"), known.get("mtime")) != (
                stamp["size"], stamp["mtime"]):
            result.append(path)
        elif known.get("reader", 1) < READER_VERSION:
            # mit einer älteren Fassung eingelesen (z.B. ohne Objektfunktion)
            result.append(path)
    return result


def outdated_files(folder: str | None = None) -> list[str]:
    """Unveränderte Dateien, die eine ältere Fassung von KNiX eingelesen hat."""
    folder = products_folder() if folder is None else folder
    index = load_index().get(os.path.normcase(os.path.abspath(folder)), {}) if folder else {}
    return [path for path in folder_files(folder)
            if index.get(_rel(path, folder), {}).get("reader", 1) < READER_VERSION
            and _rel(path, folder) in index]


def mark_imported(paths: list[str], products: dict[str, int] | None = None,
                  folder: str | None = None) -> None:
    """Dateien als eingelesen vermerken (nur solche im Produktordner);
    products: Pfad -> Anzahl Produkte."""
    folder = products_folder() if folder is None else folder
    if not folder:
        return
    key = os.path.normcase(os.path.abspath(folder))
    data = load_index()
    index = data.setdefault(key, {})
    for path in paths:
        if not _inside(path, folder):
            continue
        try:
            entry = _stamp(path)
        except OSError:
            continue
        entry["products"] = (products or {}).get(path, 0)
        entry["reader"] = READER_VERSION
        index[_rel(path, folder)] = entry
    _save_index(data)


def add_to_folder(paths: list[str], folder: str | None = None) -> list[str]:
    """Dateien in den Produktordner kopieren, sofern sie nicht schon darin
    liegen; gibt die Pfade im Ordner zurück (bzw. die Originale, wenn es
    keinen Ordner gibt oder das Kopieren scheitert)."""
    folder = products_folder() if folder is None else folder
    if not folder:
        return list(paths)
    result = []
    for path in paths:
        if _inside(path, folder):
            result.append(path)
            continue
        target = os.path.join(folder, os.path.basename(path))
        try:
            os.makedirs(folder, exist_ok=True)
            if not (os.path.exists(target) and _stamp(target)["size"] == os.path.getsize(path)):
                shutil.copy2(path, target)
            result.append(target)
        except OSError:
            logger.warning("Nicht in den Produktordner kopiert: %s", path, exc_info=True)
            result.append(path)
    return result


# Busgeräte mit Applikation: ohne KOs in der Produktauswahl ausgeblendet.
# Infrastruktur ohne Gruppen-KOs (Netzteile, Koppler, Router, Zubehör) bleibt.
_BUS_INFRASTRUCTURE_TYPES = ("DALI-Gateway",)


def is_bus_device(prod) -> bool:
    """Aktor, Sensor oder Gateway mit Applikation (hat KOs, wenn aus der KNXPROD)."""
    category = getattr(prod, "category", "") or ""
    device_type = getattr(prod, "device_type", "") or ""
    return category in ("actor", "sensor") or device_type in _BUS_INFRASTRUCTURE_TYPES


def missing_manufacturers(products) -> dict[str, int]:
    """Hersteller -> Anzahl Busgeräte ohne KOs: dafür fehlt die KNXPROD im
    Produktordner (bzw. ist nicht eingelesen)."""
    result: dict[str, int] = {}
    for prod in products:
        if is_bus_device(prod) and not prod.co_count:
            result[prod.manufacturer] = result.get(prod.manufacturer, 0) + 1
    return dict(sorted(result.items(), key=lambda item: -item[1]))
