"""
Positionsnummern der Bedienelemente (KNX-Swiss-Projektrichtlinien 10.7, FA-1404b).

Verweis vom Plan bzw. Raumbuch auf ein Bedienelement, das (noch) keine eigene
physikalische Adresse hat: «E05-01» = Raum E05, fortlaufende Nummer im Raum.
Nur geplante Projekte; importierte haben ihre Adressen aus der ETS.

- Gespeichert wird je Bedienelement nur die laufende Nummer
  (Bedienelement.position_index). Den Raumteil liefert die aktuelle
  Raumnummer, damit eine umbenannte Raumnummer nichts verwaist.
- Einmal vergeben, rückt nichts nach: ein gelöschtes Element hinterlässt eine
  Lücke, damit beschriftete Pläne stimmen. Neue Elemente erhalten die nächste
  Nummer nach der höchsten des Raums.
- Angezeigt wird die Nummer, wo eine Adresse fehlt oder nicht eindeutig auf
  den Taster zeigt: ohne Adresse, und bei konventionellen Tastern an einer
  Taster-/Universalschnittstelle bzw. mehreren Bedienelementen auf einer Adresse.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import re
from collections import Counter

from .naming_engine import label_floor_code

# Schnittstellen für konventionelle Taster: mehrere Taster, eine Adresse
_INTERFACE_RE = re.compile(
    r"tasterschnittstelle|universalschnittstelle|universal interface|"
    r"push.?button interface|bin(ä|ae)reingang|binary input", re.IGNORECASE)


def room_part(floor, room) -> str:
    """Raumteil wie in der GA-Bezeichnung (FA-401): «E05», bei Raumnummern
    je Stockwerk mit Stockwerk «DG_04»."""
    code = (floor.short_code or floor.name or "") if floor is not None else ""
    number = room.number or ""
    if not number:
        return code
    return "_".join(p for p in (label_floor_code(code, number), number) if p)


def assign_position_numbers(project) -> int:
    """Fehlende Positionsnummern vergeben (nur geplante Projekte). Doppelte
    Nummern im selben Raum (Element aus einem anderen Raum verschoben)
    erhalten eine neue. Gibt die Zahl neu vergebener Nummern zurück."""
    if project.topology.is_imported:
        return 0
    assigned = 0
    for room in project.all_rooms:
        used: set[int] = set()
        pending = []
        for be in room.bedienelemente:
            if be.suppressed:
                # Tombstones behalten ihre Nummer (nicht wiederverwenden)
                if be.position_index:
                    used.add(be.position_index)
                continue
            if be.position_index and be.position_index not in used:
                used.add(be.position_index)
            else:
                pending.append(be)
        next_index = max(used, default=0)
        for be in pending:
            next_index += 1
            be.position_index = next_index
            assigned += 1
    return assigned


class PositionLabels:
    """Anzeige je Bedienelement: einmal je Bericht bzw. Ansicht aufbauen.
    Aus dem Projekt oder (Gebäudeansicht) aus Areal und Topologie."""

    def __init__(self, project=None, *, areal=None, topology=None):
        areal = areal if project is None else project.areal
        topology = topology if project is None else project.topology
        self.planned = topology is None or not topology.is_imported
        self._floor_by_room = {}
        rooms = areal.all_rooms if areal is not None else []
        if self.planned and areal is not None:
            for floor in areal.all_floors:
                for room in floor.all_rooms:
                    self._floor_by_room[room.id] = floor
        shared = Counter(be.participant_number for r in rooms
                         for be in r.bedienelemente
                         if be.participant_number and not be.suppressed)
        self._shared = {pa for pa, n in shared.items() if n > 1}
        self._interfaces = {
            d.physical_address for a in (topology.areas if topology else [])
            for ln in a.lines for d in ln.devices
            if d.physical_address and _INTERFACE_RE.search(
                f"{d.product or ''} {d.product_name or ''}")}

    def label(self, room, be) -> str:
        """«E05-01», "" ohne Nummer oder in importierten Projekten."""
        if not self.planned or not be.position_index:
            return ""
        return f"{room_part(self._floor_by_room.get(room.id), room)}-{be.position_index:02d}"

    def number(self, room, be) -> str:
        """Positionsnummer für Berichte: nur wo die Adresse den Taster nicht
        eindeutig bezeichnet, sonst ""."""
        pa = be.participant_number
        if pa and pa not in self._shared and pa not in self._interfaces:
            return ""
        return self.label(room, be)

    def reference(self, room, be, missing: str = "Ohne Adresse",
                  always: bool = False) -> str:
        """«1.1.12 · E05-01», «E05-01» oder missing. always: Positionsnummer
        auch neben einer eindeutigen Adresse (Ansichten der App, zum
        Beschriften der Pläne)."""
        position = self.label(room, be) if always else self.number(room, be)
        parts = [p for p in (be.participant_number, position) if p]
        return " · ".join(parts) or missing
