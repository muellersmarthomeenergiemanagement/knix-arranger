"""
Gewerk-Zuordnung von Aktoren und Gateways für die Anzeige (Materialliste,
Produktauswahl).

Die Topologie speichert pro Gerät nur den Gerätetyp (z.B. "Modbus-KNX-Gateway
1-fach"), nicht das Gewerk, für das es geplant wurde. Da jeder Gerätetyp zu
festen Gewerk-Codes gehört (siehe _ACTOR_TYPE_GEWERKE im Belegungsplan), lässt
sich die Zuordnung zurückrechnen: Gewerk-Codes des Typs, geschnitten mit den
Gewerken der Räume auf der Linie des Geräts.
"""
from __future__ import annotations

from ..models.building import Room
from ..models.gewerk import GewerkCatalog
from ..models.topology import Device, Line
from .belegungsplan_service import gewerke_for_actor_product

# Räume pro Gewerk, ab denen nur noch die Anzahl angezeigt wird
_MAX_ROOMS_INLINE = 2


def gewerk_codes_for_device(device: Device) -> set[str]:
    """Gewerk-Codes eines Aktors/Gateways; manuell zugewiesene Funktionen
    haben Vorrang vor der Ableitung aus dem Gerätetyp."""
    if device.device_type not in ("actor", "gateway"):
        return set()
    manual = {c for c in device.manual_functions if c != "SZ"}
    return manual or set(gewerke_for_actor_product(device.product))


def describe_device_gewerke(
    devices: list[tuple[Device, Line]],
    room_by_id: dict[str, Room],
    catalog: GewerkCatalog,
) -> tuple[str, str]:
    """Liefert (Kurztext, Tooltip) zur Gewerk-/Raumzuordnung der Geräte.

    Beispiel: "WP Waermepumpe – U01 Technik". Leerer Text, wenn keines der
    Geräte ein Aktor/Gateway ist.
    """
    rooms_by_code: dict[str, list[Room]] = {}
    for device, line in devices:
        codes = gewerk_codes_for_device(device)
        for code in codes:
            rooms_by_code.setdefault(code, [])
        for rid in line.assigned_room_ids:
            room = room_by_id.get(rid)
            if not room:
                continue
            room_codes = {a.gewerk_code for a in room.gewerk_assignments}
            for code in codes & room_codes:
                if room not in rooms_by_code[code]:
                    rooms_by_code[code].append(room)

    # Codes ohne Raum auf der Linie ausblenden, sofern andere Codes Räume
    # haben (ein Schaltaktor soll nicht "S, V, G, BW ..." ohne Bezug zeigen).
    if any(rooms_by_code.values()):
        rooms_by_code = {c: r for c, r in rooms_by_code.items() if r}
    if not rooms_by_code:
        return "", ""

    segments: list[str] = []
    tooltip_lines: list[str] = []
    for code in sorted(rooms_by_code):
        gewerk = catalog.get(code)
        label = f"{code} {gewerk.name}" if gewerk else code
        rooms = rooms_by_code[code]
        room_labels = [f"{r.number} {r.name}".strip() for r in rooms]
        if not rooms:
            segments.append(label)
            tooltip_lines.append(label)
            continue
        if len(rooms) <= _MAX_ROOMS_INLINE:
            segments.append(f"{label} – {', '.join(room_labels)}")
        else:
            segments.append(f"{label} – {len(rooms)} Räume")
        tooltip_lines.append(f"{label}: {', '.join(room_labels)}")
    return "; ".join(segments), "\n".join(tooltip_lines)
