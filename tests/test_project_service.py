"""
Tests fuer ProjectService (Speichern/Laden .knxarr)
Tests fuer Gebaeudestruktur-Serialisierung.
"""
import pytest
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.gewerk import GewerkCatalog, Gewerk
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.topology import Topology, Area, Line


class TestBuildingSerialization:
    """Tests fuer Building-Modell Serialisierung."""

    def test_room_roundtrip(self):
        """Room to_dict/from_dict Roundtrip."""
        room = Room(number="E01", name="Schlafzimmer",
                    planned_sensors=6, planned_actors=3)
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=1),
            GewerkAssignment(gewerk_code="J", count=2),
        ]

        data = room.to_dict()
        restored = Room.from_dict(data)

        assert restored.number == "E01"
        assert restored.name == "Schlafzimmer"
        assert restored.planned_sensors == 6
        assert restored.planned_actors == 3
        assert len(restored.gewerk_assignments) == 2
        assert restored.gewerk_assignments[0].gewerk_code == "LD"
        assert restored.gewerk_assignments[1].count == 2

    def test_areal_roundtrip(self, simple_efh):
        """Areal to_dict/from_dict Roundtrip."""
        data = simple_efh.to_dict()
        restored = Areal.from_dict(data)

        assert restored.name == "Test EFH"
        assert len(restored.buildings) == 1
        assert len(restored.buildings[0].wings) == 1
        assert len(restored.buildings[0].wings[0].floors) == 4

        # Raeume pruefen
        eg = restored.buildings[0].wings[0].floors[1]  # EG
        assert eg.name == "Erdgeschoss"
        assert eg.short_code == "EG"
        assert eg.main_group_number == 2
        assert len(eg.apartments[0].rooms) == 2


class TestGroupAddressSerialization:
    """Tests fuer GA-Modell Serialisierung."""

    def test_ga_roundtrip(self):
        """GroupAddress to_dict/from_dict."""
        ga = GroupAddress(
            main_group=2, middle_group=0, sub_group=3,
            designation="LD_E01_01 RM",
            datapoint_type="DPST-1-1",
            gewerk_code="LD",
            room_number="E01",
            element_number=1,
            function_name="RM",
        )

        data = ga.to_dict()
        restored = GroupAddress.from_dict(data)

        assert restored.main_group == 2
        assert restored.middle_group == 0
        assert restored.sub_group == 3
        assert restored.designation == "LD_E01_01 RM"
        assert restored.gewerk_code == "LD"
        assert restored.address == "2/0/3"

    def test_structure_roundtrip(self, eg_room_with_gewerke, gewerk_catalog):
        """GroupAddressStructure to_dict/from_dict."""
        from knix_arranger.services.address_generator import AddressGenerator

        gen = AddressGenerator(gewerk_catalog, variant="A")
        original = gen.generate(eg_room_with_gewerke)

        data = original.to_dict()
        restored = GroupAddressStructure.from_dict(data)

        assert restored.variant == "A"
        assert len(restored.main_groups) == len(original.main_groups)
        assert len(restored.all_addresses()) == len(original.all_addresses())


class TestGewerkCatalog:
    """Tests fuer GewerkCatalog."""

    def test_load_defaults(self, gewerk_catalog):
        """Standard-Katalog hat alle 33 Gewerke."""
        assert len(gewerk_catalog.all_codes()) >= 30

    def test_get_known_gewerk(self, gewerk_catalog):
        """Bekanntes Gewerk kann abgerufen werden."""
        ld = gewerk_catalog.get("LD")
        assert ld is not None
        assert ld.name == "Licht dimmbar"
        assert ld.ga_count == 5
        assert ld.block_size == 5
        assert ld.middle_group == 0
        assert ld.category == "licht"

    def test_get_jalousie(self, gewerk_catalog):
        """Jalousie-Gewerk."""
        j = gewerk_catalog.get("J")
        assert j is not None
        assert j.ga_count == 10
        assert j.block_size == 10
        assert j.middle_group == 1
        assert j.category == "jalousie"

    def test_get_heizung(self, gewerk_catalog):
        """Heizungs-Gewerk."""
        h = gewerk_catalog.get("H")
        assert h is not None
        assert h.middle_group == 2
        assert h.category == "heizung"

    def test_get_unknown_gewerk(self, gewerk_catalog):
        """Unbekanntes Gewerk gibt None zurueck."""
        result = gewerk_catalog.get("UNKNOWN")
        assert result is None

    def test_add_custom_gewerk(self, gewerk_catalog):
        """Benutzerdefiniertes Gewerk hinzufuegen (FA-303)."""
        custom = Gewerk(
            code="ZZ", name="Testgewerk",
            ga_count=5, block_size=5, middle_group=4,
            category="allgemein",
        )
        gewerk_catalog.add_custom(custom)

        zz = gewerk_catalog.get("ZZ")
        assert zz is not None
        assert zz.is_custom is True
        assert zz.name == "Testgewerk"


class TestKnxProjectSaveLoad:
    """Tests fuer Projekt speichern/laden (.knxarr)."""

    def test_save_and_load_project(self, eg_room_with_gewerke, gewerk_catalog):
        """Projekt speichern und laden."""
        from knix_arranger.services.address_generator import AddressGenerator

        project = KnxProject(name="Test Projekt")
        project.areal = eg_room_with_gewerke

        gen = AddressGenerator(gewerk_catalog, variant="A")
        project.group_addresses = gen.generate(eg_room_with_gewerke)

        with tempfile.NamedTemporaryFile(
            suffix=".knxarr", delete=False
        ) as f:
            filepath = f.name

        try:
            project.save(filepath)
            assert os.path.exists(filepath)

            loaded = KnxProject.load(filepath)
            assert loaded.name == "Test Projekt"
            assert loaded.areal is not None
            assert loaded.areal.name == "Test"
            assert len(loaded.areal.all_rooms) > 0
        finally:
            os.unlink(filepath)

    def test_save_load_preserves_ga(self, eg_room_with_gewerke, gewerk_catalog):
        """Speichern/Laden bewahrt Gruppenadressen."""
        from knix_arranger.services.address_generator import AddressGenerator

        project = KnxProject(name="GA Test")
        project.areal = eg_room_with_gewerke

        gen = AddressGenerator(gewerk_catalog, variant="A")
        project.group_addresses = gen.generate(eg_room_with_gewerke)

        with tempfile.NamedTemporaryFile(
            suffix=".knxarr", delete=False
        ) as f:
            filepath = f.name

        try:
            project.save(filepath)
            loaded = KnxProject.load(filepath)

            assert loaded.group_addresses is not None
            orig_count = len(project.group_addresses.all_addresses())
            loaded_count = len(loaded.group_addresses.all_addresses())
            assert loaded_count == orig_count
        finally:
            os.unlink(filepath)

    def test_save_load_preserves_config(self):
        """Speichern/Laden bewahrt Konfiguration."""
        project = KnxProject(name="Config Test")
        project.config.mg_variant = "B"
        project.config.topology_mode = "TP-64"

        with tempfile.NamedTemporaryFile(
            suffix=".knxarr", delete=False
        ) as f:
            filepath = f.name

        try:
            project.save(filepath)
            loaded = KnxProject.load(filepath)

            assert loaded.config.mg_variant == "B"
            assert loaded.config.topology_mode == "TP-64"
        finally:
            os.unlink(filepath)

    def test_load_nonexistent_file(self):
        """Laden nicht existierender Datei."""
        with pytest.raises(Exception):
            KnxProject.load("nicht_vorhanden.knxarr")
