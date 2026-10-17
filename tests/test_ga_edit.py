"""
GAs in der Baumansicht bearbeiten (FA-1003b/c): Nachbearbeitung generierter
GAs übersteht die Neuberechnung, Mehrfachbearbeitung, Funktion und Rolle.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import insert_ga, regenerate_addresses
from knix_arranger.services.ga_delete import delete_gas, restore_function
from knix_arranger.services.ga_edit import (
    FIXED, FREE, GENERATED, apply_changes, edit_kind, is_reworked, reset_to_plan,
)
from knix_arranger.services import ga_functions
from knix_arranger.services.topology_engine import TopologyEngine


def _project(gewerk_catalog) -> KnxProject:
    room = Room(number="U02", name="Technik Rohrbegleitheizung")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="H", count=1),
                               GewerkAssignment(gewerk_code="L", count=2)]
    floor = Floor(name="UG", short_code="UG", main_group_number=4,
                  apartments=[Apartment(name="Wohnung", rooms=[room])])
    project = KnxProject(name="Bearbeiten")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    regenerate_addresses(project)
    return project


def _ga(project, gewerk: str, function: str, element: int = 1) -> GroupAddress:
    return next(g for g in project.group_addresses.all_addresses()
                if g.gewerk_code == gewerk and g.element_number == element
                and g.function_name == function)


def _addresses(project) -> set[str]:
    return {g.address for g in project.group_addresses.all_addresses()}


def test_heating_becomes_switch_and_survives_regeneration(gewerk_catalog):
    project = _project(gewerk_catalog)
    stell, ist = _ga(project, "H", "STELLGROESSE"), _ga(project, "H", "IST")
    stell_addr, ist_addr = stell.address, ist.address
    before = _addresses(project)
    assert edit_kind(project, stell) == GENERATED

    result = apply_changes(project, [stell], {"function_name": "E/A"})
    assert result.regenerated and result.changed == [stell_addr]
    apply_changes(project, [_ga(project, "H", "IST")], {"function_name": "RM"})

    ea = _ga(project, "H", "E/A")
    rm = _ga(project, "H", "RM")
    assert (ea.address, rm.address) == (stell_addr, ist_addr)
    assert ea.datapoint_type == "DPST-1-1" and rm.datapoint_type == "DPST-1-1"
    assert ea.designation.startswith("H_") and " E/A (" in ea.designation
    assert ea.plan_function == "STELLGROESSE" and is_reworked(ea)
    assert _addresses(project) == before

    regenerate_addresses(project)
    regenerate_addresses(project)
    assert _ga(project, "H", "E/A").address == stell_addr
    assert _ga(project, "H", "RM").address == ist_addr

    # Speichern und Laden
    loaded = KnxProject.from_dict(project.to_dict())
    loaded._gewerk_catalog = gewerk_catalog
    regenerate_addresses(loaded)
    assert _ga(loaded, "H", "E/A").address == stell_addr


def test_reset_to_plan(gewerk_catalog):
    project = _project(gewerk_catalog)
    stell = _ga(project, "H", "STELLGROESSE")
    address = stell.address
    apply_changes(project, [stell], {"function_name": "E/A"})
    assert reset_to_plan(project, [_ga(project, "H", "E/A")]) == 1
    back = _ga(project, "H", "STELLGROESSE")
    assert back.address == address and back.datapoint_type == "DPST-5-1"
    assert not is_reworked(back)
    assignment = project.all_rooms[0].gewerk_assignments[0]
    assert assignment.function_overrides == {}


def test_dpt_only_change_is_kept(gewerk_catalog):
    project = _project(gewerk_catalog)
    stell = _ga(project, "H", "STELLGROESSE")
    apply_changes(project, [stell], {"datapoint_type": "DPST-5-4"})
    regenerate_addresses(project)
    again = _ga(project, "H", "STELLGROESSE")
    assert again.datapoint_type == "DPST-5-4" and is_reworked(again)


def test_bulk_change_several_elements(gewerk_catalog):
    project = _project(gewerk_catalog)
    gas = [_ga(project, "L", "E/A", 1), _ga(project, "L", "E/A", 2)]
    apply_changes(project, gas, {"description": "Aussen"})
    assert all(g.description == "Aussen" for g in gas)
    regenerate_addresses(project)
    assert _ga(project, "L", "E/A", 2).description == "Aussen"


def test_planning_fields_of_generated_ga_refused(gewerk_catalog):
    project = _project(gewerk_catalog)
    ga = _ga(project, "H", "IST")
    result = apply_changes(project, [ga], {"room_number": "X99"})
    assert result.changed == [] and result.skipped
    assert ga.room_number != "X99"


def test_delete_reworked_ga_omits_planned_function(gewerk_catalog):
    project = _project(gewerk_catalog)
    stell = _ga(project, "H", "STELLGROESSE")
    address = stell.address
    apply_changes(project, [stell], {"function_name": "E/A"})
    delete_gas(project, [_ga(project, "H", "E/A")])
    reserve = next(g for g in project.group_addresses.all_addresses() if g.address == address)
    assert reserve.is_placeholder
    assert project.all_rooms[0].gewerk_assignments[0].omitted_functions == {1: ["STELLGROESSE"]}
    assert restore_function(project, reserve)
    assert _ga(project, "H", "E/A").address == address


def test_manual_ga_all_fields_and_dpt_follows_function(gewerk_catalog):
    project = _project(gewerk_catalog)
    manual = GroupAddress(main_group=4, middle_group=4, sub_group=50,
                          designation="Rohrbegleitheizung", is_manual=True)
    insert_ga(project.group_addresses, manual)
    assert edit_kind(project, manual) == FREE
    apply_changes(project, [manual], {"function_name": "E/A", "gewerk_code": "H"})
    assert manual.datapoint_type == "DPST-1-1" and manual.gewerk_code == "H"


def test_central_ga_only_description(gewerk_catalog):
    project = _project(gewerk_catalog)
    central = next(g for g in project.group_addresses.all_addresses()
                   if g.main_group == 0 and not g.is_placeholder)
    assert edit_kind(project, central) == FIXED


def test_function_roles():
    assert ga_functions.role_of("E/A") == ga_functions.COMMAND
    assert ga_functions.role_of("RM") == ga_functions.FEEDBACK
    assert ga_functions.role_of("STATUS POSITION HOEHE") == ga_functions.FEEDBACK
    assert ga_functions.role_of("IST") == ga_functions.MEASUREMENT
    assert ga_functions.role_of("Wind Alarm") == ga_functions.MEASUREMENT
    assert ga_functions.role_of("VORLAUF IST") == ga_functions.MEASUREMENT
    assert ga_functions.role_of("FREI") == ga_functions.COMMAND
    assert ga_functions.role_of("") == ""
    assert ga_functions.suggested_dpt("rm wert") == "DPST-5-1"
