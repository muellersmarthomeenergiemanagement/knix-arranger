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
