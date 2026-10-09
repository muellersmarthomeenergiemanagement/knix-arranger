"""
Ziehen und Ablegen in Gebäude, Topologie und Gewerke-Übersicht (FA-1015 a-c).

Reine Datenoperationen ohne Qt. Die Ansichten fragen mit den can_*-Funktionen,
ob ein Ablegen erlaubt ist, und lösen danach die übliche Neuberechnung aus.

a) Raum auf eine Wohnung/Zone oder ein Stockwerk ziehen: der Raum wechselt
   dorthin (physisches Stockwerk = room.floor_id). Eine ganze Wohnung/Zone
   lässt sich auf ein anderes Stockwerk umhängen, auch in ein anderes Gebäude.
b) Gerät auf eine andere Linie ziehen: bei geplanten Projekten wechselt der
   Raum des Geräts die Linie (die Geräte werden aus der Zuordnung Raum → Linie
   abgeleitet); manuell hinzugefügte und importierte Geräte wandern selbst
   und erhalten eine freie Teilnehmernummer der Ziellinie. Programmierte
   Geräte bleiben, wo sie sind. Eine ganze Linie lässt sich in einen anderen
   Bereich umhängen (z.B. Gartenhaus → Bereich Nebengebäude) oder mit einer
   anderen Linie zusammenlegen.
c) Gewerk aus dem Katalog auf einen Raum ziehen (fügt es hinzu bzw. erhöht
   die Anzahl) oder eine Gewerk-Zuweisung in einen anderen Raum ziehen.
"""
from __future__ import annotations

from ..models.building import Apartment, Areal, Floor, GewerkAssignment, Room
from ..models.topology import Area, Device, Line, Topology

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


def can_move_apartment(areal: Areal, apt: Apartment, target: Floor | None) -> bool:
    """Nicht auf das eigene Stockwerk und nicht neben eine gleichnamige Zone
    (gleicher Name = dieselbe Zone, siehe Areal.is_multi_zone)."""
    source = floor_of(areal, apt)
    return (target is not None and source is not None and target is not source
            and not any(a.name == apt.name for a in target.apartments))


def move_apartment(areal: Areal, apt: Apartment, target: Floor) -> bool:
    """Hängt eine Wohnung/Zone samt Räumen auf ein anderes Stockwerk um.
    Die Gruppenadressen folgen bei der Neuberechnung der Hauptgruppe des
    neuen Stockwerks."""
    if not can_move_apartment(areal, apt, target):
        return False
    floor_of(areal, apt).apartments.remove(apt)
    target.apartments.append(apt)
    for room in apt.rooms:
        room.floor_id = target.id
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


def room_follows_planning(topology: Topology, device: Device) -> bool:
    """Geplante Taster, Sensoren und Aktoren ergeben sich aus den Gewerken
    ihres Raums: eine Neuberechnung legt sie wieder dort ab. Ihr Raum ist
    deshalb nicht direkt änderbar (sonst blieb eine leere Kopie des
    Bedienelements im Zielraum zurück, Projekt_23 1.1.106)."""
    return (not topology.is_imported and not device.manually_added
            and device.device_type not in ("coupler", "power_supply"))


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


def free_line_number(area: Area) -> int:
    """Kleinste freie Liniennummer 1-15 im Bereich, 0 wenn voll."""
    used = {line.line_number for line in area.lines}
    return next((n for n in range(1, 16) if n not in used), 0)


def can_move_line(topology: Topology, line: Line, target: Area) -> bool:
    source = _area_of(topology, line)
    return (source is not None and target is not source
            and bool(free_line_number(target))
            and not any(d.is_programmed for d in line.devices))


def move_line_to_area(topology: Topology, line: Line, target: Area) -> str:
    """Linie in einen anderen Bereich: sie erhält dort die kleinste freie
    Nummer, Koppler und Geräte die neuen Adressen (Teilnehmernummern bleiben).
    Nicht bei programmierten Geräten – deren Adresse steht im Gerät. Gibt die
    neue Linienadresse "B.L" zurück, leer wenn nicht möglich."""
    if not can_move_line(topology, line, target):
        return ""
    source = _area_of(topology, line)
    old_prefix = f"{source.area_number}.{line.line_number}."
    number = free_line_number(target)
    source.lines.remove(line)
    line.line_number = number
    target.lines.append(line)
    target.lines.sort(key=lambda l: l.line_number)
    new_prefix = f"{target.area_number}.{number}."
    if line.coupler_address:
        line.coupler_address = f"{new_prefix}0"
    for device in line.devices:
        if device.physical_address.startswith(old_prefix):
            device.physical_address = new_prefix + device.physical_address[len(old_prefix):]
    return f"{target.area_number}.{number}"


def _wandering_devices(topology: Topology, line: Line) -> list[Device]:
    """Geräte, die beim Zusammenlegen selbst die Linie wechseln."""
    return [d for d in line.devices
            if d.device_type not in ("coupler", "power_supply")
            and move_kind(topology, d) == "device"]


def can_merge_lines(topology: Topology, source: Line, target: Line) -> bool:
    if (source is target or _area_of(topology, source) is None
            or _area_of(topology, target) is None
            or any(d.is_programmed for d in source.devices)):
        return False
    used = {d.physical_address.split(".")[-1] for d in target.devices}
    free = sum(1 for n in range(1, 256) if str(n) not in used)
    return len(_wandering_devices(topology, source)) <= free


def merge_lines(topology: Topology, source: Line, target: Line) -> bool:
    """Linie source in target aufgehen lassen und entfernen. Bei geplanten
    Projekten wechseln die Räume (die Neuberechnung legt die Geräte auf der
    Ziellinie an, gleichartige Aktoren werden dabei zusammengelegt); manuell
    hinzugefügte und importierte Geräte wandern selbst mit einer freien
    Teilnehmernummer. Koppler und Speisung der aufgelösten Linie entfallen.
    Nicht bei programmierten Geräten."""
    if not can_merge_lines(topology, source, target):
        return False
    for room_id in source.assigned_room_ids:
        if room_id not in target.assigned_room_ids:
            target.assigned_room_ids.append(room_id)
    for floor_id in source.assigned_floor_ids:
        if floor_id not in target.assigned_floor_ids:
            target.assigned_floor_ids.append(floor_id)
    source.assigned_room_ids = []
    for device in _wandering_devices(topology, source):
        move_device(topology, device, target)
    _area_of(topology, source).lines.remove(source)
    target.update_device_count()
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
