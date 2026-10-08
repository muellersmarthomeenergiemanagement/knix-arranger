"""
Korrekturschicht für importierte ETS-Projekte (siehe models/ets_corrections).

Wirksamer Wert = Korrektur, falls vorhanden, sonst das, was die ETS liefert.
"""
from __future__ import annotations
from dataclasses import dataclass

from .gewerk_service import GewerkService


def ets_gewerk(ga) -> str:
    """Gewerk, wie es aus dem ETS-Namen folgt ("T.EG.01.03_ea" -> "T")."""
    matched = GewerkService._match_ga_designation(ga.designation or "")
    return matched[0] if matched else ""


def effective_gewerk(project, ga) -> str:
    override = project.ets_corrections.gewerk_by_address.get(ga.address)
    return override or ga.gewerk_code or ets_gewerk(ga)


def apply_ets_corrections(project) -> int:
    """Wendet alle Korrekturen auf die ETS-Daten an (nach Öffnen, Import,
    Neuaufbau): Gewerke der GAs, Räume der Geräte, getrennte KO-Verknüpfungen.
    Idempotent; gibt die Anzahl korrigierter GAs zurück (Gewerk)."""
    n = 0
    overrides = project.ets_corrections.gewerk_by_address
    if overrides:
        for ga in project.group_addresses.all_addresses():
            code = overrides.get(ga.address)
            if not code:
                continue
            if ets_gewerk(ga) == code:
                # in der ETS nachgeführt: Korrektur erledigt
                del overrides[ga.address]
                continue
            ga.gewerk_code = code
            n += 1
    _apply_rooms(project)
    _apply_unlinks(project)
    return n


def set_gewerk(project, addresses: list[str], code: str) -> int:
    """Gewerk für GAs festlegen; code "" hebt die Korrektur auf (zurück zum
    ETS-Namen). Eine Korrektur gleich dem ETS-Kürzel wird nicht gespeichert."""
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    overrides = project.ets_corrections.gewerk_by_address
    changed = 0
    for addr in addresses:
        ga = by_address.get(addr)
        if ga is None:
            continue
        original = ets_gewerk(ga)
        if code and code != original:
            overrides[addr] = code
            ga.gewerk_code = code
        else:
            overrides.pop(addr, None)
            ga.gewerk_code = original or ga.gewerk_code
        changed += 1
    return changed


@dataclass
class Deviation:
    address: str      # GA-Adresse bzw. physikalische Adresse (Raum)
    designation: str
    field: str        # "Gewerk", "Raum", "Verknüpfung"
    ets_value: str
    knix_value: str


def _sort_key(address: str):
    return tuple(int(p) if p.isdigit() else 0 for p in address.replace(".", "/").split("/"))


def deviations(project) -> list[Deviation]:
    """Alle Korrekturen gegenüber der ETS, nach Angabe und Adresse sortiert."""
    corrections = project.ets_corrections
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    result = []
    for addr, code in corrections.gewerk_by_address.items():
        ga = by_address.get(addr)
        if ga is None or ets_gewerk(ga) == code:
            continue
        result.append(Deviation(addr, ga.designation, "Gewerk", ets_gewerk(ga) or "–", code))

    if corrections.room_by_device:
        from .multi_ga_check import find_device
        rooms = rooms_by_key(project)
        for pa, entry in corrections.room_by_device.items():
            device = find_device(project, pa)
            target = rooms.get(entry.get("room", ""))
            if device is None or target is None:
                continue
            ets = rooms.get(entry.get("ets", ""))
            result.append(Deviation(
                pa, device.product_name or device.product, "Raum",
                ets[0] if ets else (entry.get("ets") or "ohne Raum"), target[0]))

    for key in corrections.unlinked:
        pa, co_number, ga_addr = _split_unlink(key)
        ga = by_address.get(ga_addr)
        result.append(Deviation(
            ga_addr, f"{pa} KO {co_number}" + (f" · {ga.designation}" if ga else ""),
            "Verknüpfung", "verbunden", "getrennt"))

    order = {"Gewerk": 0, "Raum": 1, "Verknüpfung": 2}
    result.sort(key=lambda d: (order.get(d.field, 9), _sort_key(d.address)))
    return result


# ── Raum eines Geräts ────────────────────────────────────────────────────

def room_key(floor, room) -> str:
    """Raumschlüssel "EG|08" bzw. "EG|#UV1" -- wie der Re-Import-Abgleich
    (project_reconcile_service), denn Raum-IDs überleben keinen Neuaufbau."""
    code = floor.short_code or floor.name
    return f"{code}|{room.number}" if room.number else f"{code}|#{room.name}"


def rooms_by_key(project) -> dict[str, tuple[str, object]]:
    """Raumschlüssel -> (Anzeige "EG 08 Einstellhalle", Raum)."""
    result = {}
    for building in project.areal.buildings:
        for floor in building.all_floors:
            for room in floor.all_rooms:
                label = " ".join(p for p in (floor.short_code or floor.name,
                                             room.number, room.name) if p)
                result.setdefault(room_key(floor, room), (label, room))
    return result


def _key_of_room_id(project, room_id: str) -> str:
    return next((k for k, (_l, r) in rooms_by_key(project).items() if r.id == room_id), "")


def set_device_room(project, device, room) -> bool:
    """Gerät (samt Bedienelement) einem anderen Raum zuordnen. Bei aus der
    ETS importierten Projekten als Korrektur festgehalten, damit sie Re-Import
    und Neuaufbau übersteht; zurück in den ETS-Raum hebt sie auf. Gibt False
    zurück, wenn sich nichts ändert oder der Raum aus der Planung folgt."""
    from .structure_move import room_follows_planning
    if room is None or device.room_id == room.id:
        return False
    if room_follows_planning(project.topology, device):
        return False
    if project.topology.is_imported and device.physical_address:
        target = _key_of_room_id(project, room.id)
        entries = project.ets_corrections.room_by_device
        entry = entries.get(device.physical_address)
        ets = entry["ets"] if entry else _key_of_room_id(project, device.room_id)
        if target and target != ets:
            entries[device.physical_address] = {"room": target, "ets": ets}
        else:
            entries.pop(device.physical_address, None)
    device.room_id = room.id
    _move_bedienelement(project, device.physical_address, room)
    return True


def _move_bedienelement(project, physical_address: str, room) -> None:
    if not physical_address:
        return
    for other in project.all_rooms:
        for be in list(other.bedienelemente):
            if be.participant_number == physical_address and other is not room:
                other.bedienelemente.remove(be)
                room.bedienelemente.append(be)


def _apply_rooms(project) -> None:
    entries = project.ets_corrections.room_by_device
    if not entries:
        return
    from .multi_ga_check import find_device
    rooms = rooms_by_key(project)
    for pa, entry in entries.items():
        device = find_device(project, pa)
        target = rooms.get(entry.get("room", ""))
        if device is None or target is None:
            continue
        room = target[1]
        if device.room_id != room.id:
            # frisch aus der ETS: deren Raum als Vergleichswert festhalten
            entry["ets"] = _key_of_room_id(project, device.room_id)
            device.room_id = room.id
        _move_bedienelement(project, pa, room)


def check_rooms_after_import(project) -> int:
    """Nach einem Import mit frischer Topologie, BEVOR die Korrekturen
    angewendet werden: Steht ein Gerät laut ETS schon im korrigierten Raum,
    ist die Korrektur dort nachgeführt und entfällt. Gibt die Anzahl
    entfallener Korrekturen zurück."""
    entries = project.ets_corrections.room_by_device
    if not entries:
        return 0
    from .multi_ga_check import find_device
    rooms = rooms_by_key(project)
    done = []
    for pa, entry in entries.items():
        device = find_device(project, pa)
        target = rooms.get(entry.get("room", ""))
        if device is not None and target is not None and device.room_id == target[1].id:
            done.append(pa)
    for pa in done:
        del entries[pa]
    return len(done)


# ── Getrennte KO-Verknüpfungen ──────────────────────────────────────────

def unlink_key(physical_address: str, co_number: int, ga_addr: str) -> str:
    return f"{physical_address}|{co_number}|{ga_addr}"


def _split_unlink(key: str) -> tuple[str, int, str]:
    pa, co, ga = key.split("|", 2)
    return pa, int(co) if co.lstrip("-").isdigit() else 0, ga


def record_unlink(project, physical_address: str, co_number: int, ga_addr: str) -> None:
    """Getrennte Verknüpfung merken (nur importierte Projekte: dort bringt ein
    Re-Import sie aus der ETS zurück, solange sie dort nicht getrennt ist)."""
    if not project.topology.is_imported:
        return
    key = unlink_key(physical_address, co_number, ga_addr)
    if key not in project.ets_corrections.unlinked:
        project.ets_corrections.unlinked.append(key)


def _apply_unlinks(project) -> None:
    from .multi_ga_check import unlink_ga
    for key in project.ets_corrections.unlinked:
        unlink_ga(project, *_split_unlink(key), record=False)


@dataclass
class PendingUnlink:
    """In KNiX getrennt, in der ETS noch verbunden."""
    physical_address: str
    co_number: int
    co_name: str
    ga_address: str
    designation: str

    def text(self) -> str:
        ko = f"KO {self.co_number}" + (f" {self.co_name}" if self.co_name else "")
        ga = self.ga_address + (f" {self.designation}" if self.designation else "")
        return f"{self.physical_address} {ko}:  {ga}"


def check_unlinks_after_import(project) -> list[PendingUnlink]:
    """Nach einem Import, BEVOR die Korrekturen angewendet werden: welche in
    KNiX getrennten Verknüpfungen liefert die ETS noch? Verknüpfungen, die die
    ETS nicht mehr hat, sind dort nachgeführt -- die Korrektur entfällt."""
    from .multi_ga_check import find_device
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    pending, keep = [], []
    for key in project.ets_corrections.unlinked:
        pa, co_number, ga_addr = _split_unlink(key)
        device = find_device(project, pa)
        co = None if device is None else next(
            (c for c in device.communication_objects if c.object_number == co_number), None)
        if co is None or ga_addr not in co.connected_gas:
            continue        # in der ETS getrennt (oder Gerät/KO weg)
        keep.append(key)
        ga = by_address.get(ga_addr)
        pending.append(PendingUnlink(pa, co_number, co.name or co.object_function,
                                     ga_addr, ga.designation if ga else ""))
    project.ets_corrections.unlinked = keep
    return pending


def gewerk_display(ga) -> str:
    """Anzeige in den GA-Ansichten: "G (statt T)", wenn vom ETS-Namen abweichend."""
    original = ets_gewerk(ga)
    if ga.gewerk_code and original and ga.gewerk_code != original:
        return f"{ga.gewerk_code} (statt {original})"
    return ga.gewerk_code
