"""
KO-Zuordnung je Produkt merken (Materialliste › «Kanäle und KOs zuordnen…»).

Ist ein Busch-Watchdog Sky 6131/40 einmal zugeordnet (Kanal 1 -> KO 10
«P1: Bewegung (Master)», Aktorstatus -> KO 4 ...), gilt das als Vorlage für
alle gleichen Geräte -- in diesem und in künftigen Projekten. Die KO-
Nummern eines Produkts sind je Applikation fest; bei Tastern mit rund 115
KOs spart das die meiste Handarbeit.

Schlüssel ohne Gerätebezug:
- Sensoren: "Taste/Kanal|Funktion bzw. Rolle", z.B. "Kanal 1|E/A",
  "Kanal 1|#aktorstatus", "Gewerk A 2|P1: Bewegung";
- Aktoren: "Kanal-Nr.|Funktion", z.B. "1|E/A", "1|RM".

Gespeichert als JSON in Bibliothek/Vorlagen/ko_templates.json (ohne
Bibliothek in %APPDATA%/KNiX Arranger, siehe utils/workspace):
{Produktschlüssel: {Schlüssel: KO-Nummer, -1 = nicht verknüpfen}}, dazu
{Produktschlüssel + "#GA-Auswahl": [KO-Nummern ohne eigene GA]} -- welche KOs
eines Sensor-Produkts eigene GAs bekommen (product_sync_dialog).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("knix_arranger.ko_templates")

# Fester Pfad nur für Tests (conftest); sonst Bibliothek/Vorlagen bzw. %APPDATA%
_TEMPLATE_FILE: str | None = None


def _template_file() -> str:
    from ..utils.workspace import template_path
    return _TEMPLATE_FILE or template_path("ko_templates.json")


def _product(device) -> str:
    from ..utils.manufacturers import product_key
    if not device.order_number:
        return ""
    return "|".join(str(p) for p in product_key(device.manufacturer, device.order_number,
                                                device.product_name))


def _load_all() -> dict:
    try:
        if os.path.exists(_template_file()):
            with open(_template_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("ko_templates: Konnte Datei nicht lesen.", exc_info=True)
    return {}


def load_template(device) -> dict[str, int]:
    """Gemerkte Zuordnung für das Produkt des Geräts ({} ohne)."""
    product = _product(device)
    return dict(_load_all().get(product) or {}) if product else {}


def save_template(device, entries: dict[str, int]) -> None:
    """Zuordnung eines Geräts für sein Produkt merken (ergänzt die Vorlage)."""
    product = _product(device)
    if not product or not entries:
        return
    data = _load_all()
    template = dict(data.get(product) or {})
    template.update(entries)
    data[product] = template
    _write_all(data)


_GA_SELECTION = "#GA-Auswahl"


def load_ga_selection(device) -> set[int] | None:
    """Gemerkte Auswahl, welche KOs des Produkts keine eigene GA bekommen
    (excluded_co_numbers); None, wenn noch keine gemerkt ist."""
    product = _product(device)
    entry = _load_all().get(product + _GA_SELECTION) if product else None
    return set(entry) if isinstance(entry, list) else None


def save_ga_selection(device, excluded: set[int]) -> None:
    product = _product(device)
    if not product:
        return
    data = _load_all()
    data[product + _GA_SELECTION] = sorted(excluded)
    _write_all(data)


def _write_all(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_template_file()), exist_ok=True)
        with open(_template_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        logger.warning("ko_templates: Konnte Datei nicht schreiben.", exc_info=True)


def sensor_signature(link) -> str:
    return f"{link.channel}|#{link.role}" if link.role else f"{link.channel}|{link.ga_function}"


def actor_signature(channel: int, function: str) -> str:
    return f"{channel}|{function}"


def actor_proposal(channel, circuit, number: int, template: dict, known: set) -> dict:
    """KO-Vorschlag für einen Aktor-Stromkreis auf Kanal number: die gemerkte
    Zuordnung des Produkts vor dem Vorschlag nach Texten (suggested_co_map)."""
    from .actor_channels import suggested_co_map
    selection = suggested_co_map(channel, circuit)
    for function, _ga in circuit.functions:
        remembered = template.get(actor_signature(number, function))
        if remembered is not None and (remembered < 0 or remembered in known):
            selection[function] = remembered
    return selection


def apply_sensor_template(template: dict[str, int], links: list, known: set[int]) -> dict[str, int]:
    """ga_key -> KO-Nummer aus der Vorlage, nur KOs, die das Gerät hat."""
    result = {}
    for link in links:
        number = template.get(sensor_signature(link))
        if number is not None and (number < 0 or number in known):
            result[link.key] = number
    return result


def sensor_template_entries(links: list, selection: dict[str, int]) -> dict[str, int]:
    return {sensor_signature(link): selection[link.key]
            for link in links if link.key in selection}
