"""
pytest Fixtures fuer KNiX Arranger Tests.
"""
import pytest
import sys
import os

# Projektverzeichnis zum Pfad hinzufuegen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.gewerk import GewerkCatalog
from knix_arranger.models.project import KnxProject


@pytest.fixture(autouse=True)
def isolate_appdata(monkeypatch, tmp_path):
    """Isoliert alle Tests von der echten %APPDATA%-Umgebung.

    Mehrere Services schreiben dorthin (Produktkatalog-Erweiterung, Logs,
    Lizenzdaten, ...) -- ohne Isolation würden Testläufe die reale
    Windows-Benutzerumgebung verändern und/oder Testergebnisse durch dort
    bereits vorhandene Daten aus früheren Läufen verfälscht (siehe
    product_catalog_user.json-Verschmutzung durch add_product()-Tests).
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))


@pytest.fixture
def gewerk_catalog():
    """Laedt den Standard-Gewerke-Katalog."""
    catalog = GewerkCatalog()
    catalog.load_defaults()
    return catalog


@pytest.fixture
def simple_efh():
    """Einfaches EFH mit 4 Stockwerken und je einem Raum.

    Alle Stockwerke gehoeren zur selben Zone (gleicher Apartment-Name
    "Hauptgebaeude"), da ein EFH eine Einzelzone ist, die mehrere
    Stockwerke umfasst (Zonen-Stockwerk-Modell)."""
    areal = Areal(name="Test EFH")
    building = Building(name="EFH")
    wing = Wing(name="Hauptgebaeude")

    # UG
    ug = Floor(name="Untergeschoss", short_code="UG", main_group_number=1)
    ug_apt = Apartment(name="Hauptgebaeude")
    ug_apt.rooms.append(Room(number="U01", name="Keller"))
    ug.apartments.append(ug_apt)

    # EG
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    eg_apt = Apartment(name="Hauptgebaeude")
    eg_apt.rooms.append(Room(number="E01", name="Schlafzimmer"))
    eg_apt.rooms.append(Room(number="E02", name="Wohnzimmer"))
    eg.apartments.append(eg_apt)

    # OG
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3)
    og_apt = Apartment(name="Hauptgebaeude")
    og_apt.rooms.append(Room(number="O01", name="Kinderzimmer"))
    og.apartments.append(og_apt)

    # DG
    dg = Floor(name="Dachgeschoss", short_code="DG", main_group_number=4)
    dg_apt = Apartment(name="Hauptgebaeude")
    dg_apt.rooms.append(Room(number="D01", name="Estrich"))
    dg.apartments.append(dg_apt)

    wing.floors = [ug, eg, og, dg]
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal


@pytest.fixture
def simple_mfh():
    """MFH mit 3 Stockwerken: UG (1 Allgemein), EG (2 Wohnungen), OG (2 Wohnungen)."""
    areal = Areal(name="Test MFH")
    building = Building(name="MFH")
    wing = Wing(name="Hauptgebaeude")

    # UG: 1 Wohnung (Allgemein)
    ug = Floor(name="Untergeschoss", short_code="UG", main_group_number=1)
    ug_apt = Apartment(name="Allgemein")
    ug_apt.rooms.append(Room(number="U01", name="Keller 1"))
    ug_apt.rooms.append(Room(number="U02", name="Technik"))
    ug.apartments.append(ug_apt)

    # EG: 2 Wohnungen
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    eg_wg1 = Apartment(name="Wohnung 1")
    eg_wg1.rooms.append(Room(number="E01", name="Wohnzimmer"))
    eg_wg1.rooms.append(Room(number="E02", name="Kueche"))
    eg_wg1.rooms.append(Room(number="E03", name="Schlafzimmer"))
    eg.apartments.append(eg_wg1)

    eg_wg2 = Apartment(name="Wohnung 2")
    eg_wg2.rooms.append(Room(number="E04", name="Wohnzimmer"))
    eg_wg2.rooms.append(Room(number="E05", name="Kueche"))
    eg.apartments.append(eg_wg2)

    # OG: 2 Wohnungen
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3)
    og_wg3 = Apartment(name="Wohnung 3")
    og_wg3.rooms.append(Room(number="O01", name="Wohnzimmer"))
    og_wg3.rooms.append(Room(number="O02", name="Schlafzimmer"))
    og.apartments.append(og_wg3)

    og_wg4 = Apartment(name="Wohnung 4")
    og_wg4.rooms.append(Room(number="O03", name="Wohnzimmer"))
    og.apartments.append(og_wg4)

    wing.floors = [ug, eg, og]
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal


@pytest.fixture
def simple_zweckbau():
    """Zweckbau mit 2 Stockwerken, gleiche Zonen auf beiden Etagen."""
    areal = Areal(name="Test Zweckbau")
    building = Building(name="Buero")
    wing = Wing(name="Hauptgebaeude")

    # EG: Zone Nord + Zone Sued
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    eg_nord = Apartment(name="Zone Nord")
    eg_nord.rooms.append(Room(number="E01", name="Buero 1"))
    eg_nord.rooms.append(Room(number="E02", name="Buero 2"))
    eg.apartments.append(eg_nord)

    eg_sued = Apartment(name="Zone Sued")
    eg_sued.rooms.append(Room(number="E03", name="Buero 3"))
    eg_sued.rooms.append(Room(number="E04", name="Empfang"))
    eg.apartments.append(eg_sued)

    # OG: Zone Nord + Zone Sued (gleiche Namen!)
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3)
    og_nord = Apartment(name="Zone Nord")
    og_nord.rooms.append(Room(number="O01", name="Buero 4"))
    og_nord.rooms.append(Room(number="O02", name="Buero 5"))
    og.apartments.append(og_nord)

    og_sued = Apartment(name="Zone Sued")
    og_sued.rooms.append(Room(number="O03", name="Konferenz"))
    og.apartments.append(og_sued)

    wing.floors = [eg, og]
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal


@pytest.fixture
def eg_room_with_gewerke():
    """
    EG Raum E01 (Schlafzimmer) mit Gewerken aus Pflichtenheft Anhang A:
    1x LD, 2x J, 1x H
    """
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")

    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    eg_apt = Apartment(name="EG")

    room = Room(number="E01", name="Schlafzimmer")
    room.gewerk_assignments = [
        GewerkAssignment(gewerk_code="LD", count=1),
        GewerkAssignment(gewerk_code="J", count=2),
        GewerkAssignment(gewerk_code="H", count=1),
    ]
    eg_apt.rooms.append(room)
    eg.apartments.append(eg_apt)

    wing.floors.append(eg)
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal


@pytest.fixture
def test_project(eg_room_with_gewerke, gewerk_catalog):
    """Ein Testprojekt mit Gewerken."""
    project = KnxProject(name="Test Projekt")
    project.areal = eg_room_with_gewerke
    project._gewerk_catalog = gewerk_catalog
    return project
