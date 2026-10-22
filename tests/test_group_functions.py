"""
Gruppenbedienungen in importierten Projekten erkennen und als Funktion
übernehmen (FA-531).
"""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import (
    Area, CommunicationObject, Device, Line, Topology,
)
from knix_arranger.services.ets_function_plan import (
    check_plan, function_gas, member_links, restore_function_ids, sync_function_gas,
)
from knix_arranger.services.group_function_detection import adopt, suggest_group_functions


def _project(extra_gas=(), pir=False):
    """Küche OG 05 mit zwei Leuchten an einem Schaltaktor; 3/4/89 schaltet
    beide (Raum-Zentral), 3/7/x sind Rückmeldungen."""
    project = KnxProject(name="Import")
    lights = GewerkAssignment(gewerk_code="L", count=2)
    room = Room(number="05", name="Küche", gewerk_assignments=[lights])
    floor = Floor(name="Obergeschoss", short_code="OG", main_group_number=3,
                  apartments=[Apartment(name="OG", rooms=[room])])
    project.areal.buildings.append(Building(wings=[Wing(floors=[floor])]))

    def ga(mg, sub, name, dpt="Schalten", assignment=lights):
        return GroupAddress(main_group=3, middle_group=mg, sub_group=sub, designation=name,
                            datapoint_type=dpt, assignment_id=assignment.id if assignment else "")
    group_name = "L.OG.05.01_ea von pir" if pir else "Raum5_Licht Zentral"
    gas = [ga(0, 70, "L.OG.05.01_ea  ( Decke )"), ga(0, 75, "L.OG.05.02_ea  ( Insel )"),
           ga(4, 89, group_name, assignment=None),
           ga(7, 70, "L.OG.05.01_ea  ( Decke )"), ga(7, 75, "L.OG.05.02_ea  ( Insel )"),
           *extra_gas]
    mgs: dict[int, MiddleGroup] = {}
    for g in gas:
        mgs.setdefault(g.middle_group, MiddleGroup(number=g.middle_group)).group_addresses.append(g)
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=3, name="OG", middle_groups=list(mgs.values()))])

    def co(n, name, flags, connected):
        return CommunicationObject(object_number=n, name=name, flags=flags,
                                   connected_gas=connected)
    actor = Device(device_type="actor", product="Schaltaktor 2-fach", physical_address="1.1.1",
                   communication_objects=[
                       co(0, "Kanal A Schalten", "K-S---", ["3/0/70", "3/4/89"]),
                       co(1, "Kanal A Status", "KL-Ü--", ["3/7/70"]),
                       co(2, "Kanal B Schalten", "K-S---", ["3/0/75", "3/4/89"]),
                       co(3, "Kanal B Status", "KL-Ü--", ["3/7/75"])])
    project.topology = Topology(is_imported=True, areas=[Area(area_number=1, lines=[
        Line(line_number=1, name="Linie 1", devices=[actor])])])
    return project, room, lights


def test_group_ga_on_two_channels_is_suggested():
    project, room, lights = _project()
    [suggestion] = suggest_group_functions(project)
    assert suggestion.name == "Licht Zentral"
    assert suggestion.function_type == "FT-1"
    assert suggestion.room is room
    assert [(a.id, n) for _r, a, n in suggestion.members] == [(lights.id, 1), (lights.id, 2)]
    assert {p: g.address for p, g in suggestion.gas.items()} == {"E/A": "3/4/89"}


def test_motion_detector_and_planned_projects_are_skipped():
    project, _room, _lights = _project(pir=True)
    assert suggest_group_functions(project) == []
    project, _room, _lights = _project()
    project.topology.is_imported = False
    assert suggest_group_functions(project) == []


def test_adopted_function_keeps_ets_ga_and_survives_reimport():
    project, _room, _lights = _project()
    count = len(project.group_addresses.all_addresses())
    function = adopt(project, suggest_group_functions(project)[0], "Licht Küche")
    assert sync_function_gas(project) == []
    gas = [g for g in function_gas(project.group_addresses) if g.function_id == function.id]
    assert [(g.address, g.designation, g.ets_known) for g in gas] == [
        ("3/4/89", "Raum5_Licht Zentral", True)]
    assert len(project.group_addresses.all_addresses()) == count   # keine neuen GAs
    links = {m.element_number: own.address for m, _f, own in member_links(project, function)}
    assert links == {1: "3/0/70", 2: "3/0/75"}
    assert not [i for i in check_plan(project) if "Küche" in i.message]
    assert suggest_group_functions(project) == []                  # schon übernommen

    # Re-Import: frische GAs ohne Funktion -> über Adresse + Bezeichnung zurück
    restored = KnxProject.from_dict(project.to_dict())
    for g in restored.group_addresses.all_addresses():
        g.function_id, g.ets_known = "", False
    assert restore_function_ids(restored) == 1
    assert [g.address for g in function_gas(restored.group_addresses)] == ["3/4/89"]


def test_deleting_adopted_function_keeps_its_ga():
    project, _room, _lights = _project()
    function = adopt(project, suggest_group_functions(project)[0])
    sync_function_gas(project)
    project.functions.remove(function)
    sync_function_gas(project)
    ga = next(g for g in project.group_addresses.all_addresses() if g.address == "3/4/89")
    assert (ga.function_id, ga.ets_known) == ("", False)
