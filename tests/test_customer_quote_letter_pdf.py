"""
Tests fuer den Offert-Brief (PDF) in CustomerQuoteView._write_quote_letter_pdf.

Deckt die bei der Review gefundenen und behobenen Fehler ab:
- Trennlinie darf nicht durch den Text der ersten Tabellenzeile laufen.
- Lange Produktnamen werden gekuerzt statt die Nachbarspalte zu ueberlappen.
- Tabellenkopf wird bei Seitenumbruch wiederholt.
- Seitenzahlen nur bei mehrseitigen Briefen.
- Zwischensumme/Nettobetrag fett dargestellt.
- Positionspreise zeigen den Kundenendpreis (inkl. Aufschlag), nicht den
  Einkaufspreis.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from unittest.mock import patch

from knix_arranger.models.project import KnxProject
from knix_arranger.models.material_list import MaterialEntry
from knix_arranger.models.quotation import CustomerQuote, QuotationItem
from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.services.project_service import ProjectService
from knix_arranger.ui.views.customer_quote_view import CustomerQuoteView

fitz = pytest.importorskip("fitz")


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_view(project: KnxProject) -> CustomerQuoteView:
    view = CustomerQuoteView()
    view.set_project(project)
    return view


def _horizontal_line_ys(page) -> list[float]:
    ys = []
    for dw in page.get_drawings():
        if dw["type"] != "s":
            continue
        for item in dw.get("items", []):
            if item[0] == "l":
                p0, p1 = item[1], item[2]
                if abs(p0.y - p1.y) < 0.01:
                    ys.append(p0.y)
    return ys


def _span_origin_y(page, text_fragment: str) -> float | None:
    d = page.get_text("dict")
    for block in d["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if text_fragment in span["text"]:
                    return span["origin"][1]
    return None


def _bold_fonts(page, text_fragment: str) -> list[str]:
    d = page.get_text("dict")
    fonts = []
    for block in d["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip() == text_fragment:
                    fonts.append(span["font"])
    return fonts


class TestLetterRendering:
    def test_no_horizontal_line_through_first_row_text(self, tmp_path):
        """Regression: die Kopf/Body-Trennlinie darf nicht auf der Baseline
        der ersten Datenzeile liegen (frueher: sichtbarer Strikethrough)."""
        project = KnxProject(name="Test")
        cq = CustomerQuote(quote_number="OF-1", material_total=1000.0,
                            material_markup_percent=10.0)
        cq.items.append(QuotationItem(
            position=1, product_name="ErsteZeileEindeutig",
            quantity=1, unit_price=10.0, total_price=10.0,
        ))
        project.customer_quotes.append(cq)
        view = _make_view(project)

        filepath = str(tmp_path / "brief.pdf")
        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()):
            view._write_quote_letter_pdf(cq, project.name, filepath)

        doc = fitz.open(filepath)
        page = doc[0]
        row_y = _span_origin_y(page, "ErsteZeileEindeutig")
        assert row_y is not None
        line_ys = _horizontal_line_ys(page)
        assert all(abs(row_y - ly) > 1.0 for ly in line_ys), (
            f"Horizontale Linie bei y={line_ys} liegt auf der Textbaseline "
            f"der ersten Zeile (y={row_y}) -- Strikethrough-Bug."
        )
        doc.close()

    def test_long_product_name_is_truncated(self, tmp_path):
        """Ein sehr langer Produktname darf nicht unveraendert (und damit
        ueberlappend) dargestellt werden, sondern wird mit '…' gekuerzt."""
        project = KnxProject(name="Test")
        cq = CustomerQuote(quote_number="OF-1", material_total=1000.0)
        long_name = "Präsenzmelder KNX Secure UP-Einbau mit Konstantlichtregelung und Zusatzfunktionen [ABB 6131/2.0-101]"
        cq.items.append(QuotationItem(
            position=1, product_name=long_name,
            quantity=1, unit_price=10.0, total_price=10.0,
        ))
        project.customer_quotes.append(cq)
        view = _make_view(project)

        filepath = str(tmp_path / "brief.pdf")
        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()):
            view._write_quote_letter_pdf(cq, project.name, filepath)

        doc = fitz.open(filepath)
        full_text = doc[0].get_text()
        doc.close()
        assert long_name not in full_text, (
            "Langer Produktname wurde unverkuerzt dargestellt -- "
            "ueberlappt vermutlich die Nachbarspalte."
        )
        assert "..." in full_text

    def test_table_header_repeated_on_page_break(self, tmp_path):
        """Bei einer Offerte mit vielen Positionen muss der Tabellenkopf
        auch auf Folgeseiten erscheinen."""
        project = KnxProject(name="Test")
        cq = CustomerQuote(quote_number="OF-1", material_total=1000.0)
        for i in range(1, 46):
            cq.items.append(QuotationItem(
                position=i, product_name=f"Produkt {i}",
                quantity=1, unit_price=10.0, total_price=10.0,
            ))
        project.customer_quotes.append(cq)
        view = _make_view(project)

        filepath = str(tmp_path / "brief.pdf")
        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()):
            view._write_quote_letter_pdf(cq, project.name, filepath)

        doc = fitz.open(filepath)
        assert doc.page_count > 1, "Test setzt einen Seitenumbruch voraus"
        for page in doc:
            text = page.get_text()
            assert "Produkt / Leistung" in text, (
                "Tabellenkopf fehlt auf einer Seite nach Seitenumbruch"
            )
        doc.close()

    def test_page_numbers_only_when_multipage(self, tmp_path):
        project = KnxProject(name="Test")

        # Einseitige Offerte: keine Seitenzahl
        cq_short = CustomerQuote(quote_number="OF-1", material_total=1000.0)
        cq_short.items.append(QuotationItem(
            position=1, product_name="X", quantity=1,
            unit_price=10.0, total_price=10.0,
        ))
        project.customer_quotes.append(cq_short)
        view = _make_view(project)
        short_path = str(tmp_path / "kurz.pdf")
        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()):
            view._write_quote_letter_pdf(cq_short, project.name, short_path)
        doc = fitz.open(short_path)
        assert doc.page_count == 1
        assert "Seite" not in doc[0].get_text()
        doc.close()

        # Mehrseitige Offerte: Seitenzahlen vorhanden
        cq_long = CustomerQuote(quote_number="OF-2", material_total=1000.0)
        for i in range(1, 46):
            cq_long.items.append(QuotationItem(
                position=i, product_name=f"Produkt {i}", quantity=1,
                unit_price=10.0, total_price=10.0,
            ))
        project.customer_quotes.append(cq_long)
        long_path = str(tmp_path / "lang.pdf")
        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()):
            view._write_quote_letter_pdf(cq_long, project.name, long_path)
        doc = fitz.open(long_path)
        assert doc.page_count > 1
        assert f"Seite 1 von {doc.page_count}" in doc[0].get_text()
        assert f"Seite {doc.page_count} von {doc.page_count}" in doc[-1].get_text()
        doc.close()

    def test_subtotal_and_net_total_rows_are_bold(self, tmp_path):
        project = KnxProject(name="Test")
        cq = CustomerQuote(
            quote_number="OF-1", material_total=1000.0,
            material_markup_percent=10.0, overhead_costs=50.0,
        )
        project.customer_quotes.append(cq)
        view = _make_view(project)

        filepath = str(tmp_path / "brief.pdf")
        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()):
            view._write_quote_letter_pdf(cq, project.name, filepath)

        doc = fitz.open(filepath)
        page = doc[0]
        assert all("Bold" in f for f in _bold_fonts(page, "Zwischensumme"))
        assert all("Bold" in f for f in _bold_fonts(page, "Nettobetrag"))
        assert not any("Bold" in f for f in _bold_fonts(page, "Nebenkosten"))
        doc.close()


class TestLetterShowsCustomerPrice:
    """Regression: die EP/GP-Spalten im Brief muessen den Kundenendpreis
    (inkl. Material-Aufschlag) zeigen, nicht den Einkaufspreis."""

    def test_item_imported_from_material_list_shows_marked_up_price(self, tmp_path):
        project = KnxProject(name="Test")
        project.material_list.entries.append(MaterialEntry(
            quantity=1, manufacturer="ABB", order_number="X1",
            product_name="Schaltaktor", unit_price=100.0,
        ))
        view = _make_view(project)
        view._add_quote()
        cq = view._get_selected_quote()
        view._material_markup.setValue(20.0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()

        filepath = str(tmp_path / "brief.pdf")
        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()):
            view._write_quote_letter_pdf(cq, project.name, filepath)

        doc = fitz.open(filepath)
        full_text = doc[0].get_text()
        doc.close()

        # Einkaufspreis 100.00 wurde mit 20% Aufschlag zu 120.00 -- der
        # rohe Einkaufspreis darf so nicht mehr auftauchen.
        assert "120.00" in full_text
        assert "100.00" not in full_text
