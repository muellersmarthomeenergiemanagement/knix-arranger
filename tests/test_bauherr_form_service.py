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


class TestColumnWidthAndRowHeight:
    """FA-1502c-Nachfolger: lange Taster-Bezeichnungen (z.B. ausführliche
    Freitext-Labels aus einem Import) wurden bei fester Spaltenbreite/
    Zeilenhöhe abgeschnitten dargestellt, obwohl der Zellinhalt vollständig
    war."""

    def test_room_sheet_columns_wider_than_before(self, tmp_path):
        from knix_arranger.models.building import SensorFunktion
        room = Room(number="E01", name="Wohnzimmer")
        be = Bedienelement(
            element_type="Tastereinheit", channels=1,
            funktionen=[SensorFunktion(label="Licht schalten")],
        )
        room.bedienelemente = [be]
        project = _make_project(room)

        filepath = str(tmp_path / "formular.xlsx")
        BauherrFormService(project).generate_form(filepath)

        from openpyxl import load_workbook
        wb = load_workbook(filepath)
        ws = wb["E01 Wohnzimmer"]
        assert ws.column_dimensions["A"].width == 34
        assert ws.column_dimensions["B"].width == 34
        wb.close()

    def test_long_label_gets_taller_row_than_short_one(self, tmp_path):
        """Eine sehr lange Taster-Bezeichnung braucht mehr Zeilenhöhe als
        eine kurze -- vorher war jede Taster-Zeile fix 40px hoch, egal wie
        viel Text tatsächlich hineinmusste."""
        from knix_arranger.models.building import SensorFunktion
        room = Room(number="E01", name="Wohnzimmer")
        long_label = (
            "Liftschacht Leckage Alarm Signalton Stummschaltung "
            "(1 = stumm | 0 = nicht stumm, dauerhafte Zusatzbeschreibung)"
        )
        be = Bedienelement(
            element_type="Tastereinheit", channels=2,
            funktionen=[
                SensorFunktion(label="Licht"),
                SensorFunktion(label=long_label),
            ],
        )
        room.bedienelemente = [be]
        project = _make_project(room)

        filepath = str(tmp_path / "formular.xlsx")
        BauherrFormService(project).generate_form(filepath)

        from openpyxl import load_workbook
        wb = load_workbook(filepath)
        ws = wb["E01 Wohnzimmer"]
        taster_row = next(
            r for r in range(1, ws.max_row + 1)
            if ws.cell(row=r, column=1).value
            and str(ws.cell(row=r, column=1).value).startswith("T1")
        )
        assert ws.row_dimensions[taster_row].height > 30
        wb.close()

    def test_estimate_row_height_scales_with_text_length(self):
        svc_cls = BauherrFormService
        short_h = svc_cls._estimate_row_height(["T1  Licht"], col_width=34)
        long_h = svc_cls._estimate_row_height(
            ["T1  " + "Sehr langer Text " * 10], col_width=34,
        )
        assert long_h > short_h

    def test_estimate_row_height_respects_explicit_newline(self):
        svc_cls = BauherrFormService
        one_line = svc_cls._estimate_row_height(["T1  Licht"], col_width=34)
        two_lines = svc_cls._estimate_row_height(
            ["T1  Licht\nkurz: Umschalten"], col_width=34,
        )
        assert two_lines > one_line


class TestSignatureBlock:
    """FA-1501: Auftragsbestätigung (Datum + Unterschrift Bauherr) auf dem
    Titelblatt, mit der der Bauherr dem Integrator die Tastenbelegung als
    verbindliche Grundlage bestätigt."""

    def test_signature_block_present_on_overview_sheet(self, tmp_path):
        room = Room(number="E01", name="Wohnzimmer")
        room.bedienelemente = [Bedienelement(element_type="Tastereinheit", channels=1)]
        project = _make_project(room)

        filepath = str(tmp_path / "formular.xlsx")
        BauherrFormService(project).generate_form(filepath)

        from openpyxl import load_workbook
        wb = load_workbook(filepath)
        overview = wb["Funktionsdefinition"]
        values = [
            cell.value
            for row in overview.iter_rows()
            for cell in row
            if cell.value
        ]
        assert any("Auftragsbestätigung" in v for v in values)
        assert any(v == "Ort, Datum:" for v in values)
        assert any(v == "Unterschrift Bauherr:" for v in values)
        wb.close()


class TestNurBedienelementeUndEindeutigeRaeume:
    """Sensoren gehören nicht ins Bauherr-Formular; Raumnummern wie "00"
    kommen in importierten Projekten auf mehreren Stockwerken vor."""

    def _two_floor_project(self):
        from knix_arranger.models.building import SensorFunktion
        halle = Room(number="00", name="Halle")
        galerie = Room(number="00", name="Galerie")
        halle.bedienelemente = [
            Bedienelement(element_type="Tastereinheit", participant_number="1.1.50",
                          is_auto=False, funktionen=[SensorFunktion(label="Licht")]),
            Bedienelement(element_type="Wassermelder", participant_number="1.1.33"),
        ]
        galerie.bedienelemente = [
            Bedienelement(element_type="Tastereinheit", participant_number="1.1.53",
                          is_auto=False, funktionen=[SensorFunktion(label="Licht")]),
        ]
        floors = []
        for name, room in (("OG", halle), ("DG", galerie)):
            floor = Floor(name=name, short_code=name)
            floor.apartments = [Apartment(rooms=[room])]
            floors.append(floor)
        project = KnxProject(name="Import")
        project.areal = Areal(buildings=[Building(wings=[Wing(floors=floors)])])
        return project, halle, galerie

    def test_blattnamen_mit_stockwerk_und_ohne_sensoren(self, tmp_path):
        from openpyxl import load_workbook
        project, _halle, _galerie = self._two_floor_project()
        path = str(tmp_path / "f.xlsx")
        BauherrFormService(project).generate_form(path)
        wb = load_workbook(path)
        assert "OG 00 Halle" in wb.sheetnames
        assert "DG 00 Galerie" in wb.sheetnames
        text = " ".join(str(c.value) for row in wb["OG 00 Halle"].iter_rows() for c in row if c.value)
        assert "1.1.50" in text and "1.1.33" not in text      # Wassermelder fehlt
        overview = {r[0]: r for r in wb["Funktionsdefinition"].iter_rows(values_only=True) if r and r[0]}
        assert overview["OG 00"][2] == "1"                     # nur das Bedienelement

    def test_einlesen_trifft_richtigen_raum(self, tmp_path):
        from openpyxl import load_workbook
        project, halle, galerie = self._two_floor_project()
        path = str(tmp_path / "f.xlsx")
        BauherrFormService(project).generate_form(path)

        wb = load_workbook(path)
        ws = wb["DG 00 Galerie"]
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("T1  "):
                    cell.value = "T1  Leselicht"
        wb.save(path)

        BauherrFormService(project).import_form(path)
        assert galerie.bedienelemente[0].funktionen[0].label == "Leselicht"
        assert halle.bedienelemente[0].funktionen[0].label == "Licht"
