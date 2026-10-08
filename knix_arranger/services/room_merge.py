"""
Räume zusammenführen: ein Raum geht samt Gewerken, Bedienelementen und
Verteilern in einem anderen auf und wird danach gelöscht.

Nur für geplante Projekte. Die Gruppenadressen behalten ihre Adresse; die
Neuberechnung danach benennt sie auf den Zielraum um. Gleiche Gewerke in
beiden Räumen werden zu einer Zuweisung zusammengezählt (Elemente des
Quellraums hinten angehängt), Tastereinheiten des Quellraums erhalten
die nächsten freien Nummern im Zielraum.

Reine Datenoperation ohne Qt; die Ansicht löst danach die übliche
Neuberechnung aus.
"""
from __future__ import annotations

import dataclasses

from ..models.building import GewerkAssignment, Room
from .structure_move import MAX_GEWERK_COUNT

# Felder, die auf einen Raum verweisen (Tasten, DALI-Geräte, Checklisten,
# Szenen-Geltungsbereich, Geräte der Topologie)
_ROOM_REF_FIELDS = ("room_id", "source_room_id", "scope_id")


def merge_problem(project, source: Room, target: Room) -> str:
    """Grund, warum die Räume nicht zusammengeführt werden können, sonst ""."""
    if source is target:
        return "Quell- und Zielraum sind derselbe Raum."
    if project.topology.is_imported:
        return ("Bei aus der ETS importierten Projekten ergeben sich die Räume "
                "aus der ETS. Dort zusammenführen und neu importieren.")
    for src in source.gewerk_assignments:
        tgt = _same_gewerk(target, src.gewerk_code)
        if tgt is None:
            continue
        if tgt.count + src.count > MAX_GEWERK_COUNT:
            return (f"Gewerk {src.gewerk_code}: zusammen {tgt.count + src.count} "
                    f"Elemente, höchstens {MAX_GEWERK_COUNT} möglich.")
        if (tgt.linked_product or {}) != (src.linked_product or {}) \
                or tgt.sensor_type_override != src.sensor_type_override:
            return (f"Gewerk {src.gewerk_code} hat in beiden Räumen ein anderes "
                    f"Produkt oder einen anderen Sensortyp.")
    return ""


def merge_rooms(project, source: Room, target: Room) -> None:
    """source in target aufgehen lassen und source löschen.
    Vorher merge_problem() prüfen."""
    problem = merge_problem(project, source, target)
    if problem:
        raise ValueError(problem)

    _rename_dali_groups(project, source, target)

    # Tastereinheiten des Quellraums hinter die des Zielraums
    taster_offset = _taster_count(target)
    source_tasters = _taster_count(source)
    for be in source.bedienelemente:
        be.taster_index += taster_offset
    moved_bes = list(source.bedienelemente)
    target.bedienelemente.extend(moved_bes)
    moved_ids = {id(be) for be in moved_bes}
    source.bedienelemente = []
    for key, te_type in source.te_types.items():
        target.te_types[str(int(key) + taster_offset)] = te_type
    if target.te_count or source.te_count:
        target.te_count = taster_offset + source_tasters

    # Gewerke: gleiche zusammenzählen, übrige übernehmen. Elementnummern
    # des Quellraums verschieben sich um die Anzahl im Zielraum.
    element_offset: dict[str, int] = {}
    for src in source.gewerk_assignments:
        src.taster_indices = [i + taster_offset for i in src.taster_indices]
        tgt = _same_gewerk(target, src.gewerk_code)
        if tgt is None:
            target.gewerk_assignments.append(src)
            continue
        element_offset[src.gewerk_code] = tgt.count
        _append_elements(tgt, src)

    # Tasten, die Elemente des Quellraums bedienen: Elementnummer nachführen
    # (den Raumverweis hängt _replace_room_refs um)
    for room in project.all_rooms:
        for be in room.bedienelemente:
            for sf in be.funktionen:
                if not sf.gewerk_code:
                    continue
                if sf.source_room_id == source.id or (
                        not sf.source_room_id and id(be) in moved_ids):
                    sf.element_number += element_offset.get(sf.gewerk_code, 0)

    target.verteiler.extend(source.verteiler)
    target.bauherr_notes = "\n".join(
        t for t in (target.bauherr_notes, source.bauherr_notes) if t.strip())

    _move_topology(project, source, target)
    _replace_room_refs(project, source.id, target.id)
    # Im Zielraum sind Verweise auf ihn selbst eigene Elemente
    for be in target.bedienelemente:
        for sf in be.funktionen:
            if sf.source_room_id == target.id:
                sf.source_room_id = ""

    for apt in (a for f in project.areal.all_floors for a in f.apartments):
        if source in apt.rooms:
            apt.rooms.remove(source)


def _taster_count(room: Room) -> int:
    return max(
        [room.te_count]
        + [be.taster_index for be in room.bedienelemente]
        + [i for g in room.gewerk_assignments for i in g.taster_indices],
    )


def _same_gewerk(room: Room, code: str) -> GewerkAssignment | None:
    return next((g for g in room.gewerk_assignments if g.gewerk_code == code), None)


def _append_elements(tgt: GewerkAssignment, src: GewerkAssignment) -> None:
    offset = tgt.count
    labels = list(tgt.element_labels) + [""] * (offset - len(tgt.element_labels))
    tgt.set_element_labels(labels + list(src.element_labels))
    for nr, links in src.all_element_links().items():
        tgt.element_links(nr + offset).update(links)
    tgt.extra_entries.extend(src.extra_entries)
    tgt.datasheets.extend(d for d in src.datasheets if d not in tgt.datasheets)
    tgt.taster_indices = sorted(set(tgt.taster_indices) | set(src.taster_indices))
    tgt.count += src.count


def _move_topology(project, source: Room, target: Room) -> None:
    source_label = f"{source.number} {source.name}".strip()
    target_label = f"{target.number} {target.name}".strip()
    target_on_line = any(target.id in l.assigned_room_ids
                         for a in project.topology.areas for l in a.lines)
    for area in project.topology.areas:
        for line in area.lines:
            if source.id in line.assigned_room_ids:
                line.assigned_room_ids.remove(source.id)
                if not target_on_line:
                    line.assigned_room_ids.append(target.id)
                    target_on_line = True
            for device in line.devices:
                if device.installation_location == source_label:
                    device.installation_location = target_label


def _rename_dali_groups(project, source: Room, target: Room) -> None:
    """DALI-Gruppen des Quellraums tragen dessen Namen vorne ("Halle Spots")."""
    source_gas = {ga.address for ga in project.group_addresses.all_addresses()
                  if ga.room_id == source.id}
    prefix = f"{source.name} "
    for gateway in project.dali_configs.values():
        for group in gateway.groups:
            if group.ga_switch in source_gas and group.name.startswith(prefix):
                group.name = f"{target.name} {group.name[len(prefix):]}"


def _replace_room_refs(project, old_id: str, new_id: str) -> None:
    """Alle Verweise auf den Quellraum im ganzen Projekt umhängen."""
    seen: set[int] = set()

    def walk(obj) -> None:
        if id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, dict):
            for value in obj.values():
                walk(value)
        elif isinstance(obj, (list, tuple, set)):
            for value in obj:
                walk(value)
        elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            for f in dataclasses.fields(obj):
                value = getattr(obj, f.name)
                if f.name in _ROOM_REF_FIELDS and value == old_id:
                    setattr(obj, f.name, new_id)
                elif isinstance(value, (list, dict, tuple, set)) \
                        or dataclasses.is_dataclass(value):
                    walk(value)

    walk(project)
