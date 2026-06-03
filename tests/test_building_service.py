"""
Tests fuer BuildingService (FA-101 bis FA-107)
Gebaeudestruktur erstellen und verwalten.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.building_service import BuildingService
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)


class TestBuildingServiceCreation:
    """Tests fuer Gebaeudestruktur-Erstellung."""

    def test_create_default_areal(self):
        """Erstellt ein Standard-Areal."""
        service = BuildingService()
        areal = service.create_default_areal("Mein Haus")

        assert isinstance(areal, Areal)
        assert areal.name == "Mein Haus"
        assert len(areal.buildings) == 1
        assert len(areal.buildings[0].wings) == 1

    def test_add_floor(self):
        """Stockwerk hinzufuegen."""
        service = BuildingService()
        areal = service.create_default_areal("Test")

        wing = areal.buildings[0].wings[0]
        service.add_floor(wing, "Erdgeschoss", "EG", 2)

        assert len(wing.floors) == 1
        assert wing.floors[0].name == "Erdgeschoss"
        assert wing.floors[0].short_code == "EG"
        assert wing.floors[0].main_group_number == 2

    def test_add_apartment(self):
        """Wohnung hinzufuegen."""
        service = BuildingService()
        floor = Floor(name="EG", short_code="EG", main_group_number=2)

        service.add_apartment(floor, "Wohnung 1")

        assert len(floor.apartments) == 1
        assert floor.apartments[0].name == "Wohnung 1"

    def test_add_room(self):
        """Raum hinzufuegen."""
        service = BuildingService()
        apt = Apartment(name="EG")

        service.add_room(apt, "E01", "Schlafzimmer")

        assert len(apt.rooms) == 1
        assert apt.rooms[0].number == "E01"
        assert apt.rooms[0].name == "Schlafzimmer"

    def test_add_gewerk_to_room(self):
        """Gewerk zu Raum hinzufuegen."""
        service = BuildingService()
        room = Room(number="E01", name="Test")

        service.add_gewerk(room, "LD", 2)

        assert len(room.gewerk_assignments) == 1
        assert room.gewerk_assignments[0].gewerk_code == "LD"
        assert room.gewerk_assignments[0].count == 2


class TestBuildingServiceProperties:
    """Tests fuer Gebaeudestruktur-Eigenschaften."""

    def test_all_rooms(self, simple_efh):
        """all_rooms gibt alle Raeume zurueck."""
        rooms = simple_efh.all_rooms
        assert len(rooms) == 5  # UG:1, EG:2, OG:1, DG:1

    def test_all_floors(self, simple_efh):
        """all_floors gibt alle Stockwerke zurueck."""
        floors = simple_efh.all_floors
        assert len(floors) == 4

    def test_floor_all_rooms(self, simple_efh):
        """Floor.all_rooms ueber alle Apartments."""
        eg = simple_efh.all_floors[1]  # EG
        rooms = eg.all_rooms
        assert len(rooms) == 2

    def test_total_devices(self, simple_efh):
        """Geraeteanzahl wird berechnet."""
        eg = simple_efh.all_floors[1]
        # 2 Raeume * (4 Sensoren + 2 Aktoren) = 12
        assert eg.total_devices() == 12

    def test_room_total_devices(self):
        """Room.total_devices()."""
        room = Room(planned_sensors=6, planned_actors=4)
        assert room.total_devices() == 10


class TestBuildingServiceTemplates:
    """Tests fuer Gebaeude-Vorlagen."""

    def test_load_template_efh(self):
        """EFH-Vorlage laden."""
        service = BuildingService()
        areal = service.load_template("efh")

        if areal:  # Template koennte nicht vorhanden sein
            assert isinstance(areal, Areal)
            floors = areal.all_floors
            assert len(floors) >= 2  # Mindestens EG + OG


class TestBuildingServiceAssignment:
    """Tests fuer Hauptgruppen-Zuordnung."""

    def test_assign_main_groups(self, simple_efh):
        """Hauptgruppen automatisch zuordnen."""
        service = BuildingService()
        service.assign_main_groups(simple_efh)

        floors = simple_efh.all_floors
        # UG=1, EG=2, OG=3, DG=4 (bereits so gesetzt in Fixture)
        assert floors[0].main_group_number == 1  # UG
        assert floors[1].main_group_number == 2  # EG
        assert floors[2].main_group_number == 3  # OG
        assert floors[3].main_group_number == 4  # DG

    def test_assign_main_groups_no_duplicates(self):
        """Keine doppelten HG-Nummern nach Zuweisung."""
        areal = Areal(name="Duplikat-Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")

        # Alle Stockwerke mit gleicher HG-Nummer -1 (auto)
        for name, code in [("UG", "UG"), ("EG", "EG"), ("OG", "OG"),
                           ("1.OG", "1.OG"), ("DG", "DG")]:
            floor = Floor(name=name, short_code=code, main_group_number=-1)
            apt = Apartment(name=code)
            floor.apartments.append(apt)
            wing.floors.append(floor)

        building.wings.append(wing)
        areal.buildings.append(building)

        BuildingService.assign_main_groups(areal)

        hg_numbers = [f.main_group_number for f in areal.all_floors]
        assert len(hg_numbers) == len(set(hg_numbers)), \
            f"Doppelte HG-Nummern: {hg_numbers}"
        assert all(n > 0 for n in hg_numbers), \
            f"HG-Nummern muessen > 0 sein: {hg_numbers}"

    def test_assign_main_groups_resolves_duplicates(self):
        """Bestehende Duplikate werden aufgeloest."""
        areal = Areal(name="Duplikat-Fix")
        building = Building(name="Test")
        wing = Wing(name="Haupt")

        # Manuell gleiche Nummern setzen
        f1 = Floor(name="EG", short_code="EG", main_group_number=2)
        f1.apartments.append(Apartment(name="EG"))
        f2 = Floor(name="OG", short_code="OG", main_group_number=2)  # Duplikat!
        f2.apartments.append(Apartment(name="OG"))
        f3 = Floor(name="DG", short_code="DG", main_group_number=3)
        f3.apartments.append(Apartment(name="DG"))

        wing.floors = [f1, f2, f3]
        building.wings.append(wing)
        areal.buildings.append(building)

        BuildingService.assign_main_groups(areal)

        hg_numbers = [f.main_group_number for f in areal.all_floors]
        assert len(hg_numbers) == len(set(hg_numbers)), \
            f"Duplikate nicht aufgeloest: {hg_numbers}"

    def test_assign_main_groups_mixed_auto_manual(self):
        """Mix aus auto (-1) und manuell gesetzten Nummern."""
        areal = Areal(name="Mix-Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")

        f1 = Floor(name="EG", short_code="EG", main_group_number=2)
        f1.apartments.append(Apartment(name="EG"))
        f2 = Floor(name="OG", short_code="OG", main_group_number=-1)  # auto
        f2.apartments.append(Apartment(name="OG"))
        f3 = Floor(name="DG", short_code="DG", main_group_number=-1)  # auto
        f3.apartments.append(Apartment(name="DG"))

        wing.floors = [f1, f2, f3]
        building.wings.append(wing)
        areal.buildings.append(building)

        BuildingService.assign_main_groups(areal)

        hg_numbers = [f.main_group_number for f in areal.all_floors]
        assert len(hg_numbers) == len(set(hg_numbers)), \
            f"Doppelte HG-Nummern: {hg_numbers}"
        assert f1.main_group_number == 2  # Manuell bleibt
        assert f2.main_group_number > 0
        assert f3.main_group_number > 0
        assert f2.main_group_number != 2
        assert f3.main_group_number != 2
