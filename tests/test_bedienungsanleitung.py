"""
Die Bedienungsanleitung wird mit der App ausgeliefert (Hilfe → Bedienungsanleitung).
Erzeugt mit: python tools/update_betatester_anleitung.py --pdf
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import knix_arranger

HANDBUCH = Path(knix_arranger.__file__).parent / "data" / "KNiX_Arranger_Handbuch.pdf"


def test_handbuch_pdf_is_shipped():
    assert HANDBUCH.is_file(), "Bedienungsanleitung fehlt – tools/update_betatester_anleitung.py --pdf ausführen"
    assert HANDBUCH.read_bytes()[:5] == b"%PDF-"


def test_handbuch_matches_current_version():
    """Die Titelseite nennt die Programmversion – beim Release neu erzeugen."""
    fitz = __import__("fitz")
    with fitz.open(HANDBUCH) as doc:
        first_page = doc[0].get_text()
    assert f"Version {knix_arranger.__version__}" in first_page, (
        "Bedienungsanleitung stammt nicht von dieser Version – "
        "tools/update_betatester_anleitung.py --pdf ausführen"
    )
