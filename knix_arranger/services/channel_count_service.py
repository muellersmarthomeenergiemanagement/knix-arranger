"""
Gewerk-Zählung aus der Topologie: gesteuerte Elemente (importierte Projekte).

Die GA-Bezeichnungen eines ETS-Projekts allein sagen nicht zuverlässig, wie
viele Elemente eines Gewerks tatsächlich gesteuert werden: reine
Temperaturfühler oder unbenutzte GAs würden mitgezählt. Gezählt werden
deshalb nur Elemente, deren GA mit einem Aktor oder Gateway verbunden ist.

Element = Gewerk + Stockwerk + Raum + Element-Nr. aus der Bezeichnung
("H.EG.04.1_ea" -> Heizung, EG Raum 04, Element 1). Mehrere GAs desselben
Elements (Schalten, Status, ...) und mehrere Geräte auf derselben GA
(Aktor und Präsenzmelder) zählen einmal. Eine GA für mehrere Räume
("H.EG.02.01+H.EG.03.01") ist ein Element im ersten genannten Raum.
Zentraladressen (HG 0) zählen nicht.

Die Objektnamen der Aktorkanäle eignen sich dafür nicht: sie sind je
Hersteller völlig verschieden ("Ausgang A", "Kanal 1", "GO0009",
"Group 1, Switching", "$Dummy").
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field

from ..models.building import Areal, GewerkAssignment
from .gewerk_service import GewerkService

# Gerätetypen, die Verbraucher steuern. Taster und Sensoren senden auf
# dieselben GAs, belegen aber kein eigenes Element.
_CONTROLLING_DEVICE_TYPES = ("actor", "gateway")


@dataclass
class ElementCounts:
    by_room: dict[str, Counter] = field(default_factory=dict)   # room.id -> Code -> Anzahl
    unassigned: Counter = field(default_factory=Counter)         # Raum nicht in Gebäudestruktur
    # Stockwerk + Raum-Nr. aus der Bezeichnung, die in der Gebäudestruktur
    # fehlen ("OG 04") -> Code -> Anzahl
    missing_rooms: dict[str, Counter] = field(default_factory=dict)

    def totals(self) -> Counter:
        total = Counter(self.unassigned)
        for counts in self.by_room.values():
            total.update(counts)
        return total

    @property
    def codes(self) -> set[str]:
        return set(self.totals())

    def __bool__(self) -> bool:
        return bool(self.totals())


def _controlled_addresses(project) -> set[str]:
    return {
        addr
        for area in project.topology.areas
        for line in area.lines
        for device in line.devices
        if device.device_type in _CONTROLLING_DEVICE_TYPES
        for co in device.communication_objects
        for addr in co.connected_gas
    }


def count_controlled_elements(project) -> ElementCounts:
    """Zählt die von Aktoren/Gateways gesteuerten Elemente je Raum und Gewerk."""
    catalog = project.gewerk_catalog
    room_index = GewerkService._build_room_index(project.areal)
    controlled = _controlled_addresses(project)

    elements: set[tuple[str, str, str, int]] = set()
    for ga in project.group_addresses.all_addresses():
        if ga.main_group == 0 or ga.address not in controlled:
            continue
        matched = GewerkService._match_ga_designation(ga.designation or "")
        if matched is None:
            continue
        code, floor_code, room_nr, elem_nr, _combined = matched
        if catalog.get(code):
            elements.add((code, floor_code, room_nr, int(elem_nr)))

    result = ElementCounts()
    for code, floor_code, room_nr, _elem in elements:
        room = room_index.get((floor_code, room_nr))
        if room is None:
            result.unassigned[code] += 1
            result.missing_rooms.setdefault(f"{floor_code} {room_nr}", Counter())[code] += 1
        else:
            result.by_room.setdefault(room.id, Counter())[code] += 1
    return result


def apply_element_counts(areal: Areal, counts: ElementCounts,
                         dry_run: bool = False) -> list[str]:
    """Setzt die Gewerk-Anzahlen in den Räumen auf die gesteuerten Elemente.

    Nur Gewerke, die an mindestens einem Aktor/Gateway hängen, werden
    angepasst; andere (z.B. reine Sensor-Gewerke) bleiben unverändert.
    Bestehende Zuweisungen werden weiterverwendet (Verknüpfungen, Produkte
    und Tastereinheiten bleiben erhalten), nur die Anzahl ändert sich;
    überzählige Einträge desselben Gewerks im Raum werden entfernt.

    Gibt die Änderungen als lesbare Zeilen zurück ("EG 06 Studio: M 3 → 0").
    """
    codes = counts.codes
    changes: list[str] = []
    for building in areal.buildings:
        for wing in building.wings:
            for floor in wing.floors:
                for apartment in floor.apartments:
                    for room in apartment.rooms:
                        room_counts = counts.by_room.get(room.id, Counter())
                        label = " ".join(" ".join(p.split()) for p in (
                            floor.short_code or floor.name, room.number, room.name) if p)
                        for code in sorted(codes):
                            target = room_counts.get(code, 0)
                            existing = [a for a in room.gewerk_assignments
                                        if a.gewerk_code == code]
                            current = sum(a.count for a in existing)
                            if current == target:
                                continue
                            changes.append(f"{label}: {code} {current} → {target}")
                            if not dry_run:
                                _set_count(room, code, existing, target)
    return changes


def _set_count(room, code: str, existing: list[GewerkAssignment], target: int) -> None:
    if not existing:
        room.gewerk_assignments.append(GewerkAssignment(gewerk_code=code, count=target))
        return
    keep: list[GewerkAssignment] = []
    remaining = target
    for i, assignment in enumerate(existing):
        if remaining <= 0:
            break
        is_last = i == len(existing) - 1
        assignment.count = remaining if is_last else min(assignment.count, remaining)
        remaining -= assignment.count
        keep.append(assignment)
    keep_ids = {id(a) for a in keep}
    room.gewerk_assignments = [
        a for a in room.gewerk_assignments
        if a.gewerk_code != code or id(a) in keep_ids
    ]
