"""
Raumnummern vorschlagen und prüfen (Wizard Schritt 3, BZ-03).

Das Schema wird aus den vorhandenen Räumen gelernt: Präfix der Zone +
Stockwerkkürzel + Trennzeichen + laufende Nummer, z.B. "SEG02" (Zone
"Chalet Studio", EG), "S-EG02" oder klassisch "E01" (ohne Präfix).
"""
from __future__ import annotations
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from ..models.building import Apartment, Areal, Floor, Room, Wing
from ..utils.validators import room_number_problems


@dataclass(frozen=True)
class _Scheme:
    prefix: str   # Zonen-Präfix, z.B. "S" ("" = klassisch E01)
    sep: str      # Trennzeichen zwischen Stockwerk und Nummer ("", "-", ".")
    width: int    # Stellen der laufenden Nummer


def _scheme_of(number: str, floor_code: str) -> tuple[_Scheme, int] | None:
    """Zerlegt eine Raumnummer anhand des Stockwerkkürzels ihres Stockwerks."""
    if not floor_code:
        return None
    m = re.fullmatch(r"(.*?)" + re.escape(floor_code) + r"([.\-]?)(\d+)", number)
    if not m:
        return None
    prefix, sep, digits = m.groups()
    return _Scheme(prefix, sep, len(digits)), int(digits)


def _zone_pairs(wing: Wing, zone_name: str) -> list[tuple[Apartment, Floor]]:
    return [(apt, floor) for floor in wing.floors
            for apt in floor.apartments if apt.name == zone_name]


def _zone_schemes(wing: Wing, zone_name: str) -> Counter:
    schemes: Counter = Counter()
    for apt, floor in _zone_pairs(wing, zone_name):
        for room in apt.rooms:
            parsed = _scheme_of(room.number, floor.short_code)
            if parsed:
                schemes[parsed[0]] += 1
    return schemes


def _initial_letters(name: str) -> list[str]:
    """Kandidaten für einen neuen Zonen-Präfix: Buchstaben des Zonennamens."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    letters = [c.upper() for c in ascii_name if c.isalpha()]
    return list(dict.fromkeys(letters))


def suggest_room_number(areal: Areal, wing: Wing, apt: Apartment, floor: Floor) -> str:
    """Nächste freie Raumnummer für einen neuen Raum in Zone/Stockwerk.

    1. Schema der Zone aus ihren Räumen (auch auf anderen Stockwerken).
    2. Neue Zone in einem Projekt mit Zonen-Präfixen: erster noch freier
       Buchstabe des Zonennamens als Präfix.
    3. Sonst klassisch Stockwerkkürzel + Nummer (E01).
    Die Nummer ist im ganzen Projekt eindeutig.
    """
    schemes = _zone_schemes(wing, apt.name)
    if schemes:
        scheme = schemes.most_common(1)[0][0]
    else:
        # Andere Zonen im ganzen Areal, auch in Nebengebäuden
        others: Counter = Counter()
        used_prefixes: set[str] = set()
        for other_wing in (w for b in areal.buildings for w in b.wings):
            for zone in {a.name for f in other_wing.floors for a in f.apartments}:
                if other_wing is wing and zone == apt.name:
                    continue
                zone_schemes = _zone_schemes(other_wing, zone)
                others.update(zone_schemes)
                used_prefixes.update(s.prefix for s in zone_schemes)
        prefixed = [s for s in others.elements() if s.prefix]
        if prefixed:
            template = Counter(prefixed).most_common(1)[0][0]
            free = [c for c in _initial_letters(apt.name) if c not in used_prefixes]
            prefix = free[0] if free else ""
            scheme = _Scheme(prefix, template.sep, template.width)
        else:
            scheme = _Scheme("", "", 2)

    numbers_here = [
        parsed[1] for room in apt.rooms
        if (parsed := _scheme_of(room.number, floor.short_code))
        and parsed[0].prefix == scheme.prefix
    ]
    taken = {r.number for r in areal.all_rooms}
    n = max(numbers_here, default=0) + 1
    while True:
        number = f"{scheme.prefix}{floor.short_code}{scheme.sep}{n:0{scheme.width}d}"
        if number not in taken:
            return number
        n += 1


def room_number_warnings(areal: Areal, room: Room) -> list[str]:
    """Warnungen zu einer Raumnummer: ausserhalb des Prüfrahmens oder doppelt.

    Räume ohne Nummer (z.B. Verteiler-Pseudoräume, Schritt 3b) sind erlaubt.
    """
    if not room.number:
        return []
    warnings = list(room_number_problems(room.number))
    duplicates = [
        r for r in areal.all_rooms if r is not room and r.number == room.number
    ]
    if duplicates:
        names = ", ".join(r.name or "?" for r in duplicates)
        warnings.append(f"Raumnummer {room.number} ist bereits vergeben ({names})")
    return warnings
