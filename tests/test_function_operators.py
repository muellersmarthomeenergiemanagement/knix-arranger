"""
ETS-Funktionen: bedienende Elemente (Taster, Sensoren) neben den bedienten.
"""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, FunctionAssignment, Room,
    SensorFunktion, Wing,
)
from knix_arranger.models.ets_function import EtsFunction, EtsFunctionRef, KnixFunction
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.ets_function_plan import ko_functions, planned_operators
from knix_arranger.services.ets_function_service import (
    check_functions, function_operators, overview_rows, role_mismatch,
)


def _project():
    """Chalet 1.1.68 Taste 2: Bewegen, Schritt, Doppelklick Beschattung; die
    LED-Rückmeldung empfängt nur, der Aktor zählt nicht."""
    studio = Room(number="06", name="Studio")
    floor = Floor(name="OG", apartments=[Apartment(rooms=[studio])])
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])

    def co(n, name, function, gas, flags="K-SÜ--"):
        return CommunicationObject(object_number=n, name=name, object_function=function,
                                   flags=flags, connected_gas=gas)
    taster = Device(device_type="sensor", physical_address="1.1.68", room_id=studio.id,
                    communication_objects=[
                        co(6, "Taste 2", "AUF/AB, Jalousie", ["2/1/250"]),
                        co(7, "Taste 2", "Schritt/Stop, Jalousie", ["2/1/251"]),
                        co(10, "Taste 2, Doppelklick", "AUF/AB, fahren Beschattung",
                           ["2/1/254"]),
                        co(11, "Taste 2, LED", "Status", ["2/1/250"], flags="K-S---"),
                        co(12, "Taste 3", "AUF/AB", ["2/1/1", "2/1/250"])])
    actor = Device(device_type="actor", physical_address="1.1.11", communication_objects=[
        co(1, "Bedienung Storen (M3)", "Fahren", ["2/1/1", "2/1/250"], flags="K-S---")])
    project.topology = Topology(areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[taster, actor])])])
    return project, studio


def test_sending_kos_of_sensors_operate_the_function():
    project, _studio = _project()
    found = function_operators(project, ["2/1/250", "2/1/251", "2/1/254"])
    assert [(o.place, o.address, o.text, o.device) for o in found] == [
        ("06 Studio, Taste 2", "2/1/250", "AUF/AB, Jalousie", "Sensor 1.1.68 KO 6"),
        ("06 Studio, Taste 2", "2/1/251", "Schritt/Stop, Jalousie", "Sensor 1.1.68 KO 7"),
        ("06 Studio, Taste 2, Doppelklick", "2/1/254", "AUF/AB, fahren Beschattung",
         "Sensor 1.1.68 KO 10"),
    ]


def test_no_sensor_linked():
    project, _studio = _project()
    assert function_operators(project, ["3/1/250"]) == []


def _blinds_function(*refs):
    """Chalet «J.Bibliothek Berg»: die ETS-Funktion mit den GAs am Griesser
    JAX-9 (Kanal M1)."""
    project, studio = _project()

    def co(n, name, function, address, dpt):
        return CommunicationObject(object_number=n, name=name, object_function=function,
                                   flags="K-S---", data_type=dpt, connected_gas=[address])
    project.topology.areas[0].lines[0].devices.append(Device(
        device_type="actor", physical_address="1.1.5", communication_objects=[
            co(1, "Bedienung Storen (M1), Höhe", "Höhe 0…255", "3/1/252", "DPST-5-1"),
            co(2, "Bedienung Storen (M1), Winkel", "Winkel 0…255", "3/1/253", "DPST-5-1"),
            co(4, "Bedienung Storen (M1), Beschattung", "Auf / Beschattung", "3/1/254",
               "DPST-1-22")]))
    studio.ets_functions = [EtsFunction("J.Bibliothek Berg", "FT-7", list(refs))]
    return project


def test_shading_on_wind_alarm_role():
    """Umbenannte Windalarm-GA der ETS: die Rolle ist falsch, nicht der DPT."""
    ref = EtsFunctionRef("WindAlarm", "3/1/254", "J.Bibliothek Berg Beschattung", "DPST-1-22")
    project = _blinds_function(ref)
    [row] = overview_rows(project)
    assert "Rolle Windalarm, KO sagt Beschattung" in row.hints
    assert not any(h.startswith("DPT") for h in row.hints)
    [issue] = [i for i in check_functions(project) if i.details.get("kind") == "role"]
    assert issue.level == "warning" and "ohne Rolle" in issue.suggestion


def test_swapped_positions_name_the_right_role():
    project = _blinds_function(
        EtsFunctionRef("CurrentAbsolutePositionBlindsPercentage", "3/1/253", "", "DPST-5-1"))
    assert role_mismatch("FT-7", project.all_rooms[0].ets_functions[0].refs[0],
                         ko_functions(project)) == (
        "Rolle Position, KO sagt Lamellenstellung",
        "In der ETS der Rolle «Lamellenstellung» zuordnen")


def test_matching_role_without_hint():
    ref = EtsFunctionRef("CurrentAbsolutePositionBlindsPercentage", "3/1/252", "", "DPST-5-1")
    assert role_mismatch("FT-7", ref, ko_functions(_blinds_function(ref))) is None


def test_one_member_per_actor_channel():
    """Chalet «J.Galerie»: Bewegen und Beschattung der Funktion liegen auf
    zwei KOs desselben Kanals M5 -- ein Eintrag mit der Bewegen-GA 3/1/0,
    nicht zusätzlich 3/1/4 «_beschattung»."""
    from knix_arranger.models.group_address import (
        GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
    )
    from knix_arranger.services.ets_function_service import EtsFunctionMembers
    project, studio = _project()
    project.topology.is_imported = True
    gas = [GroupAddress(main_group=3, middle_group=1, sub_group=n, designation=d,
                        gewerk_code="J", datapoint_type=t)
           for n, d, t in ((0, "J.OG.00.01_move", "DPST-1-8"),
                           (4, "J.OG.00.01_beschattung", "DPST-1-22"))]
    gas += [GroupAddress(main_group=4, middle_group=1, sub_group=n, designation=d)
            for n, d in ((250, "J.Galerie Bewegen"), (254, "J.Galerie Beschattung"))]
    project.group_addresses = GroupAddressStructure(main_groups=[
        MainGroup(number=3, middle_groups=[MiddleGroup(number=1, group_addresses=gas[:2])]),
        MainGroup(number=4, middle_groups=[MiddleGroup(number=1, group_addresses=gas[2:])])])

    def co(n, name, connected):
        return CommunicationObject(object_number=n, name=name, flags="K-S---",
                                   connected_gas=connected)
    project.topology.areas[0].lines[0].devices.append(Device(
        device_type="actor", physical_address="1.1.5", communication_objects=[
            co(90, "Bedienung Storen (M5), Endlage", ["3/1/0", "4/1/250"]),
            co(92, "Bedienung Storen (M5), Beschattung", ["3/1/4", "4/1/254"])]))
    function = EtsFunction("J.Galerie", "FT-7", [
        EtsFunctionRef("MoveUpDown", "4/1/250"), EtsFunctionRef("", "4/1/254")])
    studio.ets_functions = [function]
    finder = EtsFunctionMembers(project)
    # wie im Chalet: nur die Bewegen-GA hat einen Raum im Raumbuch
    finder._place = lambda address, code: "00 Halle" if address == "3/1/0" else ""
    members = [m for m in finder.members(function) if m.channel.startswith("1.1.5")]
    assert [(m.address, m.place, m.channel) for m in members] == [
        ("3/1/0", "00 Halle", "1.1.5 Bedienung Storen (M5)")]


def test_planned_sensor_function():
    project, studio = _project()
    function = KnixFunction(name="Balkonseite", function_type="FT-7", room_id=studio.id)
    sf = SensorFunktion(gewerk_code="J", function_id=function.id)
    be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.68",
                       funktionen=[sf, SensorFunktion(gewerk_code="L")],
                       function_assignments=[FunctionAssignment(button_channel="Taste 2",
                                                                sf_id=sf.id)])
    studio.bedienelemente = [be, Bedienelement(element_type="Tastereinheit", suppressed=True,
                                               funktionen=[SensorFunktion(
                                                   function_id=function.id)])]
    assert planned_operators(project, function) == [
        ("06 Studio, Tastereinheit 1", "1.1.68 Taste 2")]
