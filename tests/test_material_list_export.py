"""Tests fuer den Excel-Export der Materialliste (FA-2307)."""
import pytest

openpyxl = pytest.importorskip("openpyxl")

from knix_arranger.models.material_list import MaterialEntry, MaterialList
from knix_arranger.services.material_list_export_service import MaterialListExportService


def _cells(ws) -> list[list]:
    return [list(row) for row in ws.iter_rows(values_only=True)]


def _find_row(rows, first_value):
    return next(r for r in rows if r and r[0] == first_value)


@pytest.fixture
def material_list():
    return MaterialList(entries=[
        MaterialEntry(quantity=2, category="Aktor", device_type="Schaltaktor 8-fach",
                      manufacturer="MDT", order_number="AKS-0816.03",
                      product_name="Schaltaktor 8-fach", unit_price=250.0,
                      installation_location="UV1", line_name="1.1.0 EG"),
        MaterialEntry(quantity=3, category="Aktor", device_type="Jalousieaktor 4-fach"),
        MaterialEntry(quantity=1, category="Netzteil", device_type="Netzteil 640 mA",
                      manufacturer="ABB", order_number="SV/S30.640.5.1", unit_price=180.5),
    ])


@pytest.fixture
def exported(material_list, tmp_path):
    path = tmp_path / "materialliste"
    MaterialListExportService().export_xlsx(material_list, "Testprojekt", str(path))
    return tmp_path / "materialliste.xlsx"


def test_file_gets_xlsx_extension(exported):
    assert exported.exists()


def test_two_sheets(exported):
    wb = openpyxl.load_workbook(exported)
    assert len(wb.sheetnames) == 2
    assert wb.sheetnames[1] == "Zusammenfassung"


def test_positions_sheet_lists_all_entries(exported):
    rows = _cells(openpyxl.load_workbook(exported).worksheets[0])
    header = _find_row(rows, "Anz.")
    assert header[:6] == ["Anz.", "Kategorie", "Typ / Gerätebezeichnung",
                          "Hersteller", "Bestellnummer", "Produktname"]
    first = rows[rows.index(header) + 1]
    assert first[:5] == [2, "Aktor", "Schaltaktor 8-fach", "MDT", "AKS-0816.03"]
    assert first[6:10] == ["UV1", "1.1.0 EG", "250.00", "500.00"]


def test_placeholder_without_manufacturer(exported):
    rows = _cells(openpyxl.load_workbook(exported).worksheets[0])
    placeholder = next(r for r in rows if r and r[2] == "Jalousieaktor 4-fach")
    assert placeholder[3] == "– (Platzhalter)"
    # Ohne Produktname wird der Gerätetyp angezeigt, ohne Preis bleibt die Zelle leer
    assert placeholder[5] == "Jalousieaktor 4-fach"
    assert placeholder[8] in ("", None)


def test_total_line(exported):
    rows = _cells(openpyxl.load_workbook(exported).worksheets[0])
    text = " ".join(str(c) for r in rows for c in r if c)
    assert "Gesamtanzahl: 6 Geräte" in text
    assert "CHF 680.50" in text


def test_summary_per_category(exported):
    rows = _cells(openpyxl.load_workbook(exported).worksheets[1])
    assert _find_row(rows, "Aktor")[1:5] == [5, 2, 3, "500.00"]
    assert _find_row(rows, "Netzteil")[1:5] == [1, 1, 0, "180.50"]
    assert _find_row(rows, "TOTAL")[1:5] == [6, 3, 3, "680.50"]


def test_empty_list_exports(tmp_path):
    path = tmp_path / "leer.xlsx"
    MaterialListExportService().export_xlsx(MaterialList(), "Leer", str(path))
    rows = _cells(openpyxl.load_workbook(path).worksheets[1])
    assert _find_row(rows, "TOTAL")[1:4] == [0, 0, 0]
