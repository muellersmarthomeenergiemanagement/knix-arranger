"""Wetteralarme auf den Sonnenschutz-Aktoren (FA-644): die GAs der
Wetterstation liegen im Belegungsplan auf den Kanälen von Jalousie,
Rollladen und Markise; die KO-Zuordnung schlägt das Sicherheits-KO vor."""
import logging

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.actor_channels import DeviceChannel, device_circuits, suggest_co
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.belegungsplan_service import BelegungsplanService
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.services.validation_engine import ValidationEngine
from knix_arranger.services.weather_alarms import (
    FROST, RAIN, WIND, names_other_alarm, station_gas, unprotected_channels,
)


def _build(weather_station=True):
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="Wetter")
    gewerke = [GewerkAssignment(gewerk_code="J", count=2),
               GewerkAssignment(gewerk_code="M", count=1),
               GewerkAssignment(gewerk_code="L", count=1)]
    if weather_station:
        gewerke.append(GewerkAssignment(gewerk_code="W", count=1))
    wohnen = Room(number="01", name="Wohnen", gewerk_assignments=gewerke)
    floor = Floor(name="EG", short_code="EG", main_group_number=2,
                  apartments=[Apartment(name="Wohnung", rooms=[wohnen])])
    project.areal = Areal(buildings=[Building(name="H", wings=[Wing(floors=[floor])])])
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    regenerate_addresses(project)
    return project


@pytest.fixture
def project():
    yield _build()
    logging.disable(logging.NOTSET)


def _alarm_rows(project):
    rows = BelegungsplanService().generate(project).actor_rows
    return [r for r in rows if r.function_name in (WIND, RAIN, FROST)]


def test_alarms_of_the_station_on_every_blind_channel(project):
    stations = station_gas(project)
    assert set(stations) == {WIND, RAIN, FROST}
    rows = _alarm_rows(project)
    by_element = {}
    for row in rows:
        by_element.setdefault((row.gewerk_code, row.element_number), set()).add(row.function_name)
    # Jalousie: Wind und Frost; Markise zusätzlich Regen; Licht nichts
    assert by_element == {("J", 1): {WIND, FROST}, ("J", 2): {WIND, FROST},
                          ("M", 1): {WIND, RAIN, FROST}}
    assert {r.ga_address for r in rows if r.function_name == WIND} == {stations[WIND].address}
    # derselbe Kanal wie der Fahrbefehl des Elements
    all_rows = BelegungsplanService().generate(project).actor_rows
    move = next(r for r in all_rows if r.gewerk_code == "J" and r.element_number == 2
                and r.function_name == "AUF/AB")
    wind = next(r for r in rows if r.gewerk_code == "J" and r.element_number == 2
                and r.function_name == WIND)
    assert (wind.physical_address, wind.channel_number) == (
        move.physical_address, move.channel_number)


def test_without_station_no_rows_but_a_hint():
    project = _build(weather_station=False)
    assert _alarm_rows(project) == []
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project=project)
              if i.rule_id == "FA-644"]
    assert len(issues) == 1 and issues[0].level == "info"
    assert "3 Sonnenschutz-Element(e)" in issues[0].message
    logging.disable(logging.NOTSET)


def test_with_station_no_hint_and_omitting_per_element(project):
    assert not [i for i in ValidationEngine().validate(project.group_addresses, project=project)
                if i.rule_id == "FA-644"]
    blinds = next(a for r in project.all_rooms for a in r.gewerk_assignments
                  if a.gewerk_code == "J")
    blinds.omitted_functions[2] = [WIND, FROST]
    elements = {(r.gewerk_code, r.element_number) for r in _alarm_rows(project)}
    assert elements == {("J", 1), ("M", 1)}


def test_circuit_carries_the_alarms_for_the_ko_dialog(project):
    device = next(d for a in project.topology.areas for ln in a.lines for d in ln.devices
                  if d.device_type == "actor" and any(
                      r.physical_address == d.physical_address for r in _alarm_rows(project)))
    circuit = next(c for c in device_circuits(project, device) if c.gewerk_code in ("J", "M"))
    assert WIND in [f for f, _ga in circuit.functions]


def _safety(number, name, function="Ein / Aus", gas=()):
    return CommunicationObject(object_number=number, name=name, object_function=function,
                               data_type="DPST-1-5", flags="KS", connected_gas=list(gas))


def test_suggestion_takes_the_safety_kos_in_order():
    """Griesser: «Sicherheit 1 (M1), Alarm» sagt nicht, welcher Alarm."""
    cos = [_safety(12, "Sicherheit 1 (M1), Alarm"), _safety(13, "Sicherheit 2 (M1), Alarm")]
    wind = suggest_co(cos, WIND, dpt="DPST-1-5")
    assert wind.object_number == 12
    assert suggest_co(cos, FROST, {12}, "DPST-1-5").object_number == 13
    # benannte KOs: jeder Alarm auf seinen Platz, nie auf einen fremden
    named = [_safety(1, "Kanal A", "Regenalarm"), _safety(2, "Kanal A", "Windalarm")]
    assert suggest_co(named, WIND, dpt="DPST-1-5").object_number == 2
    assert suggest_co(named, RAIN, dpt="DPST-1-5").object_number == 1
    assert suggest_co(named, FROST, dpt="DPST-1-5") is None
    assert names_other_alarm("Regenalarm", WIND) and not names_other_alarm("Alarm", WIND)
    assert not names_other_alarm("Window contact", RAIN)


def test_imported_channels_without_any_safety_link():
    project = _build(weather_station=False)
    project.topology.is_imported = True
    line = project.topology.areas[0].lines[0]
    device = Device(physical_address="1.1.50", device_type="actor")

    def move(number, m, gas):
        return CommunicationObject(object_number=number, name=f"Bedienung Storen (M{m}), Endlage",
                                   object_function="Auf / Ab", data_type="DPST-1-8",
                                   flags="KS", connected_gas=gas)
    device.communication_objects = [
        move(1, 1, ["2/1/0"]), _safety(12, "Sicherheit 1 (M1), Alarm", gas=["0/5/12"]),
        move(23, 2, ["2/1/5"]), _safety(34, "Sicherheit 1 (M2), Alarm"),
        move(45, 3, []), _safety(56, "Sicherheit 1 (M3), Alarm"),      # Kanal unbenutzt
    ]
    line.devices.append(device)
    found = [(d.physical_address, n) for d, n in unprotected_channels(project)]
    assert found == [("1.1.50", 1)]
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project=project)
              if i.rule_id == "FA-644"]
    assert len(issues) == 1 and "1.1.50" in issues[0].message
    logging.disable(logging.NOTSET)


def test_channel_without_kos_is_no_place():
    assert suggest_co(DeviceChannel(1, "Kanal 1").com_objects, WIND) is None
