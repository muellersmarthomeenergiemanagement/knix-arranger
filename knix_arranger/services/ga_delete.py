"""
Gruppenadressen löschen (FA-1003a, Baumansicht).

Drei Arten:
- generiert (geplantes Projekt, aus einem Gewerk-Element): die Funktion wird
  für dieses Element weggelassen (GewerkAssignment.omitted_functions); die
  Generierung legt dort eine Reserve an, die Adressen des Blocks bleiben.
- manuell angelegt oder aus der ETS importiert: die GA wird entfernt, alle
  Verweise darauf ebenfalls (Tasten, Szenen, DALI, Zeitprogramme, KOs,
  Korrekturen, Kanal-Verknüpfungen).
- sonst nicht löschbar: Reserven und zentrale Adressen eines geplanten
  Projekts, die bei jeder Neuberechnung wieder entstehen.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .address_generator import OMITTED_PREFIX, regenerate_addresses

GENERATED = "generated"
DELETABLE = "deletable"
KEEP = "keep"


def _assignment_by_id(project, assignment_id: str):
    key = (assignment_id or "").split(":", 1)[0]
    if not key:
        return None
    return next((a for room in project.all_rooms for a in room.gewerk_assignments
                 if a.id == key), None)


def classify(project, ga) -> tuple[str, str]:
    """(Art, Begründung) einer GA für das Löschen."""
    if ga.is_placeholder:
        return KEEP, "Reserve – nichts zu löschen"
    if project.topology.is_imported or ga.is_manual:
        return DELETABLE, ""
    if ga.function_name and _assignment_by_id(project, ga.assignment_id) is not None:
        return GENERATED, ""
    return KEEP, "entsteht bei jeder Neuberechnung neu (z.B. Zentral- oder Szenenadresse)"


@dataclass
class DeleteResult:
    omitted: list[str] = field(default_factory=list)     # Adressen, jetzt Reserve
    deleted: list[str] = field(default_factory=list)     # Adressen, entfernt
    kept: list[tuple[str, str]] = field(default_factory=list)   # (Adresse, Grund)


def delete_gas(project, gas: list) -> DeleteResult:
    """Löscht bzw. lässt die GAs weg (siehe Modul). Bei weggelassenen
    Funktionen werden die Adressen sofort neu generiert."""
    result = DeleteResult()
    to_remove = []
    for ga in gas:
        kind, reason = classify(project, ga)
        if kind == GENERATED:
            assignment = _assignment_by_id(project, ga.assignment_id)
            functions = assignment.omitted_functions.setdefault(ga.element_number, [])
            if ga.function_name not in functions:
                functions.append(ga.function_name)
            result.omitted.append(ga.address)
        elif kind == DELETABLE:
            to_remove.append(ga)
            result.deleted.append(ga.address)
        else:
            result.kept.append((ga.address, reason))
    if to_remove:
        _remove(project, to_remove)
    if result.omitted:
        regenerate_addresses(project)
    return result


def omitted_function_of(ga) -> str:
    """Weggelassene Funktion einer Reserve ("SPERREN"), sonst ""."""
    description = ga.description or ""
    if ga.is_placeholder and description.startswith(OMITTED_PREFIX):
        return description[len(OMITTED_PREFIX):]
    return ""


def restore_function(project, ga) -> bool:
    """Weggelassene Funktion einer Reserve wieder einschalten."""
    function = omitted_function_of(ga)
    assignment = _assignment_by_id(project, ga.assignment_id)
    if not function or assignment is None:
        return False
    functions = assignment.omitted_functions.get(ga.element_number, [])
    if function not in functions:
        return False
    functions.remove(function)
    if not functions:
        assignment.omitted_functions.pop(ga.element_number, None)
    regenerate_addresses(project)
    return True


def _remove(project, gas: list) -> None:
    addresses = {ga.address for ga in gas}
    ids = {ga.id for ga in gas}
    designations = {ga.designation for ga in gas if ga.designation}

    for main in project.group_addresses.main_groups:
        for middle in main.middle_groups:
            middle.group_addresses = [g for g in middle.group_addresses
                                      if g.address not in addresses]

    def refers(value: str) -> bool:
        value = (value or "").strip()
        if not value:
            return False
        head = value.split(" ", 1)[0]
        return head in addresses or value in designations

    for room in project.all_rooms:
        for assignment in room.gewerk_assignments:
            for links in [assignment.linked_ga_ids,
                          *assignment.linked_ga_ids_by_element.values()]:
                for function in [f for f, ga_id in links.items() if ga_id in ids]:
                    del links[function]
        for be in room.bedienelemente:
            for sf in be.funktionen:
                sf.extra_gas = [e for e in sf.extra_gas if not refers(e.ga_designation)]
                if refers(sf.ga_designation):
                    sf.ga_designation = ""
            be.function_assignments = [fa for fa in be.function_assignments
                                       if not refers(fa.function_ga)]

    for scene in project.scenes:
        scene.source_ga_addresses = [a for a in scene.source_ga_addresses
                                     if a not in addresses]
        scene.actions = [a for a in scene.actions
                         if a.ga_address not in addresses and not refers(a.group_address)]
    # Erkannte Szenen, deren einzige Adresse gelöscht ist, gibt es nicht mehr
    project.scenes = [s for s in project.scenes
                      if not (s.is_detected and not s.source_ga_addresses)]

    for gateway in project.dali_configs.values():
        for name in ("ga_switch_broadcast", "ga_dim_broadcast", "ga_scene",
                     "ga_status_value", "ga_status_fault"):
            if getattr(gateway, name) in addresses:
                setattr(gateway, name, "")
        for group in gateway.groups:
            for name in ("ga_switch", "ga_dim", "ga_value", "ga_status", "ga_scene",
                         "ga_fault"):
                if getattr(group, name) in addresses:
                    setattr(group, name, "")

    for program in project.time_programs:
        for _profile, point in program.all_switch_points():
            if point.target_ga_id in ids:
                point.target_ga_id = ""

    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                for co in device.communication_objects:
                    co.connected_gas = [a for a in co.connected_gas if a not in addresses]

    corrections = project.ets_corrections
    for address in addresses:
        corrections.gewerk_by_address.pop(address, None)
    # "1.1.51|6|12/1/62" (Gerät|KO|GA): GA-Teil exakt vergleichen
    corrections.unlinked = [u for u in corrections.unlinked
                            if u.rsplit("|", 1)[-1] not in addresses]
