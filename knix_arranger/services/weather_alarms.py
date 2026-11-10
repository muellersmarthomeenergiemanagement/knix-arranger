"""
Wetteralarme auf den Sonnenschutz-Aktoren (FA-644).

Die Wetterstation (Gewerk W) meldet Wind, Regen und Frost je auf einer GA.
Schützen kann sie nur, wenn diese GAs auf den Sicherheits-KOs der Jalousie-,
Rollladen- und Markisenkanäle liegen -- sonst fährt bei Sturm nichts hoch.
KNiX legt sie deshalb im Belegungsplan auf jeden dieser Kanäle (wie die
Funktions-GAs zusätzlich zu den GAs des Elements); die KO-Zuordnung schlägt
das Sicherheits-KO vor.

Welche Alarme je Gewerk: wie im Chalet Franziska ausgeführt -- Jalousie und
Rollladen Wind und Frost, Markise zusätzlich Regen. Weglassen je Element
über GewerkAssignment.omitted_functions (Innenjalousie, Aktor ohne drittes
Sicherheits-KO).
"""
from __future__ import annotations

import re

WIND, RAIN, FROST = "WIND ALARM", "REGEN", "FROST ALARM"
ALARM_FUNCTIONS = (WIND, RAIN, FROST)

#: Gewerk -> Alarme, die seine Kanäle brauchen
ALARMS_BY_GEWERK: dict[str, tuple[str, ...]] = {
    "J": (WIND, FROST),
    "R": (WIND, FROST),
    "M": (WIND, RAIN, FROST),
}

#: Wort im Herstellertext eines KOs, das einen bestimmten Alarm nennt
#: (nicht «Window», «Regelung», «Training»)
ALARM_WORDS = {
    WIND: re.compile(r"\bwind(?!ow)|\bvent\b", re.IGNORECASE),
    RAIN: re.compile(r"\bregen|\brain(?!ing)|\bpluie", re.IGNORECASE),
    FROST: re.compile(r"\bfrost|\bgel\b", re.IGNORECASE),
}


def station_gas(project, structure=None) -> dict[str, object]:
    """Alarm -> GA der Wetterstation (die erste, wenn es mehrere gibt)."""
    structure = structure if structure is not None else project.group_addresses
    result: dict[str, object] = {}
    for ga in structure.all_addresses():
        if (ga.gewerk_code == "W" and not ga.is_placeholder
                and ga.planned_function in ALARM_FUNCTIONS):
            result.setdefault(ga.planned_function, ga)
    return result


def element_alarms(room, gewerk_code: str, element_number: int,
                   stations: dict[str, object]) -> list[tuple[str, object]]:
    """(Alarm, GA der Wetterstation) für ein Element, ohne die weggelassenen."""
    wanted = ALARMS_BY_GEWERK.get(gewerk_code, ())
    if not wanted or not stations:
        return []
    assignment = next((a for a in room.gewerk_assignments
                       if a.gewerk_code == gewerk_code), None)
    omitted = set(assignment.omitted_functions.get(element_number, [])) if assignment else set()
    return [(alarm, stations[alarm]) for alarm in wanted
            if alarm in stations and alarm not in omitted]


def names_other_alarm(text: str, function: str) -> bool:
    """Nennt der KO-Text einen anderen Alarm als den gesuchten? («Regenalarm»
    ist kein Platz für den Windalarm; «Sicherheit 1, Alarm» passt für jeden.)"""
    if function not in ALARM_WORDS:
        return False
    text = text or ""
    if ALARM_WORDS[function].search(text):
        return False
    return any(pattern.search(text) for other, pattern in ALARM_WORDS.items()
               if other != function)


def protected_elements(project) -> list[tuple]:
    """(Raum, Zuweisung, Element) aller Sonnenschutz-Elemente, die einen
    Windalarm brauchen (nicht weggelassen)."""
    result = []
    for room in project.all_rooms:
        for assignment in room.gewerk_assignments:
            if WIND not in ALARMS_BY_GEWERK.get(assignment.gewerk_code, ()):
                continue
            for nr in range(1, assignment.count + 1):
                if WIND not in assignment.omitted_functions.get(nr, []):
                    result.append((room, assignment, nr))
    return result


_SAFETY_KO = re.compile(r"alarm|sicherheit|safety|s[eé]curit", re.IGNORECASE)


def _is_safety_ko(co) -> bool:
    from .actor_channels import _dpt_key, _is_feedback
    if _is_feedback(co):
        return False
    return (_dpt_key(co.data_type) == ("1", "5")
            or bool(_SAFETY_KO.search(f"{co.name or ''} {co.object_function or ''}")))


def unprotected_channels(project) -> list[tuple]:
    """Importiert: (Gerät, Anzahl) der Aktoren mit Sonnenschutz-Kanälen in
    Betrieb (Fahrbefehl verknüpft), deren Sicherheits-KOs alle ohne GA sind."""
    from .actor_channels import co_function
    from .ets_function_plan import _ko_groups
    result = []
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if device.device_type != "actor":
                    continue
                count = 0
                for channel in _ko_groups(device):
                    moving = any(co.connected_gas
                                 and co_function(co, {"AUF/AB": "DPST-1-8"}) == "AUF/AB"
                                 for co in channel)
                    safety = [co for co in channel if _is_safety_ko(co)]
                    if moving and safety and not any(co.connected_gas for co in safety):
                        count += 1
                if count:
                    result.append((device, count))
    return result
