"""
GA-Vorlagen-Bibliothek: Speichert benutzerdefinierte GA-Vorlagen projektübergreifend.
Ablageort: config/custom_ga_library.json
"""
from __future__ import annotations

import json
from pathlib import Path

_LIBRARY_PATH = Path(__file__).parent.parent / "config" / "custom_ga_library.json"


def load_library() -> list[dict]:
    """Lädt alle gespeicherten GA-Vorlagen."""
    if not _LIBRARY_PATH.exists():
        return []
    try:
        return json.loads(_LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_library(entries: list[dict]) -> None:
    """Speichert die Bibliothek auf Disk."""
    _LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LIBRARY_PATH.write_text(
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
