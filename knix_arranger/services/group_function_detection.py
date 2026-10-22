"""
Gruppenbedienungen in importierten Projekten erkennen (FA-531).

Eine Befehls-GA, die mehrere Aktorkanäle desselben Gewerks belegt, ist eine
Gruppenbedienung -- in KNiX eine Funktion (FA-530), auch wenn sie in der ETS
niemand als solche angelegt hat ("Raum5_Licht Zentral", "LDA.OG.00.02+
LDA.OG.00.01_ea"). Daraus entstehen Vorschläge, die der Integrator bestätigt;
KNiX legt nichts selbst an.

Nicht als Gruppe gelten: HG 0 (Zentral), Rückmeldungen (MG 6/7, Status-KOs),
Bewegungsmelder-GAs ("… von pir": Sensorlogik, keine Bedienfunktion) und
GAs, die schon einer Funktion gehören. Eine übernommene Funktion plant keine
eigenen GAs: ihre GAs sind die bestehenden aus der ETS (KnixFunction.ets_gas,
GroupAddress.ets_known), sie behalten Adresse und Bezeichnung.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from ..models.ets_function import FunctionMember, KnixFunction
from .ets_function_plan import (
    PLAN_POINTS, TYPE_GEWERKE, _assignments_by_id, _element_function, _element_number,
    next_number,
)

_PIR_RE = re.compile(r"\b(pir|bwm|präsenz|praesenz|bewegung)", re.IGNORECASE)
_FEEDBACK_RE = re.compile(r"(rückmeld|rueckmeld|status|feedback|zustand)", re.IGNORECASE)
_PARENS_RE = re.compile(r"\(\s*(.*?)\s*\)")


#: Erkennung des Funktionspunkts am DPT-Text der ETS bzw. an der DPST-Nummer
_POINT_BY_DPT = (
    (("auf/ab", "dpst-1-8"), "AUF/AB"),
    (("schritt", "dpst-1-7"), "STOPP"),
    (("dimmer", "dpst-3-7"), "DIM"),
    (("prozent", "dpst-5-1"), "WERT"),
    (("schalten", "1 bit", "dpst-1-1"), "E/A"),
)


@dataclass
class GroupSuggestion:
    """Vorschlag: eine Gruppe von GAs mit denselben Aktorkanälen."""
    name: str
    function_type: str
    room: object = None              # Raum, wenn alle Mitglieder darin liegen
    zone: object = None              # sonst die gemeinsame Zone
    floor: object = None
    members: list[tuple[object, object, int]] = field(default_factory=list)  # (Raum, Zuweisung, Nr.)
    gas: dict[str, object] = field(default_factory=dict)     # Funktionspunkt -> GA
    channels: list[tuple[str, str]] = field(default_factory=list)  # (Gerät, Kanal)
    missing_channels: int = 0        # Kanäle ohne erkennbares Element

    @property
    def place(self) -> str:
        if self.room is not None:
            return " ".join(p for p in (self.room.number, self.room.name) if p)
        return f"Zone {self.zone.name}" if self.zone is not None else ""


def _point(ga, function_type: str) -> str:
    """Funktionspunkt einer Gruppen-GA: Endung der Bezeichnung, sonst DPT."""
    allowed = {p.function for p in PLAN_POINTS.get(function_type, ())}
    function = _element_function(ga)
    if function in allowed:
        return function
    text = (ga.datapoint_type or "").lower()
    for keys, point in _POINT_BY_DPT:
        if any(k in text for k in keys):
            if point == "WERT" and function_type == "FT-7":
                point = "POSITION HOEHE"
            if point == "STOPP" and function_type != "FT-7":
                continue
            if point in allowed:
                return point
    return ""


def _function_type(codes: set[str], gas: list) -> str:
    """Typ aus den Gewerken der Mitglieder (wie TYPE_GEWERKE der Planung):
    Steckdosen allein = Steckdose schalten, mit Licht gemischt = Licht
    ("Licht Zentral" mit einer Stehlampe an der Steckdose); dimmen nur, wenn
    alle dimmbar sind und eine Dimm- oder Wert-GA dabei ist."""
    if codes <= set(TYPE_GEWERKE["FT-7"]):
        return "FT-7"
    if codes <= set(TYPE_GEWERKE["FT-10"]) and "S" in codes and not codes & {"L", "LD", "LDA"}:
        return "FT-10"
    if codes <= set(TYPE_GEWERKE["FT-1"]):
        if codes <= set(TYPE_GEWERKE["FT-6"]) and any(
                _point(g, "FT-6") in ("DIM", "WERT") for g in gas):
            return "FT-6"
        return "FT-1"
    return ""


def _name(gas: list, ets_names: dict[str, str]) -> str:
    """ETS-Funktion der GAs, sonst Klartext bzw. Bezeichnung der ersten GA."""
    for ga in gas:
        if ga.address in ets_names:
            return ets_names[ga.address]
    first = gas[0].designation or gas[0].address
    m = _PARENS_RE.search(first)
    if m and m.group(1):
        return m.group(1)
    base = first.split("(", 1)[0].strip()
    base = re.sub(r"_(ea|dim|wert|move|step|hoehe|winkel)$", "", base, flags=re.IGNORECASE)
    # "Raum5_Licht Zentral" (Tastenbezeichnung der ETS) -> "Licht Zentral"
    base = re.sub(r"^Raum\d+_", "", base, flags=re.IGNORECASE)
    return base.replace("_", " ").strip()


def suggest_group_functions(project) -> list[GroupSuggestion]:
    """Vorschläge für importierte Projekte; leer bei geplanten."""
    if not project.topology.is_imported:
        return []
    from .belegungsplan_service import BelegungsplanService
    from .ets_function_service import iter_functions
    gas = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    by_id = _assignments_by_id(project)
    rows = [r for r in BelegungsplanService().generate(project).actor_rows
            if r.ga_address and r.channel_number]

    # Kanal -> Element, das ihn belegt (häufigstes über seine Element-GAs)
    votes: dict[tuple[str, str], dict[tuple[str, int], int]] = {}
    for r in rows:
        ga = gas.get(r.ga_address)
        if ga is None or not ga.assignment_id or ga.function_id:
            continue
        number = _element_number(ga)
        if number:
            key = (ga.assignment_id.removesuffix(":fb"), number)
            channel = (r.physical_address, r.channel_number)
            votes.setdefault(channel, {}).setdefault(key, 0)
            votes[channel][key] += 1
    element_of = {ch: max(v, key=v.get) for ch, v in votes.items()}

    # Befehls-GA -> Kanäle
    channels_of: dict[str, set[tuple[str, str]]] = {}
    for r in rows:
        ga = gas.get(r.ga_address)
        if (ga is None or ga.main_group == 0 or ga.central == "true" or ga.function_id
                or ga.middle_group in (6, 7) or _PIR_RE.search(ga.designation or "")
                or _FEEDBACK_RE.search(f"{r.function_name} {r.co_function}")):
            continue
        channels_of.setdefault(r.ga_address, set()).add((r.physical_address, r.channel_number))

    # GAs mit denselben Kanälen bilden eine Gruppe (Schalten/Dimmen/Wert)
    groups: dict[frozenset, list] = {}
    for address, channels in channels_of.items():
        if len(channels) > 1:
            groups.setdefault(frozenset(channels), []).append(gas[address])

    ets_names = {ref.address: function.name
                 for _f, _r, function in iter_functions(project) for ref in function.refs}
    existing = {frozenset((m.assignment_id, m.element_number) for m in f.members)
                for f in getattr(project, "functions", [])}
    room_place = {}
    for floor in project.areal.all_floors:
        for apartment in floor.apartments:
            for room in apartment.rooms:
                room_place[room.id] = (floor, apartment)

    result = []
    for channels, group_gas in groups.items():
        elements = []
        missing = 0
        for channel in sorted(channels):
            element = element_of.get(channel)
            # Nummer aus der ETS-Bezeichnung über der Anzahl in KNiX: kein Element
            if (element is None or element[0] not in by_id
                    or element[1] > by_id[element[0]][1].count):
                missing += 1
            elif element not in elements:
                elements.append(element)
        if len(elements) < 2 or frozenset(elements) in existing:
            continue
        members = [(by_id[a][0], by_id[a][1], n) for a, n in elements]
        codes = {assignment.gewerk_code for _r, assignment, _n in members}
        group_gas.sort(key=lambda g: (g.main_group, g.middle_group, g.sub_group))
        function_type = _function_type(codes, group_gas)
        if not function_type:
            continue
        points = {}
        for ga in group_gas:
            point = _point(ga, function_type)
            if point and point not in points:
                points[point] = ga
        if not points:
            continue
        rooms = {room.id for room, _a, _n in members}
        places = [room_place[r] for r in rooms if r in room_place]
        zones = {zone.id for _floor, zone in places}
        if len(places) != len(rooms) or len(zones) != 1:
            continue   # über mehrere Zonen: Funktionen bleiben bei Raum/Zone
        suggestion = GroupSuggestion(
            name=_name(group_gas, ets_names), function_type=function_type,
            members=members, gas=points, channels=sorted(channels),
            missing_channels=missing)
        suggestion.floor, suggestion.zone = places[0]
        if len(rooms) == 1:
            suggestion.room = members[0][0]
        result.append(suggestion)
    result.sort(key=lambda s: (s.floor.name if s.floor else "", s.place, s.name))
    return result


def check_groups(project) -> list:
    """FA-531: Hinweis auf erkannte, noch nicht übernommene Gruppenbedienungen
    (in KNiX zu erledigen, nicht in der ETS-Arbeitsliste)."""
    suggestions = suggest_group_functions(project)
    if not suggestions:
        return []
    from .validation_engine import ValidationIssue
    places = sorted({s.place for s in suggestions if s.place})
    return [ValidationIssue(
        "info", "FA-531",
        f"{len(suggestions)} Gruppenbedienung(en) erkannt, z.B. in {', '.join(places[:3])}: "
        f"GAs, die mehrere Aktorkanäle desselben Gewerks belegen",
        "", "ETS-Funktionen › Reiter «Geplant» › «Gruppen erkennen…» – als Funktion übernehmen",
        details={"count": len(suggestions)})]


def adopt(project, suggestion: GroupSuggestion, name: str = "") -> KnixFunction:
    """Vorschlag als Funktion übernehmen: ihre GAs sind die bestehenden der
    ETS -- sie behalten Adresse und Bezeichnung, KNiX plant keine weiteren."""
    function = KnixFunction(
        name=name or suggestion.name, function_type=suggestion.function_type,
        room_id=suggestion.room.id if suggestion.room is not None else "",
        zone_id=suggestion.zone.id if suggestion.room is None else "",
        members=[FunctionMember(a.id, n) for _r, a, n in suggestion.members],
        ets_gas={point: f"{ga.address}  {ga.designation}"
                 for point, ga in suggestion.gas.items()})
    function.number = next_number(project, function)
    for point, ga in suggestion.gas.items():
        ga.function_id = function.id
        ga.function_name = point
        ga.ets_known = True
    project.functions.append(function)
    return function
