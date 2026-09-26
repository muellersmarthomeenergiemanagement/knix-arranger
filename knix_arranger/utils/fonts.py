"""
Firmenschrift Inter für alle PDF-Dokumente.

Die statischen Schnitte Inter-Regular/Inter-Bold liegen in
knix_arranger/data/fonts (SIL Open Font License, siehe Inter-LICENSE.txt)
und werden mit der App ausgeliefert. Fehlen sie, wird auf eine lokal
installierte Inter bzw. zuletzt auf Helvetica zurückgefallen.
"""
from __future__ import annotations
import os

_BUNDLED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "fonts")


def _find_font(names: list[str]) -> str:
    dirs = [
        _BUNDLED_DIR,
        "C:/Windows/Fonts",
        os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts"),
    ]
    for d in dirs:
        for name in names:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return os.path.normpath(p)
    return ""


INTER_REGULAR = _find_font(["Inter-Regular.ttf", "Inter_Regular.ttf"])
INTER_BOLD = _find_font(["Inter-Bold.ttf", "Inter-SemiBold.ttf", "Inter_Bold.ttf"])

# PyMuPDF-Fontnamen (Fallback: Basis-14-Helvetica)
FONT_REGULAR = "inter" if INTER_REGULAR else "helv"
FONT_BOLD = "inter-bo" if INTER_BOLD else "hebo"

_font_cache: dict[bool, object] = {}


def register_fonts(page) -> None:
    """Bettet Inter in eine PyMuPDF-Seite ein (vor dem ersten insert_text)."""
    for name, path in ((FONT_REGULAR, INTER_REGULAR), (FONT_BOLD, INTER_BOLD)):
        if path:
            try:
                page.insert_font(fontname=name, fontfile=path)
            except Exception:
                pass


def font_name(bold: bool = False) -> str:
    return FONT_BOLD if bold else FONT_REGULAR


def text_length(text: str, fontsize: float, bold: bool = False) -> float:
    """Textbreite in Punkten für die Firmenschrift."""
    import fitz
    font = _font_cache.get(bold)
    if font is None:
        path = INTER_BOLD if bold else INTER_REGULAR
        font = fitz.Font(fontfile=path) if path else fitz.Font(
            fontname="hebo" if bold else "helv")
        _font_cache[bold] = font
    return font.text_length(text, fontsize)
