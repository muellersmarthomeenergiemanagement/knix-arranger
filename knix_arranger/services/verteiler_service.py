"""
Einbauort der Aktoren: Verteiler je Linie und je Aktortyp (FA-1305a).

Die Verteiler werden in Wizard Schritt 4 je Raum erfasst. Eine Linie
bekommt einen Verteiler -- gewählt (Line.verteiler_id) oder automatisch:
der erste Verteiler in ihren Räumen, sonst die erste HV, sonst der erste
Verteiler im Projekt. Je Aktortyp kann ein anderer Verteiler gelten
(Line.actor_verteiler), z.B. Jalousieaktoren in der UV Halle.
"""
from __future__ import annotations

from ..models.building import Room, Verteiler
from ..models.topology import Line, Topology


def verteiler_label(vt: Verteiler, room: Room) -> str:
    """Einbauort-Text, z.B. "HV (HV Technikraum)"."""
    if not vt.verteiler_type:
        return vt.name or room.name
    return f"{vt.verteiler_type} ({vt.name or room.name})"


class VerteilerPlacement:
    """Ordnet Linien und Aktortypen ihre Verteiler zu."""

    def __init__(self, rooms: list[Room]):
        self.refs: list[tuple[Verteiler, Room]] = [
            (vt, room) for room in rooms for vt in room.verteiler
        ]
        self.by_id = {vt.id: (vt, room) for vt, room in self.refs}
        self.labels = {verteiler_label(vt, room) for vt, room in self.refs}

    def label(self, vt_id: str) -> str:
        ref = self.by_id.get(vt_id)
        return verteiler_label(*ref) if ref else ""

    def default_for_line(self, line: Line) -> tuple[Verteiler, Room] | None:
        rooms = set(line.assigned_room_ids)
        for vt, room in self.refs:
            if room.id in rooms:
                return vt, room
        for vt, room in self.refs:
            if vt.verteiler_type == "HV":
                return vt, room
        return self.refs[0] if self.refs else None

    def for_line(self, line: Line) -> tuple[Verteiler, Room] | None:
        return self.by_id.get(line.verteiler_id) or self.default_for_line(line)

    def for_actor(self, line: Line, actor_type: str) -> tuple[Verteiler, Room] | None:
        return self.by_id.get(line.actor_verteiler.get(actor_type, "")) or self.for_line(line)

    def is_auto_location(self, line: Line) -> bool:
        """Einbauort der Linie stammt aus den Verteilern (kein eigener Freitext)."""
        return (bool(line.verteiler_id) or not line.uv_location
                or line.uv_location in self.labels)

    def apply_line(self, line: Line) -> None:
        """Setzt line.uv_location aus dem Verteiler (Freitext bleibt)."""
        if not self.is_auto_location(line):
            return
        ref = self.for_line(line)
        if ref is not None:
            line.uv_location = verteiler_label(*ref)

    def actor_location(self, line: Line, actor_type: str) -> str:
        """Einbauort eines Aktors: Abweichung je Typ, sonst der der Linie."""
        vt_id = line.actor_verteiler.get(actor_type, "")
        if vt_id in self.by_id:
            return self.label(vt_id)
        return line.uv_location


def apply_device_locations(topology: Topology, rooms: list[Room]) -> None:
    """Einbauorte der Linien und ihrer Geräte nach einer geänderten
    Verteiler-Wahl nachführen. Programmierte Geräte und eigene Freitexte
    (kein Verteiler-Text) bleiben unverändert; importierte Topologien auch."""
    if topology.is_imported:
        return
    placement = VerteilerPlacement(rooms)
    for area in topology.areas:
        for line in area.lines:
            placement.apply_line(line)
            for device in line.devices:
                if device.is_programmed or device.device_type == "sensor":
                    continue
                if device.installation_location and                         device.installation_location not in placement.labels:
                    continue
                if device.device_type in ("actor", "gateway"):
                    device.installation_location = placement.actor_location(
                        line, device.product)
                elif device.device_type in ("coupler", "power_supply"):
                    device.installation_location = line.uv_location


def carry_over_line_verteiler(old: Topology, new: Topology) -> None:
    """Gewählte Verteiler bei einer Neuberechnung der Topologie übernehmen
    (Linien entstehen neu; Zuordnung über den Liniennamen = Zone)."""
    previous = {line.name: line for area in old.areas for line in area.lines}
    for area in new.areas:
        for line in area.lines:
            prev = previous.get(line.name)
            if prev is not None:
                line.verteiler_id = prev.verteiler_id
                line.actor_verteiler = dict(prev.actor_verteiler)
