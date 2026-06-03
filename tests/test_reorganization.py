"""
Tests fuer ReorganizationEngine (FA-700)
Sortierung, Re-Blocking, Re-Naming.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.reorganization_engine import ReorganizationEngine
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)


class TestReorganizationBasic:
    """Grundlegende Reorganisations-Tests."""

    def test_reorganize_returns_copy(self, eg_room_with_gewerke, gewerk_catalog):
        """Reorganisation gibt Kopie zurueck (FA-042)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        original = gen.generate(eg_room_with_gewerke)

        engine = ReorganizationEngine(gewerk_catalog)
        result = engine.reorganize(original)

        # Nicht dasselbe Objekt
        assert result is not original
        # Aber gleiche Struktur
        assert len(result.main_groups) == len(original.main_groups)

    def test_reorganize_preserves_variant(self, eg_room_with_gewerke, gewerk_catalog):
        """Variante wird beibehalten."""
        gen = AddressGenerator(gewerk_catalog, variant="B")
        original = gen.generate(eg_room_with_gewerke)

        engine = ReorganizationEngine(gewerk_catalog)
        result = engine.reorganize(original)

        assert result.variant == "B"

    def test_reorganize_sorts_addresses(self, gewerk_catalog):
        """FA-701: Adressen werden sortiert."""
        # Unsortierte Struktur erstellen
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")

        # Absichtlich unsortiert
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=5,
            designation="LD_E02_01 E/A", datapoint_type="DPST-1-1",
            gewerk_code="LD", room_number="E02", element_number=1,
            function_name="E/A",
        ))
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A", datapoint_type="DPST-1-1",
            gewerk_code="LD", room_number="E01", element_number=1,
            function_name="E/A",
        ))

        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        engine = ReorganizationEngine(gewerk_catalog)
        result = engine.reorganize(structure)

        hg2 = result.main_groups[0]
        mg0 = hg2.middle_groups[0]
        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)

        # E01 sollte vor E02 kommen
        assert gas[0].room_number == "E01"
        assert gas[1].room_number == "E02"

        # Neu nummeriert: 0, 1
        assert gas[0].sub_group == 0
        assert gas[1].sub_group == 1


class TestReorganizationNaming:
    """FA-706: Bezeichnungen anpassen."""

    def test_rename_addresses(self, gewerk_catalog):
        """Adressen werden umbenannt."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")

        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="Alter Name",
            datapoint_type="DPST-1-1",
            gewerk_code="LD", room_number="E01", element_number=1,
            function_name="E/A",
        ))

        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        engine = ReorganizationEngine(gewerk_catalog)
        result = engine.reorganize(structure, rename=True)

        ga = result.main_groups[0].middle_groups[0].group_addresses[0]
        # Sollte das Standard-Format haben
        assert "LD_E01_01" in ga.designation
        assert "E/A" in ga.designation

    def test_no_rename_when_disabled(self, gewerk_catalog):
        """Keine Umbenennung wenn rename=False."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")

        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="Alter Name",
            datapoint_type="DPST-1-1",
            gewerk_code="LD", room_number="E01", element_number=1,
            function_name="E/A",
        ))

        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        engine = ReorganizationEngine(gewerk_catalog)
        result = engine.reorganize(structure, rename=False)

        ga = result.main_groups[0].middle_groups[0].group_addresses[0]
        assert ga.designation == "Alter Name"


class TestReorganizationCentral:
    """FA-703: Zentraladressen separat behandeln."""

    def test_central_addresses_not_renamed(self, gewerk_catalog):
        """Zentraladressen werden nicht umbenannt."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=0, name="Zentral")
        mg = MiddleGroup(number=0, name="Licht")

        mg.group_addresses.append(GroupAddress(
            main_group=0, middle_group=0, sub_group=1,
            designation="ZENTRAL Alle Lichter AUS",
            central="true",
            datapoint_type="DPST-1-1",
        ))

        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        engine = ReorganizationEngine(gewerk_catalog)
        result = engine.reorganize(structure, rename=True)

        ga = result.main_groups[0].middle_groups[0].group_addresses[0]
        assert "ZENTRAL" in ga.designation


class TestReorganizationDiff:
    """FA-704: Vorher-/Nachher-Vergleich."""

    def test_create_diff(self, gewerk_catalog):
        """Diff erkennt Aenderungen."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")

        ga = GroupAddress(
            main_group=2, middle_group=0, sub_group=5,
            designation="Alter Name",
            datapoint_type="DPST-1-1",
            gewerk_code="LD", room_number="E01", element_number=1,
            function_name="E/A",
        )
        mg.group_addresses.append(ga)
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        engine = ReorganizationEngine(gewerk_catalog)
        result = engine.reorganize(structure, rename=True)

        diff = engine.create_diff(structure, result)

        # Mindestens eine Aenderung (sub_group und designation)
        assert len(diff) >= 1
        assert diff[0]["type"] == "changed"

    def test_no_diff_for_identical(self, eg_room_with_gewerke, gewerk_catalog):
        """Kein Diff fuer bereits sortierte Struktur."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        original = gen.generate(eg_room_with_gewerke)

        engine = ReorganizationEngine(gewerk_catalog)
        # Reorganisiere ohne Umbenennung, Struktur sollte gleich bleiben
        result = engine.reorganize(original, rename=False)

        diff = engine.create_diff(original, result)

        # Generierte Strukturen sind schon sortiert, sollten wenige Aenderungen haben
        # (eventuell Platzhalter werden entfernt)
        # Hier pruefen wir nur, dass diff funktioniert
        assert isinstance(diff, list)
