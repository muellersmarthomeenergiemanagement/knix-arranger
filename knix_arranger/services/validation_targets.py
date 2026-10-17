"""
Sprungziele einer Validierungsmeldung (FA-615a): wo in KNiX man sie korrigiert.

Das erste Ziel ist das Hauptziel (Doppelklick), die übrigen stehen im
Kontextmenü. Abgeleitet aus Regel, Adressfeld (GA, physikalische Adresse,
Linie, Raumnummer, "HG n") und Meldungstext.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Art des Ziels -> Ansicht im Hauptfenster
GA = "ga"                  # Gruppenadressen-Baum, key = Adresse
DEVICE = "device"          # Topologie, key = physikalische Adresse
LINE = "line"              # Topologie, key = "Bereich.Linie"
ROOM = "room"              # Gebäude, key = Raum-id
BAUHERR = "bauherr"        # Bauherrenberatung, key = Raum-id
FLOOR = "floor"            # Gebäude, key = Hauptgruppe
VIEW = "view"              # Ansicht ohne Auswahl, key = Ansichts-Schlüssel
KEYS = "keys"              # Dialog «Tasten anpassen» (FA-629), key = physikalische Adresse

_GA_RE = re.compile(r"^\d{1,2}/\d/\d{1,3}$")
_PA_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{1,3}$")
_LINE_RE = re.compile(r"^\d{1,2}\.\d{1,2}$")
_HG_RE = re.compile(r"^HG (\d+)$")
_PA_IN_TEXT = re.compile(r"(?<![\d./])(\d{1,2}\.\d{1,2}\.\d{1,3})(?![\d./])")
_GA_IN_TEXT = re.compile(r"(?<![\d./])(\d{1,2}/\d/\d{1,3})(?![\d./])")

_VIEW_LABELS = {
    "scenes": "Szenen öffnen",
    "time_programs": "Zeitsteuerung öffnen",
    "material_list": "Materialliste öffnen",
    "gewerke": "Gewerke öffnen",
    "topology": "Topologie öffnen",
    "building": "Gebäude öffnen",
}

# Regeln, die nur in einer Ansicht korrigiert werden
_RULE_VIEWS = {
    "FA-1813": "scenes",
    "FA-3308b": "time_programs",
    "FA-3306": "time_programs",
    "FA-620": "gewerke",
    "FA-626": "material_list",
    "FA-622": "material_list",
}


@dataclass(frozen=True)
class Target:
    kind: str
    key: str
    label: str


def _ga_target(address: str) -> Target:
    return Target(GA, address, f"GA {address} in den Gruppenadressen zeigen")


def _device_target(pa: str) -> Target:
    return Target(DEVICE, pa, f"Gerät {pa} in der Topologie zeigen")


def _room_targets(project, room) -> list[Target]:
    label = f"{room.number} {room.name}".strip()
    return [Target(BAUHERR, room.id, f"Raum {label} in der Bauherrenberatung öffnen"),
            Target(ROOM, room.id, f"Raum {label} im Gebäude zeigen")]


def targets_for(issue: dict, project) -> list[Target]:
    """Sprungziele einer Meldung (Felder wie ValidationView._issue_fields)."""
    rule = issue.get("rule_id", "")
    address = (issue.get("address") or "").strip()
    message = issue.get("message", "")
    result: list[Target] = []

    def add(target: Target | None) -> None:
        if target is not None and target not in result:
            result.append(target)

    gas = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    devices = {d.physical_address for area in project.topology.areas
               for line in area.lines for d in line.devices if d.physical_address}
    rooms = {room.id: room for room in project.all_rooms}

    if rule == "FA-619" and address in gas:
        # Element ohne Bedienung: Taste zuweisen oder in eine Szene aufnehmen
        from .operation_check import switched_elements
        ga = gas[address]
        key = (ga.room_id, ga.gewerk_code, ga.element_number)
        if ga.gewerk_code == "SF" or key in switched_elements(project):
            add(Target(VIEW, "scenes", _VIEW_LABELS["scenes"]))
        room = rooms.get(ga.room_id)
        if room is not None:
            add(_room_targets(project, room)[0])
        add(_ga_target(address))
    if rule in _RULE_VIEWS:
        add(Target(VIEW, _RULE_VIEWS[rule], _VIEW_LABELS[_RULE_VIEWS[rule]]))
    # Zu wenige Tasten (FA-629): Dialog mit den Wegen, dann Bauherrenberatung
    room_id = (issue.get("details") or {}).get("room_id")
    if rule == "FA-629" and address in devices:
        add(Target(KEYS, address, f"Tasten anpassen ({address})…"))
    if rule == "FA-629" and room_id in rooms:
        add(_room_targets(project, rooms[room_id])[0])
    # Taster ohne Funktion bzw. doppelt belegte Taste: Bauherrenberatung zuerst
    if rule in ("FA-631", "FA-632") and room_id in rooms:
        add(_room_targets(project, rooms[room_id])[0])

    missing_ga = None
    if _GA_RE.match(address):
        if address in gas:
            add(_ga_target(address))
        else:
            missing_ga = address      # z.B. Lücke im Block (FA-605)
    elif _PA_RE.match(address):
        if address in devices:
            add(_device_target(address))
    elif _LINE_RE.match(address):
        add(Target(LINE, address, f"Linie {address} in der Topologie zeigen"))
    elif (m := _HG_RE.match(address)):
        add(Target(FLOOR, m.group(1), f"Stockwerk mit HG {m.group(1)} im Gebäude zeigen"))
    elif address:
        for room in project.all_rooms:
            if room.number == address:
                for target in _room_targets(project, room)[::-1]:
                    add(target)          # Raum im Gebäude zuerst (Linie, Gewerke)
                if rule == "FA-625":
                    add(Target(VIEW, "topology", _VIEW_LABELS["topology"]))
                break

    # Weitere Adressen aus dem Meldungstext, z.B. das Gerät bei FA-611/FA-614
    for pa in _PA_IN_TEXT.findall(message):
        if pa in devices:
            add(_device_target(pa))
    for ga_address in _GA_IN_TEXT.findall(message):
        if ga_address in gas:
            add(_ga_target(ga_address))
    if missing_ga is not None:
        main, middle, _sub = missing_ga.split("/")
        add(Target(GA, missing_ga, f"Mittelgruppe {main}/{middle} in den Gruppenadressen zeigen"))
    return result
