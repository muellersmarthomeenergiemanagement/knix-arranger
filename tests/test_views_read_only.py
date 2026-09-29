"""Anzeigen verändert keine Daten: BelegungsplanService.generate() liest nur.

Früher legte generate() bei jedem Öffnen von Topologie, Verknüpfungsmatrix und
Belegungsplan Bedienelemente an und berechnete die Tastenbelegung neu -- so
landeten geratene Belegungen in importierten Tastern (Chalet 1.1.40/1.1.52).
"""
from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, GewerkAssignment, Room,
    SensorFunktion, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.belegungsplan_service import BelegungsplanService
from knix_arranger.services.sensor_service import refresh_bedienelemente


def _project():
    room = Room(number="02", name="Bibliothek")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1, taster_indices=[1])]
    room.bedienelemente = [Bedienelement(
        element_type="Tastereinheit", participant_number="1.1.40", is_auto=False,
        funktionen=[SensorFunktion(label="Taste 1", ga_designation="3/4/20  Raum2_Szene High")],
    )]
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="OG", apartments=[Apartment(rooms=[room])])])])])
    # Sensor ohne Bedienelement: generate() darf keines anlegen
    project.topology = Topology(areas=[Area(area_number=1, lines=[Line(line_number=1, devices=[
        Device(physical_address="1.1.52", device_type="sensor", room_id=room.id),
    ])])])
    return project, room


def test_generate_does_not_change_project():
    project, room = _project()
    before = project.content_fingerprint()

    BelegungsplanService().generate(project)

    assert project.content_fingerprint() == before
    assert [be.participant_number for be in room.bedienelemente] == ["1.1.40"]
    assert room.bedienelemente[0].function_assignments == []


def test_refresh_derives_what_views_show():
    project, room = _project()

    refresh_bedienelemente(project)

    assert sorted(be.participant_number for be in room.bedienelemente) == ["1.1.40", "1.1.52"]
    be40 = next(be for be in room.bedienelemente if be.participant_number == "1.1.40")
    assert be40.function_assignments[0].function_ga.startswith("3/4/20")
