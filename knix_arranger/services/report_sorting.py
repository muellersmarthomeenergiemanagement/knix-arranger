"""
Einheitliche Sortierung fuer Berichte.

- Physikalische Adressen und Gruppenadressen numerisch (1.1.9 vor 1.1.10,
  2/0/9 vor 2/0/10); ungueltige/leere Adressen am Ende.
- Raeume in Gebaeude-Reihenfolge: Gebaeude, Fluegel und Stockwerke wie in der
  Gebaeudestruktur angelegt (UG, EG, OG, DG -- nicht alphabetisch nach
  Stockwerksname), darin nach Raumnummer numerisch, Raeume ohne Nummer
  (z.B. Verteiler) am Ende des Stockwerks.
"""
from __future__ import annotations
import re

_NUMBER_RE = re.compile(r"\d+")


def physical_address_key(address: str) -> tuple:
    try:
        return (0, tuple(int(p) for p in (address or "").split(".")))
    except ValueError:
        return (1, ())


def group_address_key(address: str) -> tuple:
    try:
        return (0, tuple(int(p) for p in (address or "").split("/")))
    except ValueError:
        return (1, ())


def room_order(areal) -> dict[str, int]:
    """Room.id -> Position in Gebaeude-Reihenfolge."""
    keyed = []
    floor_position = 0
    for building in areal.buildings:
        for wing in building.wings:
            for floor in wing.floors:
                for apartment in floor.apartments:
                    for room in apartment.rooms:
                        m = _NUMBER_RE.search(room.number or "")
                        number = (0, int(m.group())) if m else (1, 0)
                        keyed.append((floor_position, number, room.name or "", room.id))
                floor_position += 1
    keyed.sort(key=lambda k: k[:3])
    return {room_id: i for i, (*_, room_id) in enumerate(keyed)}


def sorted_rooms(areal, rooms=None) -> list:
    """Raeume (Standard: alle des Areals) in Gebaeude-Reihenfolge."""
    order = room_order(areal)
    rooms = areal.all_rooms if rooms is None else rooms
    return sorted(rooms, key=lambda r: order.get(r.id, len(order)))
