"""
Funktionen planen (FA-530, FA-637).

Eine Funktion bedient mehrere Elemente gemeinsam, z.B. "Fensterfront" für
drei Jalousien eines Raums: Sie hat eigene GAs, die zusätzlich zu den GAs
der Elemente auf deren Aktorkanäle verknüpft werden. Ein Taster auf der
Funktions-GA bedient den ganzen Bezirk, die Einzelbedienung bleibt.

Adressen: HG des Stockwerks, MG des Gewerks, ab UG 200 je Funktion ein
5er-Block (etwas abgesetzt von den Blöcken der Elemente), Bezeichnung
"J_01_F1 AUF/AB (Fensterfront)". Bei Variante B liegen die Rückmeldungen
in MG 6/7 unter ihrem Befehl. Die ETS legt die GAs einer neuen Funktion in
HG 12 an; der Integrator ordnet dort die KNiX-GAs zu (ETS-Arbeitsliste).

Rückmeldung: Senden mehrere Kanäle auf dieselbe Status-GA, ist der Status
zufällig und Leseanfragen beantworten mehrere Geräte (FA-614). Deshalb
sendet nur der Leitkanal (ein Mitglied), oder die Funktion hat keinen
Status.

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


@dataclass(frozen=True)
class PlanPoint:
    function: str      # KNiX-Funktion, z.B. "E/A" (wie bei den Elementen)
    role: str          # Rolle in der ETS
    dpt: str
    offset: int        # Platz im 5er-Block
    status: bool = False
    offset_b: int = -1  # Variante B: Platz im Rückmeldeblock (MG 6/7)


_E_A = PlanPoint("E/A", "SwitchOnOff", "DPST-1-1", 0)
_RM = PlanPoint("RM", "InfoOnOff", "DPST-1-1", 3, True, 0)

#: Funktionstyp -> Funktionspunkte
PLAN_POINTS: dict[str, tuple[PlanPoint, ...]] = {
    "FT-1": (_E_A, _RM),
    "FT-10": (_E_A, _RM),
    "FT-6": (_E_A,
             PlanPoint("DIM", "DimmingControl", "DPST-3-7", 1),
             PlanPoint("WERT", "DimmingValue", "DPST-5-1", 2),
             _RM,
             PlanPoint("RM WERT", "InfoDimmingValue", "DPST-5-1", 4, True, 2)),
    "FT-7": (PlanPoint("AUF/AB", "MoveUpDown", "DPST-1-8", 0),
             PlanPoint("STOPP", "StopStepUpDown", "DPST-1-7", 1),
             PlanPoint("STATUS POSITION HOEHE",
                       "CurrentAbsolutePositionBlindsPercentage", "DPST-5-1", 2, True, 2),
             PlanPoint("STATUS POSITION LAMELLEN",
                       "CurrentAbsolutePositionSlatPercentage", "DPST-5-1", 3, True, 3)),
}
#: Planbare Typen in der Reihenfolge der Auswahl
PLAN_TYPES = ("FT-7", "FT-1", "FT-6", "FT-10")
TYPE_MIDDLE_GROUP = {"FT-1": 0, "FT-6": 0, "FT-10": 0, "FT-7": 1}
FEEDBACK_MIDDLE_GROUP = {0: 6, 1: 7}
#: Gewerke, deren Elemente Mitglied sein können
TYPE_GEWERKE = {
    "FT-1": ("L", "LD", "LDA", "S", "SD"),
    "FT-6": ("LD", "LDA", "SD"),
    "FT-10": ("S", "SD"),
    "FT-7": ("J", "R", "M"),
}
_DEFAULT_CODE = {"FT-1": "L", "FT-6": "LD", "FT-10": "S", "FT-7": "J"}
FIRST_SUB = 200
BLOCK = 5

# "J_01_F1 AUF/AB (Fensterfront)" -> Gewerk, Ort, Nummer, Funktion
_FUNCTION_DESIGNATION_RE = re.compile(
    r"^([A-Z]{1,3})_([A-Z0-9][A-Z0-9.\-]*)_F(\d{1,2})\s+(.+?)(?:\s+\(.*\))?$")


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
        """Ortsteil der Bezeichnung: Raumnummer, bei einer Zone das Stockwerk."""
        if self.room is not None:
            return self.room.number or "00"
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

    @property
    def label(self) -> str:
        label = self.assignment.element_label(self.element_number)
        text = f"{self.assignment.gewerk_code}_{self.room.number}_{self.element_number:02d}"
        return f"{text} ({label or self.room.name})"


def member_candidates(location: Location, function_type: str) -> list[MemberElement]:
    """Elemente des Orts, die eine Funktion dieses Typs mitbedienen können."""
    codes = TYPE_GEWERKE.get(function_type, ())
    result = []
    for room in location.rooms:
        for assignment in room.gewerk_assignments:
            if assignment.gewerk_code not in codes:
                continue
            for nr in range(1, assignment.count + 1):
                result.append(MemberElement(room, assignment, nr))
    return result


def resolve_members(project, function: KnixFunction) -> list[MemberElement | None]:
    """Mitglieder in der Reihenfolge der Funktion (None = Element entfernt)."""
    by_id = {}
    for room in project.all_rooms:
        for assignment in room.gewerk_assignments:
            by_id[assignment.id] = (room, assignment)
    result = []
    for member in function.members:
        found = by_id.get(member.assignment_id)
        if found is None or member.element_number > found[1].count:
            result.append(None)
        else:
            result.append(MemberElement(found[0], found[1], member.element_number))
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
    points = PLAN_POINTS.get(function.function_type, ())
    return tuple(p for p in points if function.with_status or not p.status)


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


def _target(point: PlanPoint, middle_group: int, variant: str) -> tuple[int, int]:
    """(MG, Platz im Block) eines Funktionspunkts."""
    if variant == "B" and point.status and middle_group in FEEDBACK_MIDDLE_GROUP:
        return FEEDBACK_MIDDLE_GROUP[middle_group], point.offset_b
    return middle_group, point.offset


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
    variant = structure.variant or project.config.mg_variant
    warnings = []
    for function in functions:
        location = locate(project, function)
        points = function_points(function)
        if location is None or not points or location.floor.main_group_number <= 0:
            continue
        hg = location.floor.main_group_number
        mg = TYPE_MIDDLE_GROUP[function.function_type]
        targets = [(p, *_target(p, mg, variant)) for p in points]

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
    restored = 0
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
        restored += 1
    return restored


def is_function_designation(text: str) -> bool:
    return bool(_FUNCTION_DESIGNATION_RE.match(text or ""))


# ── Verknüpfung mit den Aktorkanälen der Mitglieder ───────────────────────

def member_links(project, function: KnixFunction):
    """(Mitglied, Funktions-GA, GA des Mitglieds mit derselben Funktion,
    soll verknüpft sein) je Mitglied und Funktionspunkt. Rückmeldungen nur
    beim Leitkanal."""
    gas = {ga.function_name: ga for ga in project.group_addresses.all_addresses()
           if ga.function_id == function.id}
    element_gas: dict[tuple[str, int], dict[str, GroupAddress]] = {}
    for ga in project.group_addresses.all_addresses():
        if ga.assignment_id and not ga.is_placeholder and not ga.function_id:
            key = (ga.assignment_id.removesuffix(":fb"), ga.element_number)
            element_gas.setdefault(key, {})[ga.planned_function] = ga
    for index, member in enumerate(resolve_members(project, function)):
        if member is None:
            continue
        own = element_gas.get((member.assignment.id, member.element_number), {})
        for point in function_points(function):
            fga = gas.get(point.function)
            if fga is None:
                continue
            wanted = not point.status or index == function.lead
            yield member, fga, own.get(point.function), wanted


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
             if ga.address not in ets_addresses),
            key=lambda g: (g.middle_group, g.sub_group))
    return statuses


# ── Prüfung (FA-637) ──────────────────────────────────────────────────────

def _point_label(function_type: str, function_name: str) -> str:
    point = next((p for p in PLAN_POINTS.get(function_type, ())
                  if p.function == function_name), None)
    if point is None:
        return function_name
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
        if ets_read:
            point_text = ", ".join(
                f"{_point_label(function.function_type, ga.function_name)} {ga.address}"
                for ga in (status.missing if status.ets else gas))
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
    senders: dict[str, list[str]] = {}
    for member, fga, own, wanted in member_links(project, function):
        if own is None:
            continue
        cos = linked.get(own.address, [])
        for device, co in cos:
            has = fga.address in co.connected_gas
            if wanted and not has:
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
            if has and _point_is_status(function, fga.function_name):
                senders.setdefault(fga.address, []).append(_co_text(device, co))
    for address, cos in senders.items():
        if len(cos) > 1:
            issues.append(ValidationIssue(
                "warning", "FA-637",
                f"Funktion «{function.name}»: Rückmeldung {address} wird von "
                f"{len(cos)} Kanälen gesendet ({', '.join(cos)})",
                address, "Nur beim Leitkanal verknüpfen, bei den übrigen trennen",
                details={"key": f"{function.id}|{address}|sender", "kind": "sender",
                         "where": f"GA {address}",
                         "task": f"Nur beim Leitkanal lassen, bei {', '.join(cos[1:])} "
                                 "trennen."}))
    return issues


def _point_is_status(function, function_name: str) -> bool:
    return any(p.status and p.function == function_name
               for p in PLAN_POINTS.get(function.function_type, ()))


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
