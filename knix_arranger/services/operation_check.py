"""
Elemente ohne Bedienung (FA-619).

Ein schaltbares Element (Licht, Steckdose, Beschattung) eines geplanten
Projekts, das keine Taste, kein Präsenzmelder, keine Szene und keine
Zeitsteuerung anspricht, ist meist vergessen -- z.B. Licht Technik, das in
Wirklichkeit vom Taster in der Waschküche geschaltet wird, dort aber noch
nicht zugewiesen ist. Zentrale Funktionen (HG 0) zählen nicht: "Alles aus"
schaltet ein Licht nicht ein.

Ein Element ist (Raum, Gewerk, Elementnummer), wie in den Gruppenadressen
(GroupAddress.room_id / gewerk_code / element_number).
"""
from __future__ import annotations

from dataclasses import dataclass

#: Gewerke, die man von Hand bedient
OPERABLE_GEWERKE = frozenset({
    "L", "LD", "LDA", "LC", "LCT", "LCW", "DMX",   # Licht
    "S", "SD",                                    # Steckdosen
    "J", "R", "M", "T",                           # Beschattung, Vorhang
})

# Befehl zuerst, damit die Meldung die Adresse zeigt, die man zuweist
_COMMAND_FUNCTIONS = ("E/A", "AUF/AB")


@dataclass
class UnoperatedElement:
    gewerk_code: str
    room_id: str
    element_number: int
    ga: object          # GroupAddress, Befehl des Elements


def _element(ga) -> tuple[str, str, int]:
    return ga.room_id, ga.gewerk_code, ga.element_number


def unoperated_elements(project) -> list[UnoperatedElement]:
    """Schaltbare Elemente ohne Bedienung; nur für mit KNiX geplante Projekte
    (importierten fehlt oft die Angabe, wer bedient)."""
    if project.topology.is_imported:
        return []
    all_gas = project.group_addresses.all_addresses()
    elements: dict[tuple, list] = {}
    for ga in all_gas:
        if ga.gewerk_code in OPERABLE_GEWERKE and ga.room_id and not ga.is_placeholder:
            elements.setdefault(_element(ga), []).append(ga)
    if not elements:
        return []

    by_designation = {ga.designation: ga for ga in all_gas if ga.designation}
    by_address = {ga.address: ga for ga in all_gas}
    by_id = {ga.id: ga for ga in all_gas}
    operated: set[tuple] = set()

    # Taster und Präsenzmelder, auch mit Funktionen aus anderen Räumen
    for room in project.all_rooms:
        for be in room.bedienelemente:
            if be.suppressed:
                continue
            for sf in be.funktionen:
                operated.add((sf.source_room_id or room.id, sf.gewerk_code, sf.element_number))
            for fa in be.function_assignments:
                ga = by_designation.get(fa.function_ga)
                if ga is not None:
                    operated.add(_element(ga))

    # Szenen: Aktionen auf die GA eines Elements
    for scene in project.scenes:
        for action in scene.actions:
            ga = by_address.get(action.ga_address) or by_designation.get(action.group_address)
            if ga is not None:
                operated.add(_element(ga))

    # Aktive Zeitprogramme
    for program in project.time_programs:
        if not program.active:
            continue
        for _dp, sp in program.all_switch_points:
            ga = by_id.get(sp.target_ga_id)
            if ga is not None:
                operated.add(_element(ga))

    result = []
    for key, gas in elements.items():
        if key in operated:
            continue
        command = next((g for f in _COMMAND_FUNCTIONS for g in gas if g.function_name == f),
                       None) or min(gas, key=lambda g: (g.main_group, g.middle_group, g.sub_group))
        result.append(UnoperatedElement(key[1], key[0], key[2], command))
    result.sort(key=lambda u: (u.ga.main_group, u.ga.middle_group, u.ga.sub_group))
    return result
