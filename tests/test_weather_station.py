"""Wetterstation als Systemgerät (FA-1408, FA-1409, FA-442): GAs zentral in
HG 0 / MG 5, je Element ein Gerät auf der Linie seines Raums."""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import AddressGenerator, regenerate_addresses
from knix_arranger.services.sensor_service import (
    GEWERK_PRIMARY_FUNCTIONS, SensorService,
)


def _areal():
    """EG Technik mit 2 Wetterstationen, OG Dach mit einer, dazu Licht."""
    technik = Room(number="E01", name="Technik", gewerk_assignments=[
        GewerkAssignment(gewerk_code="W", count=2),
        GewerkAssignment(gewerk_code="L", count=1)])
    dach = Room(number="O01", name="Dach", gewerk_assignments=[
        GewerkAssignment(gewerk_code="W", count=1)])
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2,
               apartments=[Apartment(name="EG", rooms=[technik])])
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3,
               apartments=[Apartment(name="OG", rooms=[dach])])
    areal = Areal(name="Test", buildings=[Building(wings=[Wing(floors=[eg, og])])])
    return areal, technik, dach


def _weather_gas(structure):
    return [ga for ga in structure.all_addresses() if ga.gewerk_code == "W"]


def test_wetter_gas_zentral_in_hg0_mg5(gewerk_catalog):
    areal, _technik, _dach = _areal()
    structure = AddressGenerator(gewerk_catalog, variant="A").generate(areal)
    gas = _weather_gas(structure)
    assert len(gas) == 30                                    # 3 Stationen × 10er-Block
    assert {(ga.main_group, ga.middle_group) for ga in gas} == {(0, 5)}
    hg0 = next(hg for hg in structure.main_groups if hg.number == 0)
    assert next(mg for mg in hg0.middle_groups if mg.number == 5).name == "Wetterstation"
    # Stockwerke ohne Wetterstation, Licht bleibt beim Stockwerk
    assert all(ga.main_group != 0 for ga in structure.all_addresses()
               if ga.gewerk_code == "L" and ga.room_id)
    # Bezeichnung nennt Zone, Raum und Element
    assert any(ga.designation == "W_O01_01 HELLIGKEIT SUED (OG / Dach)" for ga in gas)


def test_wetter_gas_bleiben_beim_neu_generieren(gewerk_catalog):
    areal, _technik, dach = _areal()
    gen = AddressGenerator(gewerk_catalog, variant="A")
    first = gen.generate(areal)
    before = {ga.id: ga.address for ga in _weather_gas(first)}
    dach.gewerk_assignments.append(GewerkAssignment(gewerk_code="L", count=1))
    second = gen.generate(areal, existing=first)
    assert {ga.id: ga.address for ga in _weather_gas(second)} == before


def test_variante_b_wetter_in_hg0(gewerk_catalog):
    areal, _technik, _dach = _areal()
    structure = AddressGenerator(gewerk_catalog, variant="B").generate(areal)
    assert {(ga.main_group, ga.middle_group) for ga in _weather_gas(structure)} == {(0, 5)}


def test_je_element_ein_geraet_und_bedienelement(gewerk_catalog):
    areal, technik, dach = _areal()
    project = KnxProject(name="Wetter")
    project.areal = areal
    project._gewerk_catalog = gewerk_catalog
    regenerate_addresses(project)
    service = SensorService()

    assert service.determine_system_sensors(project.all_rooms) == [
        {"gewerk_code": "W", "sensor_type": "Wetterstation", "count": 3}]
    weather = [r for r in service.determine_sensors(project.all_rooms, gewerk_catalog)
               if r.sensor_type == "Wetterstation"]
    assert sorted((r.room_id, r.count) for r in weather) == sorted(
        [(technik.id, 1), (technik.id, 1), (dach.id, 1)])

    service.auto_assign_functions(project.all_rooms, project.group_addresses)
    bes = [be for be in technik.bedienelemente if be.element_type == "Wetterstation"]
    assert [[sf.element_number for sf in be.funktionen] for be in bes] == [[1], [2]]
    assert all(len(be.function_assignments) == 10 for be in bes)
    assert bes[1].function_assignments[1].function_ga == "W_E01_02 HELLIGKEIT SUED (EG / Technik)"


def test_wetterstation_keine_tastenfunktion():
    """Taster dürfen die Wetterstation nicht als Funktion angeboten bekommen."""
    assert "W" not in GEWERK_PRIMARY_FUNCTIONS


def _project_with_floor_weather(gewerk_catalog):
    """Projekt mit Wetter-GAs beim Stockwerk, wie vor Version 1.4.10."""
    from unittest.mock import patch
    from knix_arranger.services import address_generator
    areal, _technik, _dach = _areal()
    project = KnxProject(name="Alt")
    project.areal = areal
    project._gewerk_catalog = gewerk_catalog
    with patch.dict(address_generator.CENTRAL_GEWERK_MIDDLE_GROUPS, clear=True):
        regenerate_addresses(project)
    old = {ga.id: ga.address for ga in _weather_gas(project.group_addresses)}
    assert {a.split("/")[0] for a in old.values()} == {"2", "3"}
    return project, old


def test_in_ets_uebertragen_wetter_gas_bleiben_beim_stockwerk(gewerk_catalog):
    project, old = _project_with_floor_weather(gewerk_catalog)
    project.ets_transferred = "2026-10-19"
    regenerate_addresses(project)
    assert {ga.id: ga.address for ga in _weather_gas(project.group_addresses)} == old


def test_geplant_wetter_gas_wandern_nach_hg0(gewerk_catalog):
    project, _old = _project_with_floor_weather(gewerk_catalog)
    regenerate_addresses(project)
    assert {ga.main_group for ga in _weather_gas(project.group_addresses)} == {0}
