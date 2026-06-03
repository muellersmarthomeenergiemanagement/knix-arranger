"""
Tests fuer CsvImportService (FA-500, FA-501-506)
Tests mit generiertem CSV und ggf. ETS6_Chalet.csv Referenzdatei.
"""
import pytest
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.csv_import_service import CsvImportService
from knix_arranger.services.csv_export_service import CsvExportService
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.models.group_address import GroupAddressStructure


# Referenz CSV-Pfad
REFERENCE_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ETS6_Chalet.csv"
)


class TestCsvImportBasic:
    """Grundlegende CSV-Import-Tests."""

    def test_import_generated_csv(self, eg_room_with_gewerke, gewerk_catalog):
        """Import einer generierten CSV-Datei."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()
        importer = CsvImportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name

        try:
            exporter.export_csv(structure, csv_path, overwrite=True)
            imported = importer.import_csv(csv_path)

            assert isinstance(imported, GroupAddressStructure)
            assert len(imported.main_groups) > 0
        finally:
            os.unlink(csv_path)

    def test_import_nonexistent_file(self):
        """Import einer nicht existierenden Datei wirft Fehler."""
        importer = CsvImportService()
        with pytest.raises(FileNotFoundError):
            importer.import_csv("nicht_vorhanden.csv")

    def test_import_preserves_structure(self, eg_room_with_gewerke, gewerk_catalog):
        """Import bewahrt hierarchische Struktur."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        original = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()
        importer = CsvImportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name

        try:
            exporter.export_csv(original, csv_path, overwrite=True)
            imported = importer.import_csv(csv_path)

            # Gleiche Anzahl Hauptgruppen
            assert len(imported.main_groups) == len(original.main_groups)

            # Gleiche HG-Nummern
            orig_hg_nums = sorted(hg.number for hg in original.main_groups)
            imp_hg_nums = sorted(hg.number for hg in imported.main_groups)
            assert orig_hg_nums == imp_hg_nums
        finally:
            os.unlink(csv_path)

    def test_import_preserves_addresses(self, eg_room_with_gewerke, gewerk_catalog):
        """Import bewahrt Gruppenadress-Werte."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        original = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()
        importer = CsvImportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name

        try:
            exporter.export_csv(original, csv_path, overwrite=True)
            imported = importer.import_csv(csv_path)

            orig_addresses = set(ga.address for ga in original.all_addresses())
            imp_addresses = set(ga.address for ga in imported.all_addresses())

            # Alle Originaladressen muessen importiert werden
            # (Platzhalter koennten leer exportiert werden)
            non_placeholder_orig = set(
                ga.address for ga in original.all_addresses()
                if not ga.is_placeholder
            )
            for addr in non_placeholder_orig:
                assert addr in imp_addresses, f"Adresse {addr} fehlt nach Import"
        finally:
            os.unlink(csv_path)


class TestCsvImportDesignation:
    """Tests fuer Bezeichnungs-Parsing beim Import."""

    def test_parse_gewerk_from_designation(self, eg_room_with_gewerke, gewerk_catalog):
        """Gewerk-Code wird aus Bezeichnung extrahiert."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        original = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()
        importer = CsvImportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name

        try:
            exporter.export_csv(original, csv_path, overwrite=True)
            imported = importer.import_csv(csv_path)

            # Finde eine Licht-Adresse
            hg2 = next(hg for hg in imported.main_groups if hg.number == 2)
            mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
            first_ga = sorted(mg0.group_addresses, key=lambda g: g.sub_group)[0]

            assert first_ga.gewerk_code == "LD"
            assert first_ga.room_number == "E01"
        finally:
            os.unlink(csv_path)


@pytest.mark.skipif(
    not os.path.exists(REFERENCE_CSV),
    reason="ETS6_Chalet.csv Referenzdatei nicht vorhanden"
)
class TestCsvImportReference:
    """Tests mit der ETS6_Chalet.csv Referenzdatei (AK-04)."""

    def test_import_ets6_chalet(self):
        """ETS6_Chalet.csv kann importiert werden."""
        importer = CsvImportService()
        structure = importer.import_csv(REFERENCE_CSV)

        assert isinstance(structure, GroupAddressStructure)
        assert len(structure.main_groups) > 0
        assert len(structure.all_addresses()) > 0

    def test_ets6_chalet_has_addresses(self):
        """ETS6_Chalet.csv hat Gruppenadressen."""
        importer = CsvImportService()
        structure = importer.import_csv(REFERENCE_CSV)

        all_gas = structure.all_addresses()
        assert len(all_gas) > 100  # Erwartet: >1000 Adressen

    def test_ets6_chalet_structure(self):
        """ETS6_Chalet.csv hat erwartete HG-Struktur."""
        importer = CsvImportService()
        structure = importer.import_csv(REFERENCE_CSV)

        hg_numbers = [hg.number for hg in structure.main_groups]
        assert 0 in hg_numbers  # HG 0 = Zentral
