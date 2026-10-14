"""
Persistenz der zuletzt verwendeten Produkte.

Speichert die letzten MAX_RECENT Produktauswahlen als JSON in
%APPDATA%/KNiX Arranger/recent_products.json, damit der Produkt-Auswahl-Dialog
häufig genutzte Artikel sofort anzeigen kann.
"""
from __future__ import annotations
import json
import logging
import os

logger = logging.getLogger("knix_arranger.recent_products")

MAX_RECENT = 8
# Fester Pfad nur für Tests; sonst %APPDATA%/KNiX Arranger (rechnerbezogen)
_RECENT_FILE: str | None = None


def _recent_file() -> str:
    from ..utils.workspace import appdata_dir
    return _RECENT_FILE or os.path.join(appdata_dir(), "recent_products.json")


def load_recent() -> list[dict]:
    """Lädt die Liste der zuletzt verwendeten Produkte (neueste zuerst)."""
    try:
        if os.path.exists(_recent_file()):
            with open(_recent_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        logger.warning("recent_products: Konnte Datei nicht lesen.", exc_info=True)
    return []


def save_recent(products: list[dict]) -> None:
    """Speichert die aktuelle Recent-Liste (max MAX_RECENT Einträge)."""
    try:
        os.makedirs(os.path.dirname(_recent_file()), exist_ok=True)
        with open(_recent_file(), "w", encoding="utf-8") as f:
            json.dump(products[:MAX_RECENT], f, ensure_ascii=False, indent=2)
    except Exception:
        logger.warning("recent_products: Konnte Datei nicht schreiben.", exc_info=True)


def add_recent(prod: dict) -> None:
    """
    Fügt ein Produkt an den Anfang der Recent-Liste ein.

    Duplikate (gleiche Bestellnummer + Hersteller) werden vorher entfernt.
    """
    key = (prod.get("order_number", ""), prod.get("manufacturer", ""))
    recent = load_recent()
    recent = [p for p in recent
              if (p.get("order_number", ""), p.get("manufacturer", "")) != key]
    recent.insert(0, prod)
    save_recent(recent)
