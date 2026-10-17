"""
Gruppenadressen in der Baumansicht bearbeiten, einzeln oder mehrere (FA-1003b).

Was bearbeitbar ist, hängt von der Herkunft der GA ab:
- generiert (geplantes Projekt, aus einem Gewerk-Element): Funktion, DPT und
  Beschreibung. Funktion und DPT werden als Nachbearbeitung am Gewerk-Element
  gespeichert (GewerkAssignment.function_overrides, Schlüssel = Funktion laut
  Schema) und gelten bei jeder Neuberechnung; die Adresse bleibt dieselbe,
  die Bezeichnung folgt der Funktion. Alles andere kommt aus der Planung.
- manuell angelegt oder aus der ETS importiert: alle Felder direkt.
- übrige generierte (Reserven, Zentral- und Szenenadressen): nur die
  Beschreibung, der Rest entsteht bei jeder Neuberechnung neu.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .address_generator import insert_ga, regenerate_addresses
from .ga_delete import _assignment_by_id
from .ga_functions import suggested_dpt

GENERATED = "generated"
FREE = "free"
FIXED = "fixed"

FIELDS_GENERATED = frozenset({"function_name", "datapoint_type", "description"})
FIELDS_FREE = frozenset({
    "designation", "description", "function_name", "datapoint_type",
    "gewerk_code", "room_number", "element_number", "central", "is_placeholder",
})
FIELDS_FIXED = frozenset({"description"})

_REASON_FIXED = "entsteht bei jeder Neuberechnung neu – nur die Beschreibung ist frei"
_REASON_GENERATED = "kommt aus der Planung (Wizard) – frei sind Funktion, DPT und Beschreibung"


def edit_kind(project, ga) -> str:
    if project.topology.is_imported or ga.is_manual:
        return FREE
    if (not ga.is_placeholder and ga.function_name
            and _assignment_by_id(project, ga.assignment_id) is not None):
        return GENERATED
    return FIXED


def editable_fields(project, ga) -> frozenset:
    return {GENERATED: FIELDS_GENERATED, FREE: FIELDS_FREE,
            FIXED: FIELDS_FIXED}[edit_kind(project, ga)]


def is_reworked(ga) -> bool:
    """Generierte GA mit nachbearbeiteter Funktion/DPT."""
    return bool(ga.plan_function)


@dataclass
class EditResult:
    changed: list[str] = field(default_factory=list)              # Adressen
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (Adresse, Grund)
    regenerated: bool = False


def _override_slot(project, ga) -> dict | None:
    assignment = _assignment_by_id(project, ga.assignment_id)
    if assignment is None:
        return None
    return assignment.function_overrides.setdefault(ga.element_number, {})


def _clean_overrides(project, ga) -> None:
    assignment = _assignment_by_id(project, ga.assignment_id)
    if assignment is not None and not assignment.function_overrides.get(ga.element_number):
        assignment.function_overrides.pop(ga.element_number, None)


def _rework(project, ga, function: str | None, dpt: str | None) -> bool:
    """Speichert Funktion/DPT einer generierten GA als Nachbearbeitung."""
    slot = _override_slot(project, ga)
    if slot is None:
        return False
    plan = ga.planned_function
    current = dict(slot.get(plan) or {})
    new_function = ((function or "").strip().upper() or plan) if function is not None \
        else ga.function_name
    if function is not None and dpt is None and new_function != ga.function_name:
        dpt = suggested_dpt(new_function) or None   # DPT folgt der Funktion
    if new_function == plan and dpt is None:
        slot.pop(plan, None)                         # zurück zur Planung
    else:
        current["function"] = new_function
        current["dpt"] = dpt if dpt is not None else current.get("dpt") or ga.datapoint_type
        slot[plan] = current
    _clean_overrides(project, ga)
    return True


def apply_changes(project, gas: list, changes: dict) -> EditResult:
    """Übernimmt die Felder in changes (Feldname -> Wert) für alle gas, so weit
    sie bearbeitbar sind. Nachbearbeitete Funktionen generierter GAs führen
    zu einer Neuberechnung der Adressen (Adressen bleiben)."""
    result = EditResult()
    if not changes:
        return result
    before = {ga.id: ga.designation for ga in project.group_addresses.all_addresses()}
    for ga in gas:
        kind = edit_kind(project, ga)
        allowed = editable_fields(project, ga)
        wanted = {k: v for k, v in changes.items() if k in allowed}
        refused = set(changes) - set(wanted)
        if refused and not wanted:
            result.skipped.append(
                (ga.address, _REASON_FIXED if kind == FIXED else _REASON_GENERATED))
            continue
        if kind == GENERATED and ({"function_name", "datapoint_type"} & set(wanted)):
            if _rework(project, ga, wanted.get("function_name"), wanted.get("datapoint_type")):
                result.regenerated = True
        for name, value in wanted.items():
            if kind == GENERATED and name in ("function_name", "datapoint_type"):
                continue
            if name == "function_name" and "datapoint_type" not in changes:
                if value != ga.function_name and suggested_dpt(value):
                    ga.datapoint_type = suggested_dpt(value)
            setattr(ga, name, value)
        result.changed.append(ga.address)
    if result.regenerated:
        regenerate_addresses(project)
        _follow_designations(project, before)
    return result


def move_ga(project, ga, main: int, middle: int, sub: int) -> str:
    """Neue Adresse für eine frei bearbeitbare GA (manuell/importiert), Verweise
    werden nachgeführt. Gibt "" zurück oder den Grund, weshalb es nicht geht."""
    from .renumber_service import remap_ga_references
    if (main, middle, sub) == (ga.main_group, ga.middle_group, ga.sub_group):
        return ""
    if edit_kind(project, ga) != FREE:
        return "Die Adresse kommt aus der Planung – verschieben per Ziehen im Baum."
    if not (0 <= main <= 31 and 0 <= middle <= 7 and 0 <= sub <= 255):
        return "Ungültige Adresse (HG 0–31, MG 0–7, UG 0–255)."
    if (main, middle, sub) == (0, 0, 0):
        return "0/0/0 ist eine Systemadresse."
    structure = project.group_addresses
    other = structure.find_address(main, middle, sub)
    if other is not None and other is not ga:
        return f"{main}/{middle}/{sub} ist schon vergeben ({other.designation})."
    old = ga.address
    for hg in structure.main_groups:
        for mg in hg.middle_groups:
            if ga in mg.group_addresses:
                mg.group_addresses.remove(ga)
    ga.main_group, ga.middle_group, ga.sub_group = main, middle, sub
    insert_ga(structure, ga)
    for hg in structure.main_groups:
        for mg in hg.middle_groups:
            mg.group_addresses.sort(key=lambda g: g.sub_group)
    remap_ga_references(project, {old: ga.address})
    return ""


def reset_to_plan(project, gas: list) -> int:
    """Nachbearbeitete Funktion/DPT wieder wie geplant. Anzahl GAs."""
    n = 0
    before = {ga.id: ga.designation for ga in project.group_addresses.all_addresses()}
    for ga in gas:
        if not is_reworked(ga):
            continue
        slot = _override_slot(project, ga)
        if slot is not None and slot.pop(ga.plan_function, None) is not None:
            n += 1
        _clean_overrides(project, ga)
        assignment = _assignment_by_id(project, ga.assignment_id)
        if assignment is not None:
            # einzelne GA zurück: das Element hat keinen ganzen Funktionsumfang mehr
            assignment.element_profiles.pop(ga.element_number, None)
    if n:
        regenerate_addresses(project)
        _follow_designations(project, before)
    return n


# ── Funktionsumfang je Element (FA-1003d) ──

PROFILE_LABELS = {
    "": "Wie geplant (alle Funktionen des Gewerks)",
    "schalten_rm": "Schalten mit Rückmeldung (E/A + RM)",
    "schalten": "Schalten ohne Rückmeldung (E/A)",
}


def element_of(project, ga):
    """(Gewerk-Eintrag, Element-Nr.) einer generierten GA, sonst (None, 0)."""
    if project.topology.is_imported or ga.is_manual or not ga.element_number:
        return None, 0
    assignment = _assignment_by_id(project, ga.assignment_id)
    return (assignment, ga.element_number) if assignment is not None else (None, 0)


def can_set_profile(project, ga) -> bool:
    """Nur für Elemente, die nicht ohnehin ein Schaltaktor schaltet."""
    from ..models.device import GEWERK_TO_ACTOR_TYPE
    assignment, _nr = element_of(project, ga)
    return (assignment is not None
            and GEWERK_TO_ACTOR_TYPE.get(assignment.gewerk_code) not in (None, "Schaltaktor"))


def _schema_functions(project, assignment, element_nr: int) -> tuple[list[str], list[str]]:
    """Funktionen des Elements laut Schema: (Befehlsblock, Rückmeldeblock B)."""
    from .address_generator import AddressGenerator
    gewerk = project.gewerk_catalog.get(assignment.gewerk_code)
    if gewerk is None:
        return [], []
    gen = AddressGenerator(project.gewerk_catalog, variant=project.config.mg_variant)
    blocks = []
    for is_feedback in (False, True):
        schema = gen._get_block_schema(gewerk, assignment=assignment, is_feedback=is_feedback)
        if is_feedback and (project.config.mg_variant != "B" or schema is None):
            blocks.append([])
            continue
        entries = schema.entries_for(element_nr) if schema else []
        blocks.append([e.function for e in entries if e.function and not e.is_reserve])
    return blocks[0], blocks[1]


def set_element_profile(project, ga, profile: str) -> bool:
    """Funktionsumfang des Elements der GA setzen ("" = wie geplant). Die ersten
    Plätze des Blocks bekommen die Funktionen des Profils, die übrigen werden
    Reserve; die Adressen bleiben. Neuberechnung inklusive."""
    from ..models.building import ELEMENT_PROFILES
    assignment, nr = element_of(project, ga)
    if assignment is None or (profile and profile not in ELEMENT_PROFILES):
        return False
    before = {g.id: g.designation for g in project.group_addresses.all_addresses()}
    assignment.function_overrides.pop(nr, None)
    assignment.omitted_functions.pop(nr, None)
    assignment.element_profiles.pop(nr, None)
    if profile:
        forward, feedback = _schema_functions(project, assignment, nr)
        targets = ELEMENT_PROFILES[profile]
        overrides, omitted = {}, []
        for i, function in enumerate(forward):
            if i < len(targets):
                if function != targets[i]:
                    overrides[function] = {"function": targets[i],
                                           "dpt": suggested_dpt(targets[i])}
            else:
                omitted.append(function)
        omitted.extend(f for f in feedback if f not in omitted)
        if overrides:
            assignment.function_overrides[nr] = overrides
        if omitted:
            assignment.omitted_functions[nr] = omitted
        assignment.element_profiles[nr] = profile
    regenerate_addresses(project)
    _follow_designations(project, before)
    return True


def _follow_designations(project, before: dict[str, str]) -> None:
    """Tastenbelegungen, die eine GA über ihre Bezeichnung finden, auf die
    neue Bezeichnung umstellen (die Funktion steht in der Bezeichnung)."""
    renamed = {}
    for ga in project.group_addresses.all_addresses():
        old = before.get(ga.id)
        if old and old != ga.designation:
            renamed[old] = ga.designation
    if not renamed:
        return
    for room in project.all_rooms:
        for be in room.bedienelemente:
            for fa in be.function_assignments:
                if fa.function_ga in renamed:
                    fa.function_ga = renamed[fa.function_ga]
            for sf in be.funktionen:
                if sf.ga_designation in renamed:
                    sf.ga_designation = renamed[sf.ga_designation]
