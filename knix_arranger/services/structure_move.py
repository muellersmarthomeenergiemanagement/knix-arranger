"""
Ziehen und Ablegen in Gebäude, Topologie und Gewerke-Übersicht (FA-1015 a-c).

Reine Datenoperationen ohne Qt. Die Ansichten fragen mit den can_*-Funktionen,
ob ein Ablegen erlaubt ist, und lösen danach die übliche Neuberechnung aus.

a) Raum auf eine Wohnung/Zone oder ein Stockwerk ziehen: der Raum wechselt
   dorthin (physisches Stockwerk = room.floor_id).
b) Gerät auf eine andere Linie ziehen: bei geplanten Projekten wechselt der
   Raum des Geräts die Linie (die Geräte werden aus der Zuordnung Raum → Linie
   abgeleitet); manuell hinzugefügte und importierte Geräte wandern selbst
   und erhalten eine freie Teilnehmernummer der Ziellinie. Programmierte
   Geräte bleiben, wo sie sind.
c) Gewerk aus dem Katalog auf einen Raum ziehen (fügt es hinzu bzw. erhöht
   die Anzahl) oder eine Gewerk-Zuweisung in einen anderen Raum ziehen.
"""
from __future__ import annotations

from ..models.building import Apartment, Areal, Floor, GewerkAssignment, Room
from ..models.topology import Device, Line, Topology

MAX_GEWERK_COUNT = 20  # wie die Anzahl-Auswahl der Gewerke-Übersicht


# ── a) Räume ───────────────────────────────────────────────────────────────

def apartment_of(areal: Areal, room: Room) -> Apartment | None:
    for floor in areal.all_floors:
        for apt in floor.apartments:
            if room in apt.rooms:
                return apt
    return None


def floor_of(areal: Areal, apt: Apartment) -> Floor | None:
    return next((f for f in areal.all_floors if apt in f.apartments), None)


def room_target_on_floor(areal: Areal, room: Room, floor: Floor) -> Apartment | None:
    """Ziel-Zone beim Ablegen auf einem Stockwerk: dieselbe Zone wie bisher,
    falls sie dort vorkommt (Maisonette), sonst die erste."""
    current = apartment_of(areal, room)
    if current is not None:
        same = next((a for a in floor.apartments if a.name == current.name), None)
        if same is not None:
            return same
    return floor.apartments[0] if floor.apartments else None


def can_move_room(areal: Areal, room: Room, target: Apartment | None) -> bool:
    return target is not None and apartment_of(areal, room) not in (None, target)


def move_room(areal: Areal, room: Room, target: Apartment) -> bool:
    """Hängt den Raum in eine andere Wohnung/Zone um. Raumnummer, Gewerke und
    Bedienelemente bleiben; die Adressen folgen bei der Neuberechnung dem
    Stockwerk."""
    if not can_move_room(areal, room, target):
        return False
    apartment_of(areal, room).rooms.remove(room)
    target.rooms.append(room)
    floor = floor_of(areal, target)
    if floor is not None:
        room.floor_id = floor.id
    return True


# ── b) Geräte und Linien ───────────────────────────────────────────────────

def line_of(topology: Topology, device: Device) -> Line | None:
    for area in topology.areas:
        for line in area.lines:
            if device in line.devices:
                return line
    return None


def _area_of(topology: Topology, line: Line):
    return next((a for a in topology.areas if line in a.lines), None)


def move_kind(topology: Topology, device: Device) -> str:
    """Was das Ziehen dieses Geräts bewirkt: "device" (Gerät wandert),
    "room" (sein Raum wechselt die Linie) oder "" (nicht verschiebbar)."""
    if device.device_type in ("coupler", "power_supply") or device.is_programmed:
        return ""
    if topology.is_imported or device.manually_added:
        return "device"
    return "room" if device.room_id else ""


def can_move_device(topology: Topology, device: Device, target: Line) -> bool:
    kind = move_kind(topology, device)
    if not kind:
        return False
    if kind == "room":
        return device.room_id not in target.assigned_room_ids
    return line_of(topology, device) not in (None, target)


def free_participant(topology: Topology, line: Line, preferred: int = 0) -> int:
    """Gewünschte Teilnehmernummer, falls auf der Linie frei, sonst die
    kleinste freie ab 1."""
    used: set[int] = set()
    for device in line.devices:
        parts = (device.physical_address or "").split(".")
        if len(parts) == 3 and parts[2].isdigit():
            used.add(int(parts[2]))
    if 0 < preferred <= 255 and preferred not in used:
        return preferred
    return next((n for n in range(1, 256) if n not in used), 0)


def move_device(topology: Topology, device: Device, target: Line) -> str:
    """Gerät auf eine andere Linie (importiert oder manuell hinzugefügt).
    Die Teilnehmernummer bleibt, wenn sie dort frei ist. Gibt die neue
    physikalische Adresse zurück, leer wenn nicht möglich."""
    if move_kind(topology, device) != "device" or not can_move_device(topology, device, target):
        return ""
    area = _area_of(topology, target)
    parts = (device.physical_address or "").split(".")
    preferred = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else 0
    number = free_participant(topology, target, preferred)
    if area is None or not number:
        return ""
    source = line_of(topology, device)
    source.devices.remove(device)
    source.update_device_count()
    target.devices.append(device)
    target.update_device_count()
    device.physical_address = f"{area.area_number}.{target.line_number}.{number}"
    return device.physical_address


def move_room_to_line(topology: Topology, room_id: str, target: Line) -> bool:
    """Raum auf eine andere Linie umhängen (geplante Projekte). Die Geräte
    folgen bei der Neuberechnung."""
    if not room_id or room_id in target.assigned_room_ids:
        return False
    for area in topology.areas:
        for line in area.lines:
            if room_id in line.assigned_room_ids:
                line.assigned_room_ids.remove(room_id)
    target.assigned_room_ids.append(room_id)
    return True


# ── c) Gewerke ─────────────────────────────────────────────────────────────

def add_gewerk(room: Room, code: str) -> GewerkAssignment | None:
    """Gewerk aus dem Katalog auf einen Raum: neu mit Anzahl 1 oder, falls
    schon vorhanden, ein Element mehr. None, wenn die Anzahl am Maximum ist."""
    existing = next((g for g in room.gewerk_assignments if g.gewerk_code == code), None)
    if existing is None:
        assignment = GewerkAssignment(gewerk_code=code, count=1)
        room.gewerk_assignments.append(assignment)
        return assignment
    if existing.count >= MAX_GEWERK_COUNT:
        return None
    existing.count += 1
    return existing


def can_move_gewerk(source: Room, assignment: GewerkAssignment, target: Room) -> bool:
    return (target is not source and assignment in source.gewerk_assignments
            and not any(g.gewerk_code == assignment.gewerk_code
                        for g in target.gewerk_assignments))


def move_gewerk(areal: Areal, source: Room, assignment: GewerkAssignment,
                target: Room) -> bool:
    """Gewerk-Zuweisung samt Anzahl, Klartext und Produkt in einen anderen Raum.
    Tasten, die diese Elemente bedienen, bedienen sie weiterhin (Verweis auf
    den neuen Raum). Die Zuordnung zu Tastereinheiten beginnt im Zielraum
    wieder bei der ersten."""
    if not can_move_gewerk(source, assignment, target):
        return False
    source.gewerk_assignments.remove(assignment)
    target.gewerk_assignments.append(assignment)
    assignment.taster_indices = [1]
    code = assignment.gewerk_code
    for room in areal.all_rooms:
        for be in room.bedienelemente:
            for sf in be.funktionen:
                if sf.gewerk_code != code:
                    continue
                points_to_source = (sf.source_room_id == source.id
                                    or (not sf.source_room_id and room is source))
                if points_to_source:
                    sf.source_room_id = "" if room is target else target.id
    return True
