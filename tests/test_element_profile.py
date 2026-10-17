"""
Funktionsumfang je Element (FA-1003d): Heizung als reines Ein/Aus, z.B.
Rohrbegleitheizung. Adressen bleiben, ein Schaltaktor-Kanal statt eines
Heizungsaktor-Kanals.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.actor_service import ActorService
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.belegungsplan_service import BelegungsplanService
from knix_arranger.services.ga_edit import (
    can_set_profile, reset_to_plan, set_element_profile,
)


def _project(gewerk_catalog, gewerke=(("H", 2), ("S", 1))) -> KnxProject:
    room = Room(number="U02", name="Technik")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code=c, count=n) for c, n in gewerke]
    floor = Floor(name="UG", short_code="UG", main_group_number=4,
                  apartments=[Apartment(name="Wohnung", rooms=[room])])
    project = KnxProject(name="Funktionsumfang")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    line = Line(name="Linie 1", line_number=1, assigned_room_ids=[room.id])
    line.devices = [
        Device(device_type="actor", product="Schaltaktor 4-fach", physical_address="1.1.1"),
        Device(device_type="actor", product="Heizungsaktor 4-fach", physical_address="1.1.2"),
    ]
    project.topology = Topology(areas=[Area(area_number=1, lines=[line])])
    regenerate_addresses(project)
    return project


def _element_gas(project, nr: int) -> list:
    return sorted((g for g in project.group_addresses.all_addresses()
                   if g.assignment_id == project.all_rooms[0].gewerk_assignments[0].id
                   and g.element_number == nr), key=lambda g: g.sub_group)


def test_switch_profile_keeps_addresses(gewerk_catalog):
    project = _project(gewerk_catalog)
    before = {g.address for g in project.group_addresses.all_addresses()}
    first = _element_gas(project, 1)[0]
    assert first.function_name == "STELLGROESSE" and can_set_profile(project, first)

    assert set_element_profile(project, first, "schalten_rm")
    gas = _element_gas(project, 1)
    active = [g for g in gas if not g.is_placeholder]
    assert [(g.function_name, g.datapoint_type) for g in active] == [
        ("E/A", "DPST-1-1"), ("RM", "DPST-1-1")]
    assert all(g.is_placeholder for g in gas[2:])
    assert {g.address for g in project.group_addresses.all_addresses()} == before
    # Element 2 bleibt Heizung
    assert _element_gas(project, 2)[0].function_name == "STELLGROESSE"

    regenerate_addresses(project)
    assert [g.function_name for g in _element_gas(project, 1) if not g.is_placeholder] == ["E/A", "RM"]

    loaded = KnxProject.from_dict(project.to_dict())
    assert loaded.all_rooms[0].gewerk_assignments[0].element_profiles == {1: "schalten_rm"}


def test_back_to_plan(gewerk_catalog):
    project = _project(gewerk_catalog)
    first = _element_gas(project, 1)[0]
    set_element_profile(project, first, "schalten")
    set_element_profile(project, _element_gas(project, 1)[0], "")
    assignment = project.all_rooms[0].gewerk_assignments[0]
    assert not (assignment.function_overrides or assignment.omitted_functions
                or assignment.element_profiles)
    assert _element_gas(project, 1)[0].function_name == "STELLGROESSE"


def test_single_reset_drops_profile(gewerk_catalog):
    project = _project(gewerk_catalog)
    set_element_profile(project, _element_gas(project, 1)[0], "schalten_rm")
    reset_to_plan(project, [_element_gas(project, 1)[0]])
    assert project.all_rooms[0].gewerk_assignments[0].element_profiles == {}


def test_actor_requirements_follow_profile(gewerk_catalog):
    project = _project(gewerk_catalog)
    set_element_profile(project, _element_gas(project, 1)[0], "schalten_rm")
    reqs = {r.actor_type: r.channels_needed
            for r in ActorService().determine_actors(project.all_rooms, gewerk_catalog)}
    assert reqs == {"Heizungsaktor": 1, "Schaltaktor": 2}


def test_channel_on_switch_actor(gewerk_catalog):
    project = _project(gewerk_catalog)
    set_element_profile(project, _element_gas(project, 1)[0], "schalten_rm")
    rows = BelegungsplanService().generate(project).actor_rows
    by_device = {}
    for r in rows:
        if not r.element_number:
            continue    # Zentral- und Szenenadressen
        by_device.setdefault(r.physical_address, set()).add(
            (r.gewerk_code, r.element_number, r.function_name))
    assert {("H", 1, "E/A"), ("H", 1, "RM"), ("S", 1, "E/A")} <= by_device["1.1.1"]
    assert all(code == "H" and nr == 2 for code, nr, _f in by_device["1.1.2"])
    # Heizung und Steckdose bekommen eigene Kanäle
    channels = {(r.gewerk_code, r.element_number): r.channel_number
                for r in rows if r.physical_address == "1.1.1"}
    assert channels[("H", 1)] != channels[("S", 1)]


def test_no_profile_for_switching_gewerk(gewerk_catalog):
    project = _project(gewerk_catalog, gewerke=(("S", 1),))
    ga = next(g for g in project.group_addresses.all_addresses() if g.gewerk_code == "S"
              and g.element_number == 1)
    assert not can_set_profile(project, ga)


def test_gewerk_switch_function_general(gewerk_catalog):
    """Gewerk SF: E/A + RM in MG 4, ein Schaltaktor-Kanal, kein Taster."""
    project = _project(gewerk_catalog, gewerke=(("SF", 1),))
    gas = [g for g in project.group_addresses.all_addresses()
           if g.gewerk_code == "SF" and not g.is_placeholder]
    assert [(g.address, g.function_name, g.datapoint_type) for g in gas] == [
        ("4/4/0", "E/A", "DPST-1-1"), ("4/4/1", "RM", "DPST-1-1")]
    reqs = {r.actor_type: r.channels_needed
            for r in ActorService().determine_actors(project.all_rooms, gewerk_catalog)}
    assert reqs == {"Schaltaktor": 1}
    assert not can_set_profile(project, gas[0])


def _issues(project, rule):
    from knix_arranger.services.validation_engine import ValidationEngine
    return [i for i in ValidationEngine(project.gewerk_catalog).validate(
        project.group_addresses, project) if i.rule_id == rule]


def test_switched_element_without_scene_is_reported(gewerk_catalog):
    from knix_arranger.models.scene import Scene, SceneAction
    project = _project(gewerk_catalog, gewerke=(("H", 1),))
    assert not [i for i in _issues(project, "FA-619") if i.address.startswith("4/2/")]
    set_element_profile(project, _element_gas(project, 1)[0], "schalten_rm")
    ea = _element_gas(project, 1)[0]
    found = [i for i in _issues(project, "FA-619") if i.address == ea.address]
    assert found and "Szene" in found[0].message

    project.scenes.append(Scene(name="Anwesenheit", actions=[
        SceneAction(ga_address=ea.address, group_address=ea.designation)]))
    assert not [i for i in _issues(project, "FA-619") if i.address == ea.address]


def test_dpt_check_covers_function_list(gewerk_catalog):
    from knix_arranger.services.ga_edit import apply_changes
    project = _project(gewerk_catalog, gewerke=(("H", 1),))
    stell = _element_gas(project, 1)[0]
    assert not [i for i in _issues(project, "FA-603") if i.address == stell.address]
    apply_changes(project, [stell], {"datapoint_type": "DPST-1-1"})
    assert [i for i in _issues(project, "FA-603") if i.address == stell.address]
