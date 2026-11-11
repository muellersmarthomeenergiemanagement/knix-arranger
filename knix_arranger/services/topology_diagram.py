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
    # weiterer Bereich und erscheinen nicht; ohne Geräte (Planung vor der
    # Topologie-Erzeugung) alle
    with_devices = [a for a in areas if any(l.devices for l in a.lines)]
    multi_area = len(with_devices or areas) > 1
    if with_devices or not include_empty_lines:
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
            # Linie B.0 ist die Hauptlinie selbst (main_line): ohne Geräte
            # kein eigener Kasten
            if not line.devices and (not include_empty_lines or line.line_number == 0):
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


# ── Anordnung (gemeinsam für Ansicht und Bericht) ────────────────────────────
# Je Bereich ein Band: Kopf, Bereichskoppler, darunter die Hauptlinie als
# waagrechte Busleitung, an der SV und Linien nebeneinander hängen (mehr als
# eine Zeile: die Busleitung läuft links weiter zur nächsten Zeile). Mehrere
# Bereiche stehen untereinander an der senkrechten Bereichslinie links.
# Koordinaten je Band ab (0, 0); die Höhe eines Knotens misst der Aufrufer
# (node_h(node, w)), weil Qt und PDF Text verschieden umbrechen.

def layout_topology_diagram(diagram: dict, node_h, node_w: float, max_width: float,
                            head_h: float = 22.0, gap: float = 12.0,
                            label_h: float = 12.0) -> list[dict]:
    """Bänder [{"height": h, "width": w, "items": [...]}]. Elemente:
    {"type": "area", "x", "y", "w", "h", "title"},
    {"type": "node", "x", "y", "w", "h", "node"},
    {"type": "wire", "x1", "y1", "x2", "y2", "bus": bool} (bus: Bereichs-
    oder Hauptlinie, kräftig), {"type": "label", "x", "y", "text"} (y =
    Grundlinie, Farbe der Busleitung). Zwischen den Bändern liegt gap; die
    Bereichslinie läuft durch diese Lücke weiter."""
    backbone = diagram["backbone"]
    bus_x = 5.0                                   # Bereichslinie (senkrecht)
    left = 22.0 if backbone else 8.0              # links: Bereichs-/Weiterführung
    per_row = max(1, int((max_width - left + gap) // (node_w + gap)))
    bands: list[dict] = []

    if backbone:
        items = [{"type": "label", "x": left, "y": label_h - 3, "text": backbone}]
        y = label_h
        sv = diagram.get("backbone_power")
        if sv is not None:
            h = node_h(sv, node_w)
            items.append({"type": "node", "x": left, "y": y + 4, "w": node_w, "h": h,
                          "node": sv})
            stub = y + 4 + min(h / 2, 12)
            items.append({"type": "wire", "x1": bus_x, "y1": stub, "x2": left,
                          "y2": stub, "bus": False})
            y += 4 + h
        items.append({"type": "wire", "x1": bus_x, "y1": label_h - 6, "x2": bus_x,
                      "y2": y + gap, "bus": True})
        bands.append({"height": y, "width": left + node_w, "items": items})

    areas = diagram["areas"]
    for index, area in enumerate(areas):
        items: list[dict] = []
        nodes = list(area["nodes"])
        bk = nodes.pop(0) if nodes and nodes[0]["kind"] == "coupler" else None
        cols = max(1, min(len(nodes), per_row))
        width = max(node_w, cols * (node_w + gap) - gap)
        items.append({"type": "area", "x": left, "y": 0.0, "w": width, "h": head_h,
                      "title": area["title"]})
        if backbone:
            items.append({"type": "wire", "x1": bus_x, "y1": 0.0, "x2": bus_x,
                          "y2": head_h / 2, "bus": True})
            items.append({"type": "wire", "x1": bus_x, "y1": head_h / 2, "x2": left,
                          "y2": head_h / 2, "bus": False})
        y = head_h
        feed_x = left + width / 2                  # Zuleitung zur Hauptlinie
        if bk is not None:
            h = node_h(bk, node_w)
            bx = left + (width - node_w) / 2
            items.append({"type": "wire", "x1": feed_x, "y1": y, "x2": feed_x,
                          "y2": y + gap, "bus": False})
            items.append({"type": "node", "x": bx, "y": y + gap, "w": node_w, "h": h,
                          "node": bk})
            y += gap + h

        if area["main_line"] and nodes:
            rows = [nodes[i:i + per_row] for i in range(0, len(nodes), per_row)]
            label_y = y + gap + label_h - 3
            bar_y = y + gap + label_h + 2
            items.append({"type": "wire", "x1": feed_x, "y1": y, "x2": feed_x,
                          "y2": bar_y, "bus": False})
            items.append({"type": "label", "x": left, "y": label_y,
                          "text": area["main_line"]})
            cont_x = left - 4                      # Weiterführung zur nächsten Zeile
            for r, row in enumerate(rows):
                centers = [left + j * (node_w + gap) + node_w / 2 for j in range(len(row))]
                x1, x2 = min(centers), max(centers)
                if r == 0:
                    x1, x2 = min(x1, feed_x), max(x2, feed_x)
                if len(rows) > 1:
                    x1 = cont_x
                items.append({"type": "wire", "x1": x1, "y1": bar_y, "x2": x2,
                              "y2": bar_y, "bus": True})
                bottom = bar_y
                for j, node in enumerate(row):
                    h = node_h(node, node_w)
                    nx = left + j * (node_w + gap)
                    items.append({"type": "wire", "x1": centers[j], "y1": bar_y,
                                  "x2": centers[j], "y2": bar_y + gap, "bus": False})
                    items.append({"type": "node", "x": nx, "y": bar_y + gap, "w": node_w,
                                  "h": h, "node": node})
                    bottom = max(bottom, bar_y + gap + h)
                if r < len(rows) - 1:
                    next_bar = bottom + gap + 4
                    items.append({"type": "wire", "x1": cont_x, "y1": bar_y, "x2": cont_x,
                                  "y2": next_bar, "bus": True})
                    bar_y = next_bar
                y = bottom
        else:
            # Ohne Hauptlinie (eine Linie): direkt unter dem Bereich
            for node in nodes:
                h = node_h(node, node_w)
                nx = left + (width - node_w) / 2
                items.append({"type": "wire", "x1": feed_x, "y1": y, "x2": feed_x,
                              "y2": y + gap, "bus": False})
                items.append({"type": "node", "x": nx, "y": y + gap, "w": node_w, "h": h,
                              "node": node})
                y += gap + h
        # Bereichslinie bis ins nächste Band (ausser nach dem letzten Bereich)
        if backbone and index < len(areas) - 1:
            items.append({"type": "wire", "x1": bus_x, "y1": head_h / 2, "x2": bus_x,
                          "y2": y + gap, "bus": True})
        bands.append({"height": y, "width": left + width, "items": items})
    return bands
