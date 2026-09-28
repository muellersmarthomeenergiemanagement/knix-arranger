"""
Topologie-Diagramm (FA-212, FA-904): gemeinsamer Aufbau für die Ansicht
"Topologie-Diagramm" (Qt) und den Topologie-Bericht (PDF), damit beide
dieselben Knoten und Beschriftungen zeigen.

Koppler und Spannungsversorgungen erscheinen nur, wenn sie als Gerät
vorhanden sind (siehe models.topology.area_coupler/line_coupler).
"""
from __future__ import annotations
from collections import Counter

from ..models.topology import (
    is_power_supply, area_coupler, line_coupler, line_power_supplies,
    power_supply_address, line_title,
)

TOPOLOGY_TYPE_LABELS = {
    "actor": "Aktor", "sensor": "Sensor", "gateway": "Gateway",
    "coupler": "Koppler", "power_supply": "Spannungsversorgung",
}
TOPOLOGY_TYPE_ORDER = ["Aktor", "Sensor", "Gateway", "Koppler",
                       "Spannungsversorgung", "Sonstiges"]
TOPOLOGY_TYPE_PLURAL = {
    "Aktor": "Aktoren", "Sensor": "Sensoren", "Gateway": "Gateways",
    "Koppler": "Koppler", "Spannungsversorgung": "Spannungsversorgungen",
    "Sonstiges": "Weitere",
}


def device_type_label(device) -> str:
    if is_power_supply(device):
        return "Spannungsversorgung"
    return TOPOLOGY_TYPE_LABELS.get(device.device_type, "Sonstiges")


def area_title(area) -> str:
    title = f"Bereich {area.area_number}"
    if area.name and area.name != title:
        title += f": {area.name}"
    return title


def build_topology_diagram(project, include_empty_lines: bool = True) -> dict:
    """Liefert {"backbone": str, "areas": [{"title": str, "nodes": [...]}]}.
    include_empty_lines=False (Bericht) lässt Linien und Bereiche ohne Geräte weg.

    Knoten: {"kind": "coupler"|"power"|"line", "title": str, "lines": [str],
    "status": "OK"|"Warnung"|"Fehler", "messages": [str]}. Der Backbone
    (z.B. "KNX Backbone (IP)") ist nur bei mehreren Bereichen gesetzt.
    """
    from .cable_length_service import CableLengthService
    validations = {v.line_id: v for v in CableLengthService().validate_project(project)}

    areas = sorted(project.topology.areas, key=lambda a: a.area_number)
    # Leere Bereiche (z.B. Bereich 0 aus dem ETS-Import) zählen nicht als
    # weiterer Bereich; ohne Geräte (Planung vor der Topologie-Erzeugung) alle
    with_devices = [a for a in areas if any(l.devices for l in a.lines)]
    multi_area = len(with_devices or areas) > 1
    if not include_empty_lines:
        areas = with_devices
    result = []
    for area in areas:
        nodes = []
        bk = area_coupler(area) if multi_area else None
        if bk is not None:
            nodes.append({"kind": "coupler", "title": "Bereichskoppler",
                          "lines": [p for p in (bk.physical_address,
                                                bk.product_name or bk.product) if p]})
        sv = area.backbone_power_supply if multi_area else None
        if sv is not None:
            nodes.append({"kind": "power",
                          "title": sv.product_name or sv.product or "Spannungsversorgung",
                          "lines": [p for p in (f"{area.area_number}.0.-", sv.manufacturer) if p]})
        for line in sorted(area.lines, key=lambda l: l.line_number):
            if not line.devices and not include_empty_lines:
                continue
            info = []
            coupler = line_coupler(area, line)
            if coupler is not None:
                info.append(f"Koppler {coupler.physical_address}")
            info += [f"SV {power_supply_address(area, line, d)}"
                     for d in line_power_supplies(line)]
            counts = Counter(device_type_label(d) for d in line.devices
                             if d is not coupler and d is not bk)
            info += [f"{n} {t if n == 1 else TOPOLOGY_TYPE_PLURAL[t]}"
                     for t in TOPOLOGY_TYPE_ORDER
                     if (n := counts.get(t)) and t != "Spannungsversorgung"]
            validation = validations.get(line.id)
            status = validation.status if validation else "OK"
            if status != "OK":
                info.append(f"Leitungslänge: {status}")
            nodes.append({"kind": "line", "title": line_title(area, line), "lines": info,
                          "status": status,
                          "messages": list(validation.messages) if validation else []})
        result.append({"title": area_title(area), "nodes": nodes})

    backbone = ""
    if multi_area:
        media = sorted({a.backbone_type for a in (with_devices or areas) if a.backbone_type})
        backbone = "KNX Backbone" + (f" ({', '.join(media)})" if media else "")
    return {"backbone": backbone, "areas": result}
