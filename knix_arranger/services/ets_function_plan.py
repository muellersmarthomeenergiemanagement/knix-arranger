"""
ETS-Funktionen planen (FA-530, FA-637).

KNiX leitet aus den Elementen der Gewerke die Funktionen ab, die in der ETS
angelegt werden sollen: je Element eine Funktion im Raum mit den geplanten
GAs als Funktionspunkte (Licht E/A -> "Schalten", RM -> "Status" ...).

Eine .knxproj kann KNiX nicht in die ETS zurückschreiben, und die ETS legt
für eine neue Funktion eigene GAs in HG 12 an. Der Integrator legt die
Funktion deshalb in der ETS an und ordnet die KNiX-GAs zu -- die Aufgaben
dazu stehen in der ETS-Arbeitsliste (FA-618). Nach dem Re-Import gleicht
compare_plan die eingelesenen Funktionen mit der Planung ab.

Zuordnung über Adressen nur innerhalb eines Projektstands (geplante GA ↔
Funktionspunkt der ETS), nie als gespeicherter Schlüssel; der Schlüssel
einer geplanten Funktion ist Zuteilung + Element.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from ..models.ets_function import EtsFunction, EtsFunctionRef
from .ets_function_service import FUNCTION_TYPES, function_point, type_label

_LIGHT = {"E/A": "SwitchOnOff", "RM": "InfoOnOff", "DIM": "DimmingControl",
          "WERT": "DimmingValue", "RM WERT": "InfoDimmingValue"}
_BLINDS = {"AUF/AB": "MoveUpDown", "STOPP": "StopStepUpDown",
           "STATUS POSITION HOEHE": "CurrentAbsolutePositionBlindsPercentage",
           "STATUS POSITION LAMELLEN": "CurrentAbsolutePositionSlatPercentage"}
_HEATING = {"IST": "TempRoom", "BASIS-SOLL": "TempRoomSetpoint",
            "STELLGROESSE": "ValvePosition", "UMSCHALTEN BETRIEBSART": "HVACMode"}

#: Gewerk -> (Funktionstyp, Bezeichnung, Funktion laut Schema -> Rolle)
GEWERK_FUNCTIONS: dict[str, tuple[str, str, dict[str, str]]] = {
    "L":   ("FT-1", "Licht", _LIGHT),
    "LD":  ("FT-6", "Licht", _LIGHT),
    "LDA": ("FT-6", "Licht", _LIGHT),
    "S":   ("FT-10", "Steckdose", _LIGHT),
    "SD":  ("FT-6", "Steckdose", _LIGHT),
    "J":   ("FT-7", "Jalousie", _BLINDS),
    "R":   ("FT-7", "Rollladen", _BLINDS),
    "M":   ("FT-7", "Markise", _BLINDS),
    "H":   ("FT-9", "Heizung", _HEATING),
}

# Funktionstypen, die einander entsprechen (ältere ETS-Typen, Steckdose als
# Licht schalten); FT-0 Benutzerdefiniert passt zu allem
_TYPE_GROUP = {"FT-1": "switch", "FT-10": "switch", "FT-2": "dim", "FT-6": "dim",
               "FT-3": "blinds", "FT-7": "blinds", "FT-4": "heat", "FT-5": "heat",
               "FT-8": "heat", "FT-9": "heat"}


@dataclass
class PlannedFunction:
    key: str                 # "<Zuteilung>|<Element>", stabil über Importe
    floor: object
    room: object
    name: str                # "Licht Decke"
    function_type: str
    refs: list[EtsFunctionRef]

    @property
    def addresses(self) -> set[str]:
        return {r.address for r in self.refs}


@dataclass
class PlanStatus:
    """Abgleich einer geplanten Funktion mit der ETS."""
    planned: PlannedFunction
    ets: EtsFunction | None = None
    ets_room: object = None
    missing: list[EtsFunctionRef] = field(default_factory=list)
    # (geplant, in der ETS stattdessen zugeordnet)
    replaced: list[tuple[EtsFunctionRef, EtsFunctionRef]] = field(default_factory=list)

    @property
    def state(self) -> str:
        if self.ets is None:
            return "anlegen"
        if self.missing or self.replaced:
            return "ergänzen"
        return "ok"

    @property
    def other_room(self) -> bool:
        return self.ets is not None and self.ets_room is not self.planned.room

    @property
    def type_differs(self) -> bool:
        if self.ets is None or self.ets.function_type == "FT-0":
            return False
        return (_TYPE_GROUP.get(self.ets.function_type)
                != _TYPE_GROUP.get(self.planned.function_type))


def _function_name(assignment, nr: int, noun: str, room) -> str:
    label = assignment.element_label(nr)
    if label:
        return f"{noun} {label}"
    name = f"{noun} {room.name}".strip()
    return f"{name} {nr}" if assignment.count > 1 else name


def planned_functions(project) -> list[PlannedFunction]:
    """Je Element der unterstützten Gewerke eine Funktion mit den GAs, die
    einem Funktionspunkt der ETS entsprechen."""
    by_element: dict[tuple[str, int], list] = {}
    for ga in project.group_addresses.all_addresses():
        if ga.assignment_id and not ga.is_placeholder:
            # Rückmeldeblock der Variante B (MG 6/7): "<Zuteilung>:fb"
            assignment_id = ga.assignment_id.removesuffix(":fb")
            by_element.setdefault((assignment_id, ga.element_number), []).append(ga)
    result = []
    for floor in project.areal.all_floors:
        for apartment in floor.apartments:
            for room in apartment.rooms:
                for assignment in room.gewerk_assignments:
                    spec = GEWERK_FUNCTIONS.get(assignment.gewerk_code)
                    if spec is None:
                        continue
                    ftype, noun, roles = spec
                    for nr in range(1, assignment.count + 1):
                        if assignment.element_profiles.get(nr):
                            continue   # Funktionsumfang geändert (z.B. nur schalten)
                        plan = _plan_element(assignment, nr, ftype, roles,
                                             by_element.get((assignment.id, nr), []))
                        if plan is None:
                            continue
                        ftype_el, refs = plan
                        result.append(PlannedFunction(
                            f"{assignment.id}|{nr}", floor, room,
                            _function_name(assignment, nr, noun, room), ftype_el, refs))
    return result


def _plan_element(assignment, nr, ftype, roles, gas):
    refs = []
    for ga in sorted(gas, key=lambda g: (g.main_group, g.middle_group, g.sub_group)):
        role = roles.get(ga.planned_function)
        if role is None:
            continue
        if role == "ValvePosition" and ga.datapoint_type.startswith("DPST-1-"):
            ftype, role = "FT-8", ""   # schaltende Stellgrösse, Rolle über DPT
        refs.append(EtsFunctionRef(role, ga.address, ga.designation, ga.datapoint_type))
    points = FUNCTION_TYPES[ftype][1]
    refs = [r for r in refs if function_point(ftype, r) in points]
    if not refs:
        return None
    order = {p: i for i, p in enumerate(points)}
    refs.sort(key=lambda r: order.get(function_point(ftype, r), 99))
    return ftype, refs


def _ets_functions(project):
    for floor in project.areal.all_floors:
        for apartment in floor.apartments:
            for room in apartment.rooms:
                for function in room.ets_functions:
                    yield room, function


def compare_plan(project) -> list[PlanStatus]:
    """Geplante Funktionen mit den eingelesenen ETS-Funktionen abgleichen.
    Eine ETS-Funktion gehört zur geplanten, mit der sie die meisten GAs
    teilt (jede ETS-Funktion höchstens einmal)."""
    plans = planned_functions(project)
    candidates = []
    ets_list = list(_ets_functions(project))
    for pi, plan in enumerate(plans):
        for ei, (room, function) in enumerate(ets_list):
            shared = len(plan.addresses & {r.address for r in function.refs})
            if shared:
                candidates.append((-shared, pi, ei))
    candidates.sort()
    used_plans: set[int] = set()
    used_ets: set[int] = set()
    statuses = [PlanStatus(plan) for plan in plans]
    for _neg, pi, ei in candidates:
        if pi in used_plans or ei in used_ets:
            continue
        used_plans.add(pi)
        used_ets.add(ei)
        room, function = ets_list[ei]
        status = statuses[pi]
        status.ets, status.ets_room = function, room
        _compare_refs(status)
    return statuses


def _compare_refs(status: PlanStatus) -> None:
    ets = status.ets
    ets_addresses = {r.address for r in ets.refs}
    for ref in status.planned.refs:
        if ref.address in ets_addresses:
            continue
        point = function_point(status.planned.function_type, ref)
        instead = next(
            (r for r in ets.refs if r.address not in status.planned.addresses
             and point is not None
             and function_point(ets.function_type, r) is not None
             and function_point(ets.function_type, r).label == point.label), None)
        if instead is not None:
            status.replaced.append((ref, instead))
        else:
            status.missing.append(ref)


def point_label(function_type: str, ref) -> str:
    point = function_point(function_type, ref)
    return point.label if point else ref.role


def _room_text(room) -> str:
    return " ".join(p for p in (room.number, room.name) if p) or "Raum"


def check_plan(project) -> list:
    """FA-637: geplante Funktionen, die in der ETS fehlen oder unvollständig
    sind. Nur wenn das Projekt ETS-Funktionen plant."""
    if not project.config.plan_ets_functions:
        return []
    from .validation_engine import ValidationIssue
    issues = []
    for status in compare_plan(project):
        plan = status.planned
        where = f"Raum {_room_text(plan.room)}"
        kind = type_label(plan.function_type)
        if status.ets is None:
            gas = ", ".join(f"{point_label(plan.function_type, r)} {r.address}"
                            for r in plan.refs)
            issues.append(ValidationIssue(
                "warning", "FA-637",
                f"{where}: ETS-Funktion «{plan.name}» ({kind}) fehlt",
                plan.refs[0].address,
                f"Funktion anlegen, GAs zuordnen: {gas}",
                designation=plan.name,
                details={"key": plan.key, "kind": "anlegen", "where": where,
                         "task": f"Funktion «{plan.name}» ({kind}) anlegen und "
                                 f"zuordnen: {gas}."}))
            continue
        name = status.ets.name
        parts = [f"{point_label(plan.function_type, new)} {new.address} statt {old.address}"
                 for new, old in status.replaced]
        parts += [f"{point_label(plan.function_type, r)} {r.address}" for r in status.missing]
        if parts:
            text = "; ".join(parts)
            issues.append(ValidationIssue(
                "warning", "FA-637",
                f"{where}: ETS-Funktion «{name}» unvollständig: {text}",
                plan.refs[0].address, "In der ETS der Funktion zuordnen",
                designation=plan.name,
                details={"key": plan.key, "kind": "ergänzen", "where": where,
                         "task": f"Funktion «{name}»: {text} zuordnen."}))
        if status.other_room:
            issues.append(ValidationIssue(
                "warning", "FA-637",
                f"ETS-Funktion «{name}» liegt in Raum {_room_text(status.ets_room)}, "
                f"geplant in {_room_text(plan.room)}",
                plan.refs[0].address, "In der ETS in den geplanten Raum verschieben",
                designation=plan.name,
                details={"key": plan.key, "kind": "raum",
                         "where": f"Raum {_room_text(status.ets_room)}",
                         "task": f"Funktion «{name}» in Raum «{_room_text(plan.room)}» "
                                 "verschieben."}))
        if status.type_differs:
            issues.append(ValidationIssue(
                "info", "FA-637",
                f"{where}: ETS-Funktion «{name}» ist {type_label(status.ets.function_type)}, "
                f"geplant {kind}",
                plan.refs[0].address, "", designation=plan.name))
    return issues
