"""
GA-Vorlagen-Bibliothek: Speichert benutzerdefinierte GA-Vorlagen projektübergreifend.
Ablageort: %APPDATA%/KNiX Arranger/custom_ga_library.json -- nicht im
Installationsordner, der bei der installierten App schreibgeschützt ist und
bei Updates ersetzt wird.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Früherer Ablageort im Programmordner; wird beim ersten Laden übernommen.
_LEGACY_PATH = Path(__file__).parent.parent / "config" / "custom_ga_library.json"


def _library_path() -> Path:
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    return Path(appdata) / "KNiX Arranger" / "custom_ga_library.json"


def load_library() -> list[dict]:
    """Lädt alle gespeicherten GA-Vorlagen."""
    path = _library_path()
    if not path.exists():
        path = _LEGACY_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_library(entries: list[dict]) -> None:
    """Speichert die Bibliothek auf Disk."""
    path = _library_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_entry(name: str, ga) -> None:
    """Fügt eine neue Vorlage aus einem GroupAddress-Objekt hinzu."""
    entries = load_library()
    entries.append({
        "name": name,
        "main_group": ga.main_group,
        "middle_group": ga.middle_group,
        "sub_group": ga.sub_group,
        "designation": ga.designation,
        "datapoint_type": ga.datapoint_type,
        "gewerk_code": ga.gewerk_code,
        "function_name": ga.function_name,
        "description": ga.description,
        "central": ga.central,
    })
    save_library(entries)


def remove_entry(index: int) -> None:
    """Entfernt eine Vorlage anhand des Index."""
    entries = load_library()
    if 0 <= index < len(entries):
        entries.pop(index)
        save_library(entries)
