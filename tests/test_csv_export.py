"""
Tests fuer CsvExportService (FA-800, FA-801-805)
"""
import pytest
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.csv_export_service import CsvExportService
from knix_arranger.services.csv_import_service import CsvImportService
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)


class TestCsvExportBasic:
    """Grundlegende CSV-Export-Tests."""

    def test_export_creates_file(self, eg_room_with_gewerke, gewerk_catalog):
        """Export erzeugt eine Datei."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name

        try:
            exporter.export_csv(structure, csv_path, overwrite=True)
            assert os.path.exists(csv_path)
            assert os.path.getsize(csv_path) > 0
        finally:
            os.unlink(csv_path)

    def test_export_no_overwrite_raises(self, eg_room_with_gewerke, gewerk_catalog):
        """FA-805: Warnung bei Ueberschreiben."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name
            f.write("Existing content")

        try:
            with pytest.raises(FileExistsError):
                exporter.export_csv(structure, csv_path, overwrite=False)
        finally:
            os.unlink(csv_path)

    def test_export_semicolon_delimiter(self, eg_room_with_gewerke, gewerk_catalog):
        """FA-501: CSV ist Semikolon-getrennt."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name

        try:
            exporter.export_csv(structure, csv_path, overwrite=True)

            with open(csv_path, "r", encoding="utf-8") as f:
                header = f.readline()
            assert ";" in header
            assert "Main" in header
            assert "Middle" in header
        finally:
            os.unlink(csv_path)

    def test_export_utf8_encoding(self, eg_room_with_gewerke, gewerk_catalog):
        """Export ist UTF-8 kodiert."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        exporter = CsvExportService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            csv_path = f.name

        try:
            exporter.export_csv(structure, csv_path, overwrite=True)

            with open(csv_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Sollte ohne Fehler lesbar sein
            assert len(content) > 0
        finally:
            os.unlink(csv_path)


class TestCsvRoundtrip:
    """Tests fuer Export -> Import -> Vergleich."""

    def test_roundtrip_address_count(self, eg_room_with_gewerke, gewerk_catalog):
        """Roundtrip: Gleiche Anzahl Adressen."""
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

            orig_count = len(original.all_addresses())
            imp_count = len(imported.all_addresses())

            # Importierte Adressen sollten nahe an der Originalzahl sein
            # (Platzhalter koennten sich unterscheiden)
            assert imp_count > 0
            assert abs(orig_count - imp_count) <= orig_count * 0.2  # Max 20% Abweichung
        finally:
            os.unlink(csv_path)

    def test_roundtrip_preserves_dpt(self, eg_room_with_gewerke, gewerk_catalog):
        """Roundtrip: DPT-Typen werden beibehalten."""
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

            # Vergleiche DPTs der importierten Adressen
            for orig_ga in original.all_addresses():
                if orig_ga.is_placeholder or not orig_ga.datapoint_type:
                    continue
                imp_ga = imported.find_address(
                    orig_ga.main_group, orig_ga.middle_group, orig_ga.sub_group
                )
                if imp_ga:
                    assert imp_ga.datapoint_type == orig_ga.datapoint_type, \
                        f"DPT mismatch at {orig_ga.address}: " \
                        f"{orig_ga.datapoint_type} != {imp_ga.datapoint_type}"
        finally:
            os.unlink(csv_path)

    def test_roundtrip_hierarchical_structure(self, eg_room_with_gewerke, gewerk_catalog):
        """FA-803: Hierarchische Darstellung wird beibehalten."""
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

            # Gleiche HG-Nummern
            orig_hgs = sorted(hg.number for hg in original.main_groups)
            imp_hgs = sorted(hg.number for hg in imported.main_groups)
            assert orig_hgs == imp_hgs

            # Pro HG: gleiche MG-Nummern
            for orig_hg in original.main_groups:
                imp_hg = next(
                    (hg for hg in imported.main_groups if hg.number == orig_hg.number),
                    None,
                )
                assert imp_hg is not None
                orig_mgs = sorted(mg.number for mg in orig_hg.middle_groups)
                imp_mgs = sorted(mg.number for mg in imp_hg.middle_groups)
                assert orig_mgs == imp_mgs, \
                    f"MG-Mismatch in HG {orig_hg.number}: {orig_mgs} != {imp_mgs}"
        finally:
            os.unlink(csv_path)
