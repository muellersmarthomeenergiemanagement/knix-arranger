"""
FA-639: Name der GA passt nicht zur Funktion der Aktor-KOs (FA-531a).
"""
from __future__ import annotations

from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.validation_engine import ValidationEngine


def _project(gas, imported=True):
    """Griesser JAX-9 (Chalet 1.1.11), Kanal M3: 2/1/2 am Höhe-, 2/1/3 am
    Winkel-KO."""
    project = KnxProject(name="Test")
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=2, middle_groups=[MiddleGroup(number=1, group_addresses=list(gas))])])

    def co(n, name, function, connected, flags="K-S---"):
        return CommunicationObject(object_number=n, name=name, object_function=function,
                                   flags=flags, data_type="DPST-5-1", connected_gas=connected)
    actor = Device(device_type="actor", physical_address="1.1.11", communication_objects=[
        co(49, "Bedienung Storen (M3), Höhe", "Höhe 0…255", ["2/1/2"]),
        co(50, "Bedienung Storen (M3), Winkel", "Winkel 0…255", ["2/1/3"]),
        co(54, "Sonnenschutz (M3), Rückmeldung Winkel", "Winkel 0…255", ["2/6/3"],
           flags="KL-Ü--")])
    project.topology = Topology(is_imported=imported, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[actor])])])
    return project


def _ga(sub, designation, function_name=""):
    return GroupAddress(main_group=2, middle_group=1, sub_group=sub, designation=designation,
                        datapoint_type="DPST-5-1", function_name=function_name)


def test_imported_suffix_against_ko_is_a_hint():
    project = _project([_ga(2, "J.EG.06.3_hoehe"), _ga(3, "J.EG.06.3_hoehe")])
    [issue] = ValidationEngine._check_name_vs_ko(project)
    assert (issue.level, issue.rule_id, issue.address) == ("info", "FA-639", "2/1/3")
    assert "POSITION HOEHE" in issue.message and "POSITION LAMELLEN" in issue.message
    assert "1.1.11 KO 50" in issue.message


def test_fantasy_name_claims_nothing():
    project = _project([_ga(2, "J.Studio Position"), _ga(3, "J.Studio Stellung")])
    assert ValidationEngine._check_name_vs_ko(project) == []


def test_planned_function_against_ko_is_an_error():
    project = _project([_ga(2, "J_EG_06_03 POSITION HOEHE", "POSITION HOEHE"),
                        _ga(3, "J_EG_06_03 POSITION HOEHE", "POSITION HOEHE")],
                       imported=False)
    [issue] = ValidationEngine._check_name_vs_ko(project)
    assert (issue.level, issue.address) == ("error", "2/1/3")


def test_matching_names_are_silent():
    project = _project([_ga(2, "J.EG.06.3_hoehe"), _ga(3, "J.EG.06.3_winkel")])
    assert ValidationEngine._check_name_vs_ko(project) == []
