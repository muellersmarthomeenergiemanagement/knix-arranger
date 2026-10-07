"""
Programmeinstellungen (app_settings.json) im Benutzerverzeichnis (NFA-134).

Ablage: %APPDATA%/KNiX Arranger/app_settings.json, im selben Ordner wie
Lizenz, Firmenprofil und Logdateien. Bis Version 1.1.31 lag die Datei in
%APPDATA%/KNiXArranger (ohne Leerzeichen); sie wird beim ersten Zugriff
in den neuen Ordner kopiert. Die alte bleibt liegen: eine ältere Version
(z.B. nach einem Zurückgehen) liest nur dort -- verschoben fand sie das
Arbeitsverzeichnis nicht mehr.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("knix_arranger.app_settings")

_FILE_NAME = "app_settings.json"


def _base_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home()))
    return Path.home() / ".config"


def settings_path() -> Path:
    """Pfad der Einstellungsdatei; übernimmt eine Datei aus dem alten Ordner."""
    path = _base_dir() / "KNiX Arranger" / _FILE_NAME
    old = _base_dir() / "KNiXArranger" / _FILE_NAME
    if not path.exists() and old.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(old), str(path))
            logger.info("Einstellungen übernommen nach %s", path)
        except OSError as exc:
            logger.warning("Einstellungen nicht übernommen: %s", exc)
            return old
    return path


def load_settings() -> dict:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def get_setting(key: str, default=None):
    return load_settings().get(key, default)
