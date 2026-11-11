"""
Berichtslayout (Berichte-Durchsicht 2026-11-10, Befunde 21-24): schmale
Kopfzeile auf Folgeseiten, kein leerer Doppelumbruch, verkleinertes Logo,
reduzierte Schriften.
"""
from __future__ import annotations

import fitz

from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.utils.pdf_generator import LOGO_MAX_PX, PdfGenerator


def _logo(tmp_path, width=4000, height=1500) -> str:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.clear_with(200)
    path = tmp_path / "logo.jpg"
    pix.save(str(path))
    return str(path)


def _pdf(tmp_path, logo="") -> PdfGenerator:
    company = CompanyProfile(company_name="Muster SmartHome & Energiemanagement AG",
                             user_name="Max Muster", address="Dorfstrasse 1; 8000 Zürich",
                             phone="+41 44 000 00 00", email="info@muster-smarthome.ch",
                             logo_path=logo)
    pdf = PdfGenerator(title="Testbericht", company_profile=company, project_name="Chalet")
    pdf.add_heading("Testbericht", level=1)
    return pdf


def test_follow_pages_have_compact_header(tmp_path):
    pdf = _pdf(tmp_path)
    pdf.add_paragraph("Seite 1")
    pdf.add_page_break()
    pdf.add_paragraph("Seite 2")
    path = tmp_path / "t.pdf"
    pdf.save(str(path))
    with fitz.open(path) as doc:
        first, second = doc[0].get_text(), doc[1].get_text()
    assert "Dorfstrasse 1" in first and "Dorfstrasse 1" not in second
    assert "Chalet  ·  Testbericht" in second           # Projekt und Titel im Kopf
    assert "Testbericht  ·  Max Muster" in second       # Titel im Fuss


def test_page_break_on_empty_page_adds_no_page(tmp_path):
    pdf = _pdf(tmp_path)
    pdf.add_page_break()
    pdf.add_page_break()
    pdf.add_paragraph("Inhalt")
    path = tmp_path / "t.pdf"
    pdf.save(str(path))
    with fitz.open(path) as doc:
        assert len(doc) == 2


def test_large_logo_is_downscaled_and_fonts_subset(tmp_path):
    pdf = _pdf(tmp_path, logo=_logo(tmp_path))
    pdf.add_paragraph("Umlaute: äöü")
    path = tmp_path / "t.pdf"
    pdf.save(str(path))
    with fitz.open(path) as doc:
        widths = {img[2] for page in doc for img in page.get_images()}
        assert widths == {LOGO_MAX_PX}
        assert "Umlaute: äöü" in doc[0].get_text()
    assert path.stat().st_size < 150_000          # vorher ~500 KB (Inter vollständig)
