"""
Verbindungen je Gruppenadresse für die GA-Übersicht: welche Gewerke sie
betrifft, an welchen Aktoren/Geräten sie liegt und wer sie bedient.

Quelle ist der Belegungsplan (wie Raumbuch und Verknüpfungsmatrix):
- Aktor-Zeilen: Aktor/Gateway mit Kanal und Verteiler je GA, auch
  Zentral- und Szenen-GAs (HG 0) an allen erreichten Aktoren;
- Sensor-Zeilen: Taster und Sensoren, die auf die GA senden (Anzeige =
  LED-Rückmeldung, nur empfangen).
Gewerke, deren GAs dem Sensor gehören (A, FK, W ...), haben keinen Aktor --
dort ist das Gerät der Sensor des Elements (product_sync.device_elements),
z.B. Projekt_23 Bewegungsmelder 1.2.105 für Gewerk A.

Betroffene Gewerke: das Gewerk der GA; Szenen- und andere Zentral-GAs ohne
Gewerk wirken auf die Gewerke aller Stromkreise ihrer Aktoren, z.B.
0/4/1 «Anwesenheit Komplex» -> G, H, J, L, LD, LDA, M, MM, S, V.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .room_sheet import (
    _channel_text, _operator_text, short_location, verteiler_designations,
)


@dataclass
class GaLink:
    gewerke: list[str] = field(default_factory=list)
    room: tuple[str, str] = ("", "")      # (Nummer, Name)
    outputs: list[str] = field(default_factory=list)   # "Schaltaktor 1.1.22 · K3 · HV T"
    actor_addresses: list[str] = field(default_factory=list)
    operators: list[str] = field(default_factory=list)  # "1.1.101 Taste 1"

    @property
    def connected(self) -> bool:
        return bool(self.outputs or self.operators)


def ga_links(project, plan=None) -> dict[str, GaLink]:
    """Adresse -> GaLink für alle belegten Gruppenadressen."""
    from .belegungsplan_service import BelegungsplanService
    from .product_sync import device_elements, sensor_owns_gewerk
    from .report_service import _clean_location

    if plan is None:
        plan = BelegungsplanService().generate(project)
    rooms = {r.id: r for r in project.all_rooms}
    designations = verteiler_designations(project)
    gas = [ga for ga in project.group_addresses.all_addresses() if not ga.is_placeholder]
    links: dict[str, GaLink] = {}
    for ga in gas:
        room = rooms.get(ga.room_id)
        links[ga.address] = GaLink(
            gewerke=[ga.gewerk_code] if ga.gewerk_code else [],
            room=(room.number, room.name) if room else (ga.room_number, ""))

    # Gewerke der Stromkreise je Aktor (für GAs ohne eigenes Gewerk)
    circuit_gewerke: dict[str, set[str]] = {}
    for row in plan.actor_rows:
        if row.gewerk_code and row.room_id:
            circuit_gewerke.setdefault(row.physical_address, set()).add(row.gewerk_code)

    # Aktoren: je GA und Aktor die Kanäle sammeln
    outputs: dict[str, dict[tuple, list[str]]] = {}
    for row in plan.actor_rows:
        if row.ga_address not in links:
            continue
        uv = ", ".join(dict.fromkeys(
            short_location(loc, designations)
            for loc in (_clean_location(p) for p in (row.uv_location or "").split(","))
            if loc))
        key = (row.actor_type, row.physical_address, row.dali_group is not None, uv)
        channels = outputs.setdefault(row.ga_address, {}).setdefault(key, [])
        channel = (str(row.dali_group) if row.dali_group is not None
                   else row.channel_name or row.channel_number)
        if channel and channel not in channels:
            channels.append(channel)
    for address, found in outputs.items():
        link = links[address]
        for (actor_type, pa, dali, uv), channels in found.items():
            head = " ".join(p for p in (actor_type, pa) if p)
            link.outputs.append(" · ".join(
                p for p in (head, _channel_text(channels, dali), uv) if p))
            link.actor_addresses.append(pa)
        if not link.gewerke:
            link.gewerke = sorted(set().union(
                *(circuit_gewerke.get(pa, set()) for pa in link.actor_addresses)))

    # Gewerke ohne Aktor: das Gerät ist der Sensor des Elements
    sensor_of: dict[tuple[str, int], object] = {}
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if device.device_type != "sensor":
                    continue
                for _room, assignment, nr in device_elements(project, device):
                    if sensor_owns_gewerk(assignment.gewerk_code):
                        sensor_of.setdefault((assignment.id, nr), device)
    for ga in gas:
        link = links[ga.address]
        device = sensor_of.get((ga.assignment_id, ga.element_number))
        if device is not None and not link.outputs:
            name = device.product_name or device.product
            link.outputs.append(" ".join(p for p in (name, device.physical_address) if p))

    # Bedienung: Taster und Sensoren (Anzeige = LED-Rückmeldung)
    for row in plan.sensor_rows:
        link = links.get(row.ga_address)
        if link is None:
            continue
        text = _operator_text(row)
        if row.is_feedback:
            text += " (Anzeige)"
        if text not in link.operators:
            link.operators.append(text)
    return links
