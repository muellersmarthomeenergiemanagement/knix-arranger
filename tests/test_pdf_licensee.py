"""PDF-Berichte: Lizenznehmer in Fusszeile und Dokumenteigenschaften."""
import pytest
import knix_arranger.services.license_service as _ls_module
from knix_arranger.utils.pdf_generator import PdfGenerator


def _report(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf = PdfGenerator(title="Test")
    pdf.add_paragraph("Inhalt")
    path = str(tmp_path / "t.pdf")
    pdf.save(path)
    return fitz.open(path)


def test_lizenznehmer_in_fusszeile_und_eigenschaften(tmp_path, monkeypatch):
    monkeypatch.setattr(_ls_module, "_licensed_to", "Elektro Muster AG")
    doc = _report(tmp_path)
    text = "".join(page.get_text() for page in doc)
    assert "Lizenziert für Elektro Muster AG" in text
    assert "Lizenziert für Elektro Muster AG" in doc.metadata["creator"]
    assert doc.metadata["creator"].startswith("KNiX Arranger ")


def test_ohne_lizenz_kein_hinweis(tmp_path, monkeypatch):
    monkeypatch.setattr(_ls_module, "_licensed_to", "")
    doc = _report(tmp_path)
    text = "".join(page.get_text() for page in doc)
    assert "Lizenziert" not in text
    assert "Lizenziert" not in doc.metadata["creator"]
