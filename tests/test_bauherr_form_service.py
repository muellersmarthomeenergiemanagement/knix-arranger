"""
Tests fuer BauherrFormService (FA-1501-1504)
Schwerpunkt: gelöschte (suppressed) Bedienelemente dürfen im
Bauherren-Formular nicht mehr auftauchen.
"""
import pytest
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Bedienelement,
)
from knix_arranger.services.bauherr_form_service import BauherrFormService
from knix_arranger.utils.excel_generator import HAS_OPENPYXL

pytestmark = pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl nicht installiert")


def _make_project(room: Room) -> KnxProject:
    project = KnxProject(name="Test")
    apt = Apartment(name="WG")
    apt.rooms = [room]
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Test")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])
    return project


class TestSuppressedExcluded:
    def test_suppressed_be_excluded_from_overview_count(self, tmp_path):
        """Übersichtstabelle zählt gelöschte Geräte nicht mit."""
        room = Room(number="E01", name="Wohnzimmer")
        active_be = Bedienelement(element_type="Tastereinheit", channels=4)
        deleted_be = Bedienelement(
            element_type="Präsenzmelder", is_auto=False, suppressed=True,
        )
        room.bedienelemente = [active_be, deleted_be]
        project = _make_project(room)

        filepath = str(tmp_path / "formular.xlsx")
        BauherrFormService(project).generate_form(filepath)

        from openpyxl import load_workbook
        wb = load_workbook(filepath)
        overview = wb["Funktionsdefinition"]
        found_row = None
        for row in overview.iter_rows(values_only=True):
            if row and row[0] == "E01":
                found_row = row
                break
        assert found_row is not None, "Raumzeile E01 nicht in Übersicht gefunden"
        assert found_row[2] == "1", (
            f"Erwartet 1 aktives Bedienelement (gelöschtes ausgeklammert), "
            f"erhalten: {found_row[2]}"
        )
        wb.close()

    def test_room_sheet_skipped_when_only_suppressed_bes(self, tmp_path):
        """Ein Raum, dessen einziges Bedienelement gelöscht wurde, bekommt
        kein eigenes Blatt mehr (sonst erscheint das Gerät dort weiterhin)."""
        room = Room(number="E01", name="NurGeloescht")
        deleted_be = Bedienelement(
            element_type="Tastereinheit", is_auto=False, suppressed=True,
        )
        room.bedienelemente = [deleted_be]
        project = _make_project(room)

        filepath = str(tmp_path / "formular.xlsx")
        BauherrFormService(project).generate_form(filepath)

        from openpyxl import load_workbook
        wb = load_workbook(filepath)
        assert "E01 NurGeloescht" not in wb.sheetnames
        wb.close()
