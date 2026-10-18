"""Melder ausserhalb der Gewerke bekommen ein Element im Gewerk A
(sensor_service.adopt_manual_detectors). Projekt_23 Technik: Rauchmelder und
Wassermelder aus der Bauherrenberatung hatten keine GA, Schritt 10 erzeugte
keine Adressen für sie."""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.recalc_service import RecalcService
from knix_arranger.services.sensor_service import adopt_manual_detectors, refresh_bedienelemente
from knix_arranger.services.topology_engine import TopologyEngine


def _project(gewerk_catalog):
    technik = Room(number="U02", name="Technik")
    technik.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
    project = KnxProject(name="Melder")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="UG", short_code="UG", main_group_number=4,
              apartments=[Apartment(name="Wohnung", rooms=[technik])])])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    RecalcService().recalc_actors_and_addresses(project)
    return project, technik


def _melders(room, sensor_type):
    return [be for be in room.bedienelemente
            if be.element_type == sensor_type and not be.suppressed]


def test_melder_bekommt_gewerk_a_element(gewerk_catalog):
    project, technik = _project(gewerk_catalog)
    rauch = Bedienelement(element_type="Rauchmelder", is_auto=False, taster_index=2)
    wasser = Bedienelement(element_type="Wassermelder", is_auto=False, taster_index=3)
    tombstone = Bedienelement(element_type="Rauchmelder", is_auto=False, suppressed=True)
    praesenz = Bedienelement(element_type="Präsenzmelder", is_auto=False, taster_index=4)
    technik.bedienelemente += [rauch, wasser, tombstone, praesenz]

    refresh_bedienelemente(project)
    a = next(x for x in technik.gewerk_assignments if x.gewerk_code == "A")
    assert (a.count, a.element_labels) == (2, ["Rauchmelder", "Wassermelder"])
    # Bestehende Bedienelemente verbunden, nicht verdoppelt
    assert _melders(technik, "Rauchmelder") == [rauch]
    assert _melders(technik, "Wassermelder") == [wasser]
    assert [(sf.gewerk_code, sf.element_number) for sf in rauch.funktionen] == [("A", 1)]
    assert tombstone not in technik.bedienelemente
    # Präsenzmelder schalten Licht -- kein Alarm-Melder
    assert not any(sf.gewerk_code for sf in praesenz.funktionen)

    regenerate_addresses(project)
    refresh_bedienelemente(project)
    gas = [g for g in project.group_addresses.all_addresses()
           if g.room_id == technik.id and g.gewerk_code == "A"]
    assert {g.element_number for g in gas} == {1, 2}
    assert rauch.function_assignments                      # GAs am Melder
    # Wiederholt aufrufbar: nichts Neues
    assert adopt_manual_detectors(project) == 0
    assert _melders(technik, "Rauchmelder") == [rauch]


def test_importiert_unveraendert(gewerk_catalog):
    project, technik = _project(gewerk_catalog)
    project.topology.is_imported = True
    technik.bedienelemente.append(Bedienelement(element_type="Rauchmelder", is_auto=False))
    assert adopt_manual_detectors(project) == 0
    assert not any(x.gewerk_code == "A" for x in technik.gewerk_assignments)
