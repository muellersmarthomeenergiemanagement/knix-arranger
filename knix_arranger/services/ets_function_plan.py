"""
Funktionen planen (FA-530, FA-637).

Eine Funktion bedient mehrere Elemente gemeinsam, z.B. "Fensterfront" für
drei Jalousien eines Raums: Sie hat eigene GAs, die zusätzlich zu den GAs
der Elemente auf deren Aktorkanäle verknüpft werden. Ein Taster auf der
Funktions-GA bedient den ganzen Bezirk, die Einzelbedienung bleibt.

Funktionen sind reine Befehlsadressen, ohne Rückmeldung (User
2026-10-21) -- welcher Zustand sollte bei drei Kanälen auch gelten. Ihre
Elemente werden zuerst bestimmt (Gewerke); erst daraus ergibt sich, auf
welchem Aktorkanal die Funktions-GAs verknüpft werden.

Adressen: HG des Stockwerks, MG des Gewerks, ab UG 200 je Funktion ein
5er-Block (etwas abgesetzt von den Blöcken der Elemente), Bezeichnung
"J_DG_04_F1 AUF/AB (Fensterfront)". Die ETS legt die GAs einer neuen
Funktion in die höchste HG (geplant: HG 13 «ETS-Funktionen»); der Integrator
löscht sie und ordnet die KNiX-GAs zu (ETS-Arbeitsliste).
Tasten bedienen eine Funktion über SensorFunktion.function_id.

Funktions-GAs tragen GroupAddress.function_id. Nach einem .knxproj-
Re-Import (frisch eingelesene GAs) stellt restore_function_ids sie über die
Bezeichnung wieder her.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from ..models.ets_function import KnixFunction
from ..models.group_address import GroupAddress
from .ets_function_service import FUNCTION_TYPES, type_label
from .naming_engine import element_code, label_floor_code


@dataclass(frozen=True)
class PlanPoint:
    function: str      # KNiX-Funktion, z.B. "E/A" (wie bei den Elementen)
    role: str          # Rolle in der ETS; "" = kein Funktionspunkt der ETS
    dpt: str
    offset: int        # Platz im 5er-Block
    label: str = ""    # Bezeichnung, wenn die ETS den Punkt nicht kennt


_E_A = PlanPoint("E/A", "SwitchOnOff", "DPST-1-1", 0)

#: Funktionstyp -> Funktionspunkte (nur Befehle). Positionen beim Sonnen-
#: schutz z.B. für "Raum beschatten" von einem Sensor aus, Sperren z.B. für
#: Fensterputzen einer Fassade; die ETS-Funktion kennt beide nicht (ihre
#: Position/Lamellenstellung sind Rückmeldungen). Heizung: nur die
#: Betriebsart (Komfort/Standby/Nacht/Frost für eine Zone).
PLAN_POINTS: dict[str, tuple[PlanPoint, ...]] = {
    "FT-1": (_E_A,),
    "FT-10": (_E_A,),
    "FT-6": (_E_A,
             PlanPoint("DIM", "DimmingControl", "DPST-3-7", 1),
             PlanPoint("WERT", "DimmingValue", "DPST-5-1", 2)),
    "FT-7": (PlanPoint("AUF/AB", "MoveUpDown", "DPST-1-8", 0),
             PlanPoint("STOPP", "StopStepUpDown", "DPST-1-7", 1),
             PlanPoint("POSITION HOEHE", "", "DPST-5-1", 2, "Position Höhe"),
             PlanPoint("POSITION LAMELLEN", "", "DPST-5-1", 3, "Position Lamellen"),
             PlanPoint("SPERREN", "", "DPST-1-1", 4, "Sperren")),
    "FT-9": (PlanPoint("UMSCHALTEN BETRIEBSART", "HVACMode", "DPST-20-102", 0),),
}
#: Bezeichnung im Dialog, wo sie von der ETS abweicht
PLAN_TYPE_LABELS = {"FT-9": "Heizung (Betriebsart)"}


def in_ets_function(function_type: str, function_name: str) -> bool:
    """Funktionspunkt, den die ETS-Funktion kennt (dort zuzuordnen)."""
    return any(p.function == function_name and p.role
               for p in PLAN_POINTS.get(function_type, ()))
#: Planbare Typen in der Reihenfolge der Auswahl
PLAN_TYPES = ("FT-7", "FT-1", "FT-6", "FT-10", "FT-9")
TYPE_MIDDLE_GROUP = {"FT-1": 0, "FT-6": 0, "FT-10": 0, "FT-7": 1, "FT-9": 2}
#: Gewerke, deren Elemente Mitglied sein können
TYPE_GEWERKE = {
    "FT-1": ("L", "LD", "LDA", "S", "SD"),
    "FT-6": ("LD", "LDA", "SD"),
    "FT-10": ("S", "SD"),
    "FT-7": ("J", "R", "M"),
    "FT-9": ("H",),
}
_DEFAULT_CODE = {"FT-1": "L", "FT-6": "LD", "FT-10": "S", "FT-7": "J", "FT-9": "H"}


def plan_type_label(function_type: str) -> str:
    return PLAN_TYPE_LABELS.get(function_type) or type_label(function_type)
FIRST_SUB = 200
BLOCK = 5

# "J_DG_04_F1 AUF/AB (Fensterfront)" -> Gewerk, Ort (mit Stockwerk), Nummer,
# Funktion; vor Version 1.4.15 ohne Stockwerk ("J_04_F1")
_FUNCTION_DESIGNATION_RE = re.compile(
    r"^([A-Z]{1,3})_([A-Z0-9][A-Z0-9.\-]*(?:_[A-Z0-9][A-Z0-9.\-]*)?)_F(\d{1,2})"
    r"\s+(.+?)(?:\s+\(.*\))?$")


# ── Ort und Mitglieder ────────────────────────────────────────────────────

@dataclass
class Location:
    floor: object
    room: object = None        # Raum, oder None bei einer Zone
    zone: object = None        # Apartment

    @property
    def rooms(self) -> list:
        return [self.room] if self.room is not None else list(self.zone.rooms)

    @property
    def code(self) -> str:
        """Ortsteil der Bezeichnung: Stockwerk und Raumnummer ("DG_04", "EG01"
        enthält es schon), bei einer Zone das Stockwerk."""
        if self.room is not None:
            number = self.room.number or "00"
            floor = label_floor_code(self.floor.short_code, number)
            return f"{floor}_{number}" if floor else number
        return self.floor.short_code or "Z"

    @property
    def label(self) -> str:
        if self.room is not None:
            return " ".join(p for p in (self.room.number, self.room.name) if p) or "Raum"
        return f"Zone {self.zone.name}".strip()


def locate(project, function: KnixFunction) -> Location | None:
    for floor in project.areal.all_floors:
        for apartment in floor.apartments:
            if function.zone_id and apartment.id == function.zone_id:
                return Location(floor, None, apartment)
            for room in apartment.rooms:
                if function.room_id and room.id == function.room_id:
                    return Location(floor, room, apartment)
    return None


@dataclass
class MemberElement:
    room: object
    assignment: object
    element_number: int
    floor_code: str = ""      # Stockwerk-Kürzel; Raumnummern beginnen je Stockwerk neu

    @property
    def label(self) -> str:
        """"J_DG_04_02 (Schlafen)": Gewerk, Stockwerk, Raum, Element."""
        label = self.assignment.element_label(self.element_number)
        code = element_code(self.assignment.gewerk_code,
                            label_floor_code(self.floor_code, self.room.number),
                            self.room.number, self.element_number)
        return f"{code} ({label or self.room.name})"


def member_candidates(location: Location, function_type: str) -> list[MemberElement]:
    """Elemente des Orts, die eine Funktion dieses Typs mitbedienen können."""
    codes = TYPE_GEWERKE.get(function_type, ())
    result = []
    for room in location.rooms:
        for assignment in room.gewerk_assignments:
            if assignment.gewerk_code not in codes:
                continue
            for nr in range(1, assignment.count + 1):
                result.append(MemberElement(room, assignment, nr,
                                            location.floor.short_code))
    return result


def _assignments_by_id(project) -> dict[str, tuple]:
    """GewerkAssignment.id -> (Raum, Zuweisung, Stockwerk-Kürzel)."""
    by_id = {}
    for floor in project.areal.all_floors:
        for apartment in floor.apartments:
            for room in apartment.rooms:
                for assignment in room.gewerk_assignments:
                    by_id[assignment.id] = (room, assignment, floor.short_code)
    return by_id


def _element_number(ga) -> int:
    """Elementnummer einer GA. Importierte GAs tragen nur die Zuweisung, die
    Nummer steht in ihrer Bezeichnung ("J.DG.04.01_move"); GAs mehrerer
    Elemente ("J.OG.00.01+J.DG.00.02_move") gehören keinem einzelnen (0)."""
    if ga.element_number:
        return ga.element_number
    from .gewerk_service import GewerkService
    from .naming_engine import NamingEngine
    matched = GewerkService._match_ga_designation(ga.designation or "")
    if matched is not None:
        if matched[4]:
            return 0
        return int(matched[3]) if matched[3].isdigit() else 0
    return NamingEngine.parse_designation(ga.designation)["element_number"]


#: Endung importierter Bezeichnungen ("J.DG.04.01_move") -> Funktion der
#: Planung, nur Befehle wie in PLAN_POINTS
_IMPORTED_SUFFIXES = {
    "AUF/AB": ("move", "aufab", "auf_ab", "fahren", "endlage", "updown"),
    "STOPP": ("step", "stop", "stopp", "schritt"),
    "POSITION HOEHE": ("hoehe", "höhe", "position", "pos"),
    "POSITION LAMELLEN": ("winkel", "lamellen", "lamelle", "slat"),
    "SPERREN": ("sperren", "sperre", "lock"),
    "E/A": ("ea", "schalten", "switch"),
    "DIM": ("dim", "dimmen"),
    "WERT": ("wert", "value"),
    "UMSCHALTEN BETRIEBSART": ("betriebsart", "hvac", "modus"),
}
_SUFFIX_FUNCTION = {s: f for f, suffixes in _IMPORTED_SUFFIXES.items() for s in suffixes}


def _element_function(ga) -> str:
    """Funktion einer Element-GA: geplant aus dem Feld, importiert aus der
    Endung der Bezeichnung."""
    if ga.planned_function:
        return ga.planned_function
    label = (ga.designation or "").split("(", 1)[0].strip()
    return _SUFFIX_FUNCTION.get(label.rsplit("_", 1)[-1].lower(), "") if "_" in label else ""


def _element_gas(project) -> dict[tuple[str, int], dict[str, GroupAddress]]:
    """(Zuweisung, Element) -> Funktion -> Befehls-GA des Elements.
    Rückmeldungen (Variante B: MG 6/7) zählen nicht, sie tragen in
    importierten Projekten dieselbe Bezeichnung wie der Befehl."""
    imported = project.topology.is_imported
    result: dict[tuple[str, int], dict[str, GroupAddress]] = {}
    for ga in project.group_addresses.all_addresses():
        if not ga.assignment_id or ga.is_placeholder or ga.function_id:
            continue
        if imported and ga.middle_group in (6, 7):
            continue
        number = _element_number(ga)
        function = _element_function(ga)
        if number and function:
            key = (ga.assignment_id.removesuffix(":fb"), number)
            result.setdefault(key, {}).setdefault(function, ga)
    return result


def element_labels_by_address(project) -> dict[str, str]:
    """GA -> bedientes Element ("J_DG_04_01 (Schlafen)"), für die Kanäle der
    Topologie (Nummer siehe _element_number)."""
    by_id = _assignments_by_id(project)
    result = {}
    for ga in project.group_addresses.all_addresses():
        found = by_id.get(ga.assignment_id.removesuffix(":fb"))
        if found is None or ga.is_placeholder or ga.function_id:
            continue
        number = _element_number(ga)
        if number:
            room, assignment, floor_code = found
            result[ga.address] = MemberElement(room, assignment, number, floor_code).label
    return result


def floor_main_groups(project) -> dict[str, int]:
    """Stockwerk-id -> HG, in der seine GAs liegen. Importierte Projekte:
    die HG mit dem Namen des Stockwerks ("DG"), sonst die, die die meisten
    GAs seiner Räume trägt -- ohne HG 0 und 12 (zentral, ETS-Funktionen;
    im Chalet liegen dort Revox-GAs der UG-Räume). Chalet: DG in HG 4,
    nicht in der Standard-HG 7. Geplante: Floor.main_group_number."""
    from ..models.building import ETS_FUNCTION_MAIN_GROUP
    result = {f.id: f.main_group_number for f in project.areal.all_floors}
    if not project.topology.is_imported:
        return result
    from collections import Counter
    by_name = {hg.name.strip().lower(): hg.number
               for hg in project.group_addresses.main_groups if hg.name}
    named = {}
    for floor in project.areal.all_floors:
        for name in (floor.short_code, floor.name):
            if name and name.strip().lower() in by_name:
                named[floor.id] = by_name[name.strip().lower()]
                break
    floor_of = {}
    for floor in project.areal.all_floors:
        for apartment in floor.apartments:
            for room in apartment.rooms:
                for assignment in room.gewerk_assignments:
                    floor_of[assignment.id] = floor.id
    counts: dict[str, Counter] = {}
    for ga in project.group_addresses.all_addresses():
        floor_id = floor_of.get(ga.assignment_id.removesuffix(":fb"))
        if (floor_id and ga.main_group not in (0, ETS_FUNCTION_MAIN_GROUP)
                and not ga.function_id):
            counts.setdefault(floor_id, Counter())[ga.main_group] += 1
    for floor_id, counter in counts.items():
        result[floor_id] = counter.most_common(1)[0][0]
    result.update(named)
    return result


def resolve_members(project, function: KnixFunction) -> list[MemberElement | None]:
    """Mitglieder in der Reihenfolge der Funktion (None = Element entfernt)."""
    by_id = _assignments_by_id(project)
    result = []
    for member in function.members:
        found = by_id.get(member.assignment_id)
        if found is None or member.element_number > found[1].count:
            result.append(None)
        else:
            room, assignment, floor_code = found
            result.append(MemberElement(room, assignment, member.element_number, floor_code))
    return result


def next_number(project, function: KnixFunction) -> int:
    """Nächste freie Nummer "F<n>" am Ort der Funktion."""
    used = {f.number for f in project.functions if f is not function
            and f.room_id == function.room_id and f.zone_id == function.zone_id}
    n = 1
    while n in used:
        n += 1
    return n


def function_points(function: KnixFunction) -> tuple[PlanPoint, ...]:
    return PLAN_POINTS.get(function.function_type, ())


def gewerk_code(project, function: KnixFunction) -> str:
    for member in resolve_members(project, function):
        if member is not None:
            return member.assignment.gewerk_code
    return _DEFAULT_CODE.get(function.function_type, "L")


def designation(project, function: KnixFunction, point: PlanPoint,
                location: Location) -> str:
    return (f"{gewerk_code(project, function)}_{location.code}_F{function.number} "
            f"{point.function} ({function.name})")


# ── GAs der Funktionen ────────────────────────────────────────────────────

def function_gas(structure) -> list[GroupAddress]:
    return [ga for ga in structure.all_addresses() if ga.function_id]


def sync_function_gas(project, structure=None, previous: list | None = None) -> list[str]:
    """GAs aller Funktionen in die Struktur setzen. Bestehende behalten
    Adresse und id, solange ihr Platz frei ist; neue kommen in den ersten
    freien 5er-Block ab UG 200. GAs entfernter Funktionen fallen weg.
    Gibt Warnungen zurück (z.B. kein freier Block)."""
    structure = structure if structure is not None else project.group_addresses
    functions = getattr(project, "functions", [])
    if not functions and not function_gas(structure) and not previous:
        return []
    if previous is None:
        previous = function_gas(structure)
    _remove_function_gas(structure)
    old = {(ga.function_id, ga.function_name): ga for ga in previous}
    used: dict[tuple[int, int], set[int]] = {}
    for ga in structure.all_addresses():
        used.setdefault((ga.main_group, ga.middle_group), set()).add(ga.sub_group)
    # Aus der ETS eingelesene Funktions-GAs bleiben, wie sie dort stehen
    function_ids = {f.id for f in functions}
    known = [ga for ga in previous if ga.ets_known and ga.function_id in function_ids]
    for ga in known:
        _insert(structure, ga)
        used.setdefault((ga.main_group, ga.middle_group), set()).add(ga.sub_group)
    # Funktion gelöscht: ihre GAs aus der ETS bleiben als gewöhnliche GAs
    for ga in previous:
        if ga.ets_known and ga.function_id not in function_ids:
            ga.function_id, ga.ets_known = "", False
            _insert(structure, ga)
            used.setdefault((ga.main_group, ga.middle_group), set()).add(ga.sub_group)
    known_points = {(ga.function_id, ga.function_name) for ga in known}
    main_groups = floor_main_groups(project)
    warnings = []
    for function in functions:
        location = locate(project, function)
        # Übernommene Gruppenbedienung (FA-531): nur die GAs aus der ETS
        points = [] if function.ets_gas else [
            p for p in function_points(function)
            if (function.id, p.function) not in known_points]
        hg = main_groups.get(location.floor.id, 0) if location is not None else 0
        if location is None or not points or hg <= 0:
            continue
        mg = TYPE_MIDDLE_GROUP[function.function_type]
        targets = [(p, mg, p.offset) for p in points]

        def fits(start: int) -> bool:
            return start + BLOCK - 1 <= 255 and all(
                start + off not in used.get((hg, m), set()) for _p, m, off in targets)

        start = None
        for p, m, off in targets:
            prev = old.get((function.id, p.function))
            if prev is not None and prev.main_group == hg and prev.middle_group == m:
                candidate = prev.sub_group - off
                if candidate >= 0 and fits(candidate):
                    start = candidate
                break
        if start is None:
            start = next((s for s in range(FIRST_SUB, 256, BLOCK) if fits(s)), None)
        if start is None:
            warnings.append(f"Funktion «{function.name}»: kein freier Block ab "
                            f"UG {FIRST_SUB} in {hg}/{mg}")
            continue
        for p, m, off in targets:
            prev = old.get((function.id, p.function))
            ga = GroupAddress(id=prev.id) if prev is not None else GroupAddress()
            if prev is not None:
                for name in ("description", "comment", "security", "central", "unfiltered"):
                    setattr(ga, name, getattr(prev, name))
            ga.main_group, ga.middle_group, ga.sub_group = hg, m, start + off
            ga.designation = designation(project, function, p, location)
            ga.datapoint_type = p.dpt
            ga.gewerk_code = gewerk_code(project, function)
            ga.function_name = p.function
            ga.function_id = function.id
            _insert(structure, ga)
            used.setdefault((hg, m), set()).add(ga.sub_group)
    return warnings


def _remove_function_gas(structure) -> None:
    for hg in structure.main_groups:
        for mg in hg.middle_groups:
            mg.group_addresses = [ga for ga in mg.group_addresses if not ga.function_id]


def _insert(structure, ga: GroupAddress) -> None:
    from .address_generator import insert_ga
    insert_ga(structure, ga)
    hg = next(h for h in structure.main_groups if h.number == ga.main_group)
    mg = next(m for m in hg.middle_groups if m.number == ga.middle_group)
    mg.group_addresses.sort(key=lambda g: g.sub_group)


def restore_function_ids(project) -> int:
    """Nach einem Re-Import: Funktions-GAs über die Bezeichnung
    ("J_01_F1 AUF/AB (...)") wieder ihrer Funktion zuordnen."""
    by_key = {}
    for function in project.functions:
        location = locate(project, function)
        if location is not None:
            by_key[(location.code, function.number)] = function
            if location.room is not None:   # Bezeichnung vor 1.4.15
                by_key.setdefault((location.room.number or "00", function.number), function)
    restored = _restore_adopted(project)
    for ga in project.group_addresses.all_addresses():
        if ga.function_id:
            continue
        m = _FUNCTION_DESIGNATION_RE.match(ga.designation or "")
        if not m:
            continue
        function = by_key.get((m.group(2), int(m.group(3))))
        if function is None:
            continue
        ga.function_id = function.id
        ga.function_name = m.group(4).strip()
        ga.gewerk_code = m.group(1)
        ga.ets_known = True
        restored += 1
    return restored


def _restore_adopted(project) -> int:
    """Übernommene Gruppenbedienungen (FA-531) nach einem Re-Import: GA mit
    derselben Adresse und Bezeichnung, sonst die einzige mit der Bezeichnung
    (in der ETS verschoben). Bezeichnungen wie "Raum5_Licht Zentral" gibt es
    in mehreren Stockwerken -- dann zählt nur die Adresse."""
    by_name: dict[str, list[GroupAddress]] = {}
    for ga in project.group_addresses.all_addresses():
        if not ga.function_id:
            by_name.setdefault(" ".join((ga.designation or "").split()), []).append(ga)
    restored = 0
    for function in project.functions:
        for point, text in function.ets_gas.items():
            address, _sep, name = text.partition("  ")
            candidates = by_name.get(" ".join(name.split()), [])
            ga = next((g for g in candidates if g.address == address), None)
            if ga is None and len(candidates) == 1:
                ga = candidates[0]
            if ga is None or ga.function_id:
                continue
            ga.function_id, ga.function_name, ga.ets_known = function.id, point, True
            restored += 1
    return restored


def is_function_designation(text: str) -> bool:
    return bool(_FUNCTION_DESIGNATION_RE.match(text or ""))


# ── Verknüpfung mit den Aktorkanälen der Mitglieder ───────────────────────

def member_links(project, function: KnixFunction):
    """(Mitglied, Funktions-GA, GA des Mitglieds mit derselben Funktion) je
    Mitglied und Funktionspunkt."""
    gas = {ga.function_name: ga for ga in project.group_addresses.all_addresses()
           if ga.function_id == function.id}
    element_gas = _element_gas(project)
    for member in resolve_members(project, function):
        if member is None:
            continue
        own = element_gas.get((member.assignment.id, member.element_number), {})
        for point in function_points(function):
            fga = gas.get(point.function)
            if fga is not None:
                yield member, fga, own.get(point.function)


# ── Abgleich mit der ETS ──────────────────────────────────────────────────

@dataclass
class PlanStatus:
    """Stand einer geplanten Funktion in der ETS."""
    function: KnixFunction
    location: Location | None
    ets: object = None                 # EtsFunction
    ets_room: object = None
    missing: list[GroupAddress] = field(default_factory=list)

    @property
    def state(self) -> str:
        if self.ets is None:
            return "anlegen"
        return "ergänzen" if self.missing else "ok"

    @property
    def other_room(self) -> bool:
        if self.ets is None or self.location is None:
            return False
        return self.ets_room not in self.location.rooms


def compare_plan(project) -> list[PlanStatus]:
    """Geplante Funktionen mit den aus der ETS eingelesenen abgleichen: eine
    ETS-Funktion gehört zur geplanten, mit der sie die meisten GAs teilt."""
    ets_list = [(room, f) for room in project.all_rooms for f in room.ets_functions]
    gas_by_function: dict[str, list[GroupAddress]] = {}
    for ga in function_gas(project.group_addresses):
        gas_by_function.setdefault(ga.function_id, []).append(ga)
    statuses = []
    candidates = []
    for pi, function in enumerate(project.functions):
        statuses.append(PlanStatus(function, locate(project, function)))
        addresses = {ga.address for ga in gas_by_function.get(function.id, [])}
        for ei, (_room, ets) in enumerate(ets_list):
            shared = len(addresses & {r.address for r in ets.refs})
            if shared:
                candidates.append((-shared, pi, ei))
    used_p, used_e = set(), set()
    for _n, pi, ei in sorted(candidates):
        if pi in used_p or ei in used_e:
            continue
        used_p.add(pi)
        used_e.add(ei)
        status = statuses[pi]
        status.ets_room, status.ets = ets_list[ei]
        ets_addresses = {r.address for r in status.ets.refs}
        status.missing = sorted(
            (ga for ga in gas_by_function.get(status.function.id, [])
             if ga.address not in ets_addresses
             and in_ets_function(status.function.function_type, ga.function_name)),
            key=lambda g: (g.middle_group, g.sub_group))
    return statuses


# ── Prüfung (FA-637) ──────────────────────────────────────────────────────

def _point_label(function_type: str, function_name: str) -> str:
    point = next((p for p in PLAN_POINTS.get(function_type, ())
                  if p.function == function_name), None)
    if point is None:
        return function_name
    if not point.role:
        return point.label or function_name
    ets = next((p for p in FUNCTION_TYPES[function_type][1] if p.role == point.role), None)
    return ets.label if ets else function_name


def check_plan(project) -> list:
    """FA-637: geplante Funktionen in der ETS und an den Aktorkanälen."""
    if not getattr(project, "functions", None):
        return []
    from .validation_engine import ValidationIssue
    issues = []
    ets_read = any(r.ets_functions for r in project.all_rooms)
    linked = _links_by_address(project)
    for status in compare_plan(project):
        function = status.function
        location = status.location
        if location is None:
            issues.append(ValidationIssue(
                "warning", "FA-637", f"Funktion «{function.name}»: Raum bzw. Zone fehlt",
                "", "Funktion löschen oder neu anlegen", designation=function.name))
            continue
        where = location.label
        kind = type_label(function.function_type)
        gas = sorted((ga for ga in function_gas(project.group_addresses)
                      if ga.function_id == function.id),
                     key=lambda g: (g.middle_group, g.sub_group))
        if not gas:
            continue
        removed = sum(1 for m in resolve_members(project, function) if m is None)
        if removed:
            issues.append(ValidationIssue(
                "warning", "FA-637",
                f"{where}: Funktion «{function.name}» hat {removed} entfernte(s) Element(e)",
                gas[0].address, "Mitglieder der Funktion prüfen", designation=function.name))
        if not function.members:
            issues.append(ValidationIssue(
                "warning", "FA-637", f"{where}: Funktion «{function.name}» ohne Elemente",
                gas[0].address, "Elemente der Funktion wählen", designation=function.name))
        # Übernommene Gruppenbedienung (FA-531) ohne ETS-Funktion: die GAs
        # stehen schon in der ETS, eine ETS-Funktion dazu ist freiwillig
        if ets_read and not (function.ets_gas and status.ets is None):
            point_text = ", ".join(
                f"{_point_label(function.function_type, ga.function_name)} {ga.address}"
                for ga in (status.missing if status.ets else gas)
                if in_ets_function(function.function_type, ga.function_name))
            if status.ets is None:
                issues.append(_task_issue(
                    function, where, gas[0].address, "anlegen",
                    f"{where}: ETS-Funktion «{function.name}» ({kind}) fehlt",
                    f"Funktion «{function.name}» ({kind}) anlegen und zuordnen: "
                    f"{point_text}."))
            elif status.missing:
                issues.append(_task_issue(
                    function, where, gas[0].address, "ergänzen",
                    f"{where}: ETS-Funktion «{status.ets.name}» ohne {point_text}",
                    f"Funktion «{status.ets.name}»: {point_text} zuordnen."))
            if status.other_room:
                issues.append(_task_issue(
                    function, where, gas[0].address, "raum",
                    f"ETS-Funktion «{status.ets.name}» liegt nicht in {where}",
                    f"Funktion «{status.ets.name}» nach {where} verschieben."))
        if linked is not None:
            issues.extend(_link_issues(project, function, where, linked))
    return issues


def _task_issue(function, where, address, kind, message, task):
    from .validation_engine import ValidationIssue
    return ValidationIssue(
        "warning", "FA-637", message, address, "In der ETS nachführen",
        designation=function.name,
        details={"key": f"{function.id}", "kind": kind, "where": where, "task": task})


def _links_by_address(project):
    """GA-Adresse -> [(Gerät, KO)] -- None, solange keine KO verknüpft ist
    (geplante Projekte vor der CO-Verknüpfung)."""
    result: dict[str, list] = {}
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                for co in device.communication_objects:
                    for address in co.connected_gas:
                        result.setdefault(address, []).append((device, co))
    return result or None


def _co_text(device, co) -> str:
    name = co.name or co.object_function
    return f"{device.physical_address} KO {co.object_number}" + (f" «{name}»" if name else "")


def _link_issues(project, function, where, linked) -> list:
    """Funktions-GA am KO des Mitglieds, das dessen eigene GA trägt."""
    from .validation_engine import ValidationIssue
    issues = []
    for member, fga, own in member_links(project, function):
        if own is None:
            continue
        for device, co in linked.get(own.address, []):
            if fga.address not in co.connected_gas:
                issues.append(ValidationIssue(
                    "warning", "FA-637",
                    f"{_co_text(device, co)}: Funktions-GA {fga.address} fehlt "
                    f"(Funktion «{function.name}», {member.label})",
                    fga.address, f"{fga.address} mit dem KO verknüpfen",
                    designation=fga.designation,
                    details={"key": f"{function.id}|{device.physical_address}|"
                                    f"{co.object_number}|{fga.address}",
                             "kind": "verknüpfen", "where": _co_text(device, co),
                             "task": f"{fga.address} verknüpfen "
                                     f"(Funktion «{function.name}»)."}))
    return issues


# ── Tasten (FA-530) ───────────────────────────────────────────────────────

def apply_function_buttons(project) -> int:
    """Tasten mit einer Funktion (SensorFunktion.function_id): primäre GA und
    weitere Befehls-GAs aus den aktuellen Funktions-GAs ableiten. Fehlt die
    Funktion, bleibt die Taste mit ihrem Namen offen."""
    from ..models.building import SensorFunktionGa
    gas_by_function: dict[str, list[GroupAddress]] = {}
    for ga in function_gas(project.group_addresses):
        gas_by_function.setdefault(ga.function_id, []).append(ga)
    functions = {f.id: f for f in getattr(project, "functions", [])}
    changed = 0
    for room in project.all_rooms:
        for be in room.bedienelemente:
            for sf in be.funktionen:
                if not sf.function_id:
                    continue
                function = functions.get(sf.function_id)
                order = {p.function: i for i, p in enumerate(function_points(function))} \
                    if function else {}
                gas = sorted(gas_by_function.get(sf.function_id, []),
                             key=lambda g: order.get(g.function_name, 99))
                texts = [f"{ga.address}  {ga.designation}" for ga in gas]
                primary = texts[0] if texts else ""
                extra = [SensorFunktionGa(t, "befehl", f"{function.name} {ga.function_name}")
                         for t, ga in zip(texts[1:], gas[1:])]
                before = (sf.ga_designation, [e.to_dict() for e in sf.extra_gas], sf.label)
                sf.ga_designation, sf.extra_gas = primary, extra
                sf.gewerk_code, sf.scene_id, sf.primary_role = "", "", "befehl"
                if function is not None:
                    sf.label = function.name
                if before != (sf.ga_designation, [e.to_dict() for e in sf.extra_gas], sf.label):
                    changed += 1
    return changed


def unlink_removed_gas(project) -> int:
    """Geplante Projekte: Verknüpfungen auf Funktions-GAs, die es nicht mehr
    gibt (Funktion gelöscht, Element entfernt), an den KOs trennen."""
    existing = {ga.address for ga in project.group_addresses.all_addresses()}
    removed = 0
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                for co in device.communication_objects:
                    kept = [a for a in co.connected_gas
                            if a in existing or not _looks_like_function_slot(a)]
                    removed += len(co.connected_gas) - len(kept)
                    co.connected_gas = kept
    return removed


def _looks_like_function_slot(address: str) -> bool:
    try:
        return int(address.split("/")[2]) >= FIRST_SUB
    except (IndexError, ValueError):
        return False
