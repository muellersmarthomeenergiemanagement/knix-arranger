"""
KO-Namen je Produkt aus importierten ETS-Projekten (FA-1411d).

Manche Produktdateien tragen für die KOs nur Platzhalter («Object 27»,
«GO0002», «{{0:GO}}» -- die Texte hängen in der ETS von den Parametern ab),
z.B. Feller EDIZIOdue colore im Katalog. Ein importiertes ETS-Projekt mit
demselben Produkt kennt die echten Texte, Flags und DPTs («Taste 1, links»,
K S Ü). Diese werden je Produkt gemerkt (Bibliothek/Vorlagen/ko_names.json)
und bei allen Geräten dieses Produkts eingesetzt, deren KOs nur Platzhalter
tragen -- sofort und bei jeder späteren Produktzuweisung.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger("knix_arranger.ko_names")

# Fester Pfad nur für Tests (conftest); sonst Bibliothek/Vorlagen bzw. %APPDATA%
_NAMES_FILE: str | None = None

_GENERIC = re.compile(r"^\s*(?:object|objekt|go|ko|obj)\s*_?\d+\s*$", re.IGNORECASE)


def _names_file() -> str:
    from ..utils.workspace import template_path
    return _NAMES_FILE or template_path("ko_names.json")


def _product(device) -> str:
    from ..utils.manufacturers import product_key
    if not device.order_number:
        return ""
    return "|".join(str(p) for p in product_key(device.manufacturer, device.order_number,
                                                device.product_name))


def is_generic(co) -> bool:
    """KO ohne sprechenden Text: «Object 27», «GO0002», «{{0:GO}}»."""
    texts = [t for t in (co.name or "", co.object_function or "") if t.strip()]
    return not texts or all(_GENERIC.match(t) or "{{" in t for t in texts)


def load() -> dict:
    try:
        if os.path.exists(_names_file()):
            with open(_names_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("ko_names: Konnte Datei nicht lesen.", exc_info=True)
    return {}


def _save(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_names_file()), exist_ok=True)
        with open(_names_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        logger.warning("ko_names: Konnte Datei nicht schreiben.", exc_info=True)


def learn_from_project(source) -> dict[str, int]:
    """Echte KO-Texte aller Geräte eines (importierten) Projekts je Produkt
    merken. Gibt Produkt -> Anzahl gelernter KOs zurück."""
    data = load()
    learned: dict[str, int] = {}
    for area in source.topology.areas:
        for line in area.lines:
            for device in line.devices:
                product = _product(device)
                if not product:
                    continue
                entry = data.setdefault(product, {})
                for co in device.communication_objects:
                    if is_generic(co):
                        continue
                    key = str(co.object_number)
                    if key not in entry:
                        learned[product] = learned.get(product, 0) + 1
                    entry[key] = {"name": co.name, "function": co.object_function,
                                  "flags": co.flags, "dpt": co.data_type}
    _save(data)
    return learned


def apply_to_device(device, data: dict | None = None) -> int:
    """Platzhalter-KOs des Geräts mit den gemerkten Texten seines Produkts
    ersetzen (Flags/DPT nur, wo das Produkt keine hat). Anzahl ersetzter."""
    data = load() if data is None else data
    entry = data.get(_product(device)) if device.order_number else None
    if not entry:
        return 0
    n = 0
    for co in device.communication_objects:
        known = entry.get(str(co.object_number))
        if not known or not is_generic(co):
            continue
        co.name = known.get("name") or co.name
        co.object_function = known.get("function") or co.object_function
        if known.get("flags"):
            # Platzhalter tragen oft alle Flags (Griesser JAX-9): ETS gilt
            co.flags = known["flags"]
        if known.get("dpt") and not co.data_type:
            co.data_type = known["dpt"]
        n += 1
    return n


def apply_to_project(project) -> int:
    """Gemerkte Texte bei allen Geräten des Projekts einsetzen."""
    data = load()
    return sum(apply_to_device(device, data) for area in project.topology.areas
               for line in area.lines for device in line.devices)
