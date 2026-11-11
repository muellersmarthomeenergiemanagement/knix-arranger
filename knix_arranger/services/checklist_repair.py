"""
Checklisten, deren Raum es nicht mehr gibt (FA-623, FA-624).

Entsteht z.B. beim Neuaufbau aus der ETS mit der Option «Inbetriebnahme»:
die Checklisten bleiben, die Räume bekommen neue IDs und oft neue Namen.
Prüfergebnisse gehen nie verloren, ausser der Anwender entfernt die
Checkliste ausdrücklich.

- adopt_orphan_checklists: beim Öffnen, nur Eindeutiges -- Prüfpunkte mit
  physikalischer Adresse wandern in den Raum des Geräts, verwaiste
  Checklisten ohne Ergebnis fallen weg (Abgleichen erzeugt sie neu).
- move_checklist / remove_checklist: Rechtsklick in der Validierung.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import copy
import re
import uuid

from ..models.documentation import ITEM_KIND_DEVICE, RESULT_OPEN


def is_special(room_id: str) -> bool:
    """DALI- und Verteiler-Checklisten haben keinen Raum ("__dali__",
    "__verteiler__UV1")."""
    return room_id.startswith("__")


def orphan_checklists(project) -> list:
    rooms = {r.id for r in project.all_rooms}
    return [cl for cl in project.checklists
            if cl.room_id and not is_special(cl.room_id) and cl.room_id not in rooms]


def checked_count(checklist) -> int:
    return sum(1 for i in checklist.items if i.result != RESULT_OPEN)


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-zäöü]", "", name.lower())


def suggest_room(project, checklist):
    """Raum mit demselben Namen wie die Checkliste ("02 Garage" -> Raum
    Garage), "Eingang Studio" passt zu "Eingang / Studio". Bei mehreren
    gleichnamigen Räumen entscheidet die Nummer, sonst kein Vorschlag."""
    number, _, name = checklist.room_name.strip().partition(" ")
    if not name:
        number, name = "", number
    matches = [r for r in project.all_rooms if _norm(r.name) == _norm(name)]
    if len(matches) > 1:
        matches = [r for r in matches if r.number == number]
    return matches[0] if len(matches) == 1 else None


def _rooms_by_address(project) -> dict[str, object]:
    """Physikalische Adresse -> Raum, aus Geräten und Bedienelementen."""
    rooms = {r.id: r for r in project.all_rooms}
    result = {}
    for area in project.topology.areas:
        for line in area.lines:
            for d in line.devices:
                if d.physical_address and d.room_id in rooms:
                    result[d.physical_address] = rooms[d.room_id]
    for room in project.all_rooms:
        for be in room.bedienelemente:
            if be.participant_number and not be.suppressed:
                result.setdefault(be.participant_number, room)
    return result


def _target_checklist(project, room):
    target = next((c for c in project.checklists if c.room_id == room.id), None)
    if target is None:
        from .documentation_service import DocumentationService
        target = DocumentationService(project)._create_room_checklist(room)
        project.checklists.append(target)
    return target


def _transfer(project, items, room) -> int:
    """Prüfergebnisse in die Checkliste des Raums übernehmen: auf den
    passenden Prüfpunkt (Adresse, Prüfung, GA; ohne Adresse das einzige
    Bedienelement dieses Typs), sonst als eigener Prüfpunkt. Ein Ergebnis,
    das dort schon steht, bleibt. Gibt die Zahl übernommener Ergebnisse zurück."""
    target = _target_checklist(project, room)
    moved = 0
    for item in items:
        if item.be_number:
            candidates = [t for t in target.items if t.be_number == item.be_number]
        else:
            candidates = [t for t in target.items if t.be_type == item.be_type]
            if len({t.be_number for t in candidates}) > 1:
                candidates = []
        match = next((t for t in candidates if t.check_type == item.check_type
                      and t.function_ga == item.function_ga), None)
        if match is None:
            new = copy.copy(item)
            new.id = str(uuid.uuid4())
            new.room_id, new.be_id = room.id, ""
            target.items.append(new)
        elif match.result == RESULT_OPEN:
            match.result, match.notes = item.result, item.notes
            match.checked_date, match.checked_by = item.checked_date, item.checked_by
        else:
            continue
        moved += 1
    return moved


def adopt_orphan_checklists(project) -> tuple[int, int]:
    """Beim Öffnen: Ergebnisse mit physikalischer Adresse dem Raum des Geräts
    zuordnen, verwaiste Checklisten ohne Ergebnis entfernen. Was bleibt,
    meldet die Validierung (FA-623). Gibt (übernommene Ergebnisse,
    entfernte Checklisten) zurück."""
    orphans = orphan_checklists(project)
    if not orphans:
        return 0, 0
    by_address = _rooms_by_address(project)
    rooms = {r.id: r for r in project.all_rooms}
    moved = removed = 0
    for cl in orphans:
        checked = [i for i in cl.items if i.result != RESULT_OPEN]
        by_room: dict[str, list] = {}
        for item in checked:
            room = by_address.get(item.be_number)
            if room is not None:
                by_room.setdefault(room.id, []).append(item)
        for room_id, items in by_room.items():
            moved += _transfer(project, items, rooms[room_id])
        handled = {id(i) for items in by_room.values() for i in items}
        cl.items = [i for i in checked if id(i) not in handled]
        if not cl.items:
            project.checklists.remove(cl)
            removed += 1
    return moved, removed


def drop_device_items(project, addresses: set[str]) -> int:
    """Prüfpunkte von Bedienelementen entfernen, die es im Raum nicht mehr
    gibt, weil das Gerät kein Bedienelement ist (Gateway: Chalet Vitogate
    1.1.32 stand vor 1.4.38 als «Wassermelder» mit 72 Prüfpunkten in der
    Checkliste von «01 Technik»). Nur Raum-Checklisten; die Prüfung des
    Geräts steht in der Verteiler-Checkliste. Abgezeichnete Geräteprüfungen
    gehen dorthin über, wenn der Punkt dort noch offen ist; andere
    abgezeichnete Punkte bleiben stehen. Gibt die Zahl entfernter Punkte zurück."""
    if not addresses or not project.checklists:
        return 0
    verteiler = {(i.be_number, i.check_type): i for cl in project.checklists
                 if cl.room_id.startswith("__verteiler__") for i in cl.items}
    removed = 0
    for cl in project.checklists:
        if not cl.room_id or is_special(cl.room_id):
            continue
        kept = []
        for item in cl.items:
            if item.be_number not in addresses:
                kept.append(item)
                continue
            if item.result != RESULT_OPEN:
                target = verteiler.get((item.be_number, item.check_type))
                if target is None or target.result != RESULT_OPEN \
                        or item.item_kind != ITEM_KIND_DEVICE:
                    kept.append(item)
                    continue
                target.result, target.notes = item.result, item.notes
                target.checked_date, target.checked_by = item.checked_date, item.checked_by
            removed += 1
        cl.items = kept
    return removed


def _find(project, checklist_id: str):
    return next((c for c in project.checklists if c.id == checklist_id), None)


def move_checklist(project, checklist_id: str, room_id: str) -> int:
    """Alle Ergebnisse einer Checkliste in den Raum übernehmen und die
    Checkliste entfernen. Gibt die Zahl übernommener Ergebnisse zurück."""
    cl = _find(project, checklist_id)
    room = next((r for r in project.all_rooms if r.id == room_id), None)
    if cl is None or room is None:
        return 0
    moved = _transfer(project, [i for i in cl.items if i.result != RESULT_OPEN], room)
    project.checklists.remove(cl)
    return moved


def remove_checklist(project, checklist_id: str) -> bool:
    cl = _find(project, checklist_id)
    if cl is None:
        return False
    project.checklists.remove(cl)
    return True
