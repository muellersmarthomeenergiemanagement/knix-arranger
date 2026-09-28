"""PDF-Berichte: Textsuche (gueltige ToUnicode-Tabellen) und Lesezeichen-Leiste."""
import re
import pytest
from knix_arranger.utils.fonts import _clean_cmap, INTER_REGULAR
from knix_arranger.utils.pdf_generator import PdfGenerator


def test_cmap_ungueltige_eintraege_entfernt():
    cmap = (b"3 beginbfrange\n<0005> <0007> <00c0>\n<0010> <0011> <1f16b>\n"
            b"<0020> <0020> [<0041> <0042>]\nendbfrange\n"
            b"2 beginbfchar\n<0030> <1f850>\n<0031> <00e4>\nendbfchar")
    cleaned = _clean_cmap(cmap)
    assert b"1f16b" not in cleaned and b"1f850" not in cleaned
    assert b"2 beginbfrange" in cleaned and b"<0005> <0007> <00c0>" in cleaned
    assert b"1 beginbfchar" in cleaned and b"<0031> <00e4>" in cleaned


def test_gueltige_cmap_unveraendert():
    cmap = b"1 beginbfchar\n<0031> <00e4>\nendbfchar"
    assert _clean_cmap(cmap) == cmap


def test_bericht_durchsuchbar_mit_lesezeichen(tmp_path):
    fitz = pytest.importorskip("fitz")
    if not INTER_REGULAR:
        pytest.skip("Inter nicht vorhanden")
    pdf = PdfGenerator(title="Test")
    pdf.add_heading("Übersicht", level=2)
    pdf.add_paragraph("Geräte im Verteiler")
    path = str(tmp_path / "t.pdf")
    pdf.save(path)

    doc = fitz.open(path)
    assert "/PageMode/UseOutlines" in doc.xref_object(doc.pdf_catalog(), compressed=True)
    assert doc.get_toc()[0][1] == "Übersicht"
    for xref in range(1, doc.xref_length()):
        if doc.xref_is_stream(xref) and b"begincmap" in doc.xref_stream(xref):
            tokens = re.findall(rb"<([0-9A-Fa-f]*)>", doc.xref_stream(xref))
            assert all(len(t) % 4 == 0 for t in tokens)
    assert doc[0].search_for("Geräte")
    doc.close()
