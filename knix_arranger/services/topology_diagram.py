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


def _power_lines(sv, address: str) -> list[str]:
    """Adresse, dazu das zugewiesene Produkt (Hersteller, Bestellnummer)."""
    product = " ".join(p for p in (sv.manufacturer, sv.order_number or sv.product_name) if p)
    return [address] + ([product] if sv.manufacturer else [])


def build_topology_diagram(project, include_empty_lines: bool = True) -> dict:
    """Liefert {"backbone": str, "backbone_power": Knoten|None,
    "areas": [{"title": str, "main_line": str, "nodes": [...]}]}.
    include_empty_lines=False (Bericht) lässt Linien und Bereiche ohne Geräte weg.

    Knoten: {"kind": "coupler"|"power"|"line", "title": str, "lines": [str],
    "status": "OK"|"Warnung"|"Fehler", "messages": [str]}; Linien zusätzlich
    "power": [Adressen ihrer SV]. Die SVs sitzen dort, wo sie speisen:
    backbone_power an der Bereichslinie (nur bei mehreren Bereichen gesetzt,
    wie backbone, z.B. "Bereichslinie (TP)"), der "power"-Knoten eines
    Bereichs an seiner Hauptlinie (main_line, z.B. "Hauptlinie 1.0", leer
    ohne Hauptlinie), "power" einer Linie in der Linie.
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
        # Speisegerät der Hauptlinie B.0 (auch bei einem Bereich mit
        # mehreren Linien)
        sv = area.backbone_power_supply
        if sv is not None:
            nodes.append({"kind": "power", "title": "SV Hauptlinie",
                          "lines": _power_lines(sv, f"{area.area_number}.0.-")})
        for line in sorted(area.lines, key=lambda l: l.line_number):
            if not line.devices and not include_empty_lines:
                continue
            info = []
            coupler = line_coupler(area, line)
            if coupler is not None:
                info.append(f"Koppler {coupler.physical_address}")
            power = [power_supply_address(area, line, d) for d in line_power_supplies(line)]
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
                          "power": power, "status": status,
                          "messages": list(validation.messages) if validation else []})
        lines = [n for n in nodes if n["kind"] == "line"]
        has_main = bk is not None or sv is not None or len(lines) > 1
        result.append({"title": area_title(area), "nodes": nodes,
                       "main_line": f"Hauptlinie {area.area_number}.0" if has_main else ""})

    backbone, backbone_power = "", None
    if multi_area:
        # Über IP-Hauptlinien geht auch die Bereichslinie über IP
        used = with_devices or areas
        ip = (project.topology.backbone_type == "IP"
              or any(a.backbone_type == "IP" for a in used))
        backbone = f"Bereichslinie ({'IP' if ip else 'TP'})"
        sv = project.topology.backbone_power_supply
        if sv is not None:
            backbone_power = {"kind": "power", "title": "SV Bereichslinie",
                              "lines": _power_lines(sv, "0.0.-")}
    return {"backbone": backbone, "backbone_power": backbone_power, "areas": result}
