"""Elemente ohne Bedienung (FA-619): Licht Technik wird vom Taster in der
Waschküche geschaltet (Projekt_23 Chalet Franziska)."""
from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, Room, SensorFunktion, Wing,
)
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.models.time_program import DayProfile, SwitchPoint, TimeProgram
from knix_arranger.services.operation_check import unoperated_elements
from knix_arranger.services.validation_engine import ValidationEngine


def _ga(sub, room, code, nr, function, designation):
    return GroupAddress(main_group=4, middle_group=0, sub_group=sub,
                        designation=designation, gewerk_code=code, room_id=room.id,
                        element_number=nr, function_name=function)


def _project():
    project = KnxProject(name="Chalet")
    wasch = Room(number="CUG01", name="Waschküche")
    technik = Room(number="CUG02", name="Technik")
    floor = Floor(name="Untergeschoss", short_code="UG", main_group_number=4,
                  apartments=[Apartment(name="Wohnung", rooms=[wasch, technik])])
    project.areal = Areal(buildings=[Building(name="Chalet", wings=[Wing(floors=[floor])])])
    gas = [
        _ga(0, wasch, "L", 1, "E/A", "L_CUG01_01 E/A (Wohnung / Waschküche)"),
        _ga(20, technik, "L", 1, "E/A", "L_CUG02_01 E/A (Wohnung / Technik)"),
        _ga(21, technik, "L", 1, "RM", "L_CUG02_01 RM (Wohnung / Technik)"),
        _ga(30, technik, "H", 1, "BASIS-SOLL", "H_CUG02_01 BASIS-SOLL (Wohnung / Technik)"),
    ]
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=4, name="UG", middle_groups=[MiddleGroup(number=0, name="Licht",
                                                        group_addresses=gas)])])
    wasch.bedienelemente = [Bedienelement(element_type="Tastereinheit", funktionen=[
        SensorFunktion(gewerk_code="L", element_number=1)])]
    return project, wasch, technik, gas


def _run(project):
    return unoperated_elements(project)


def test_element_without_operation_is_reported_with_command_ga():
    project, wasch, technik, gas = _project()
    found = _run(project)
    assert [(u.gewerk_code, u.ga.address) for u in found] == [("L", "4/0/20")]


def test_key_in_other_room_counts():
    project, wasch, technik, gas = _project()
    wasch.bedienelemente[0].funktionen.append(
        SensorFunktion(gewerk_code="L", element_number=1, source_room_id=technik.id))
    assert _run(project) == []


def test_removed_key_does_not_count():
    project, wasch, technik, gas = _project()
    technik.bedienelemente = [Bedienelement(element_type="Tastereinheit", suppressed=True,
                                            funktionen=[SensorFunktion(gewerk_code="L",
                                                                       element_number=1)])]
    assert len(_run(project)) == 1


def test_scene_and_active_time_program_count():
    project, wasch, technik, gas = _project()
    project.scenes = [Scene(name="Abend", actions=[SceneAction(ga_address="4/0/20", value="1")])]
    assert _run(project) == []

    project.scenes = []
    program = TimeProgram(name="Nacht", day_profiles=[DayProfile(
        switch_points=[SwitchPoint(target_ga_id=gas[1].id, action_value="0")])])
    project.time_programs = [program]
    assert _run(project) == []
    program.active = False
    assert len(_run(project)) == 1


def test_imported_projects_are_not_checked():
    project, wasch, technik, gas = _project()
    project.topology.is_imported = True
    assert _run(project) == []


def test_validation_hint():
    project, wasch, technik, gas = _project()
    issues = [i for i in ValidationEngine(project.gewerk_catalog).validate(
        project.group_addresses, project=project) if i.rule_id == "FA-619"]
    assert len(issues) == 1
    assert issues[0].level == "info" and issues[0].address == "4/0/20"
    assert "Technik" in issues[0].message
