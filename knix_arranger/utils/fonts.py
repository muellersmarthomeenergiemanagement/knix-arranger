"""
Firmenschrift Inter für alle PDF-Dokumente.

Die statischen Schnitte Inter-Regular/Inter-Bold liegen in
knix_arranger/data/fonts (SIL Open Font License, siehe Inter-LICENSE.txt)
und werden mit der App ausgeliefert. Fehlen sie, wird auf eine lokal
installierte Inter bzw. zuletzt auf Helvetica zurückgefallen.
"""
from __future__ import annotations
import os
import re

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


_CMAP_BLOCK_RE = re.compile(
    rb"(\d+)\s+begin(bfrange|bfchar)(.*?)end\2", re.DOTALL)
_HEX_TOKEN_RE = re.compile(rb"<([0-9A-Fa-f]*)>")


def _clean_cmap(data: bytes) -> bytes:
    """Entfernt ToUnicode-Einträge mit ungültiger Hex-Länge.

    PyMuPDF schreibt beim Einbetten von Inter die komplette Zeichentabelle
    der Schrift, auch Zeichen ausserhalb der Basisebene (z.B. U+1F16B) als
    '<1f16b>' statt als UTF-16-Paar. Strenge Viewer (Acrobat) verwerfen dann
    die ganze Tabelle – die Textsuche im PDF findet nichts mehr. Diese
    Zeichen kommen in Berichten nicht vor und werden daher weggelassen."""
    def block(m: re.Match) -> bytes:
        entries = [line for line in m.group(3).splitlines() if line.strip()]
        kept = [line for line in entries
                if all(len(t) % 4 == 0 for t in _HEX_TOKEN_RE.findall(line))]
        if len(kept) == len(entries):
            return m.group(0)
        body = b"\n".join(kept)
        return b"%d begin%s\n%s\nend%s" % (len(kept), m.group(2), body, m.group(2))
    return _CMAP_BLOCK_RE.sub(block, data)


def finalize_pdf(doc) -> None:
    """Vor dem Speichern jedes PDFs mit Inter aufrufen: bereinigt die
    ToUnicode-Tabellen (Textsuche, Kopieren), öffnet die Lesezeichen-
    Leiste beim Öffnen, sofern Lesezeichen vorhanden sind, und trägt
    Programm und Lizenznehmer in die Dokumenteigenschaften ein."""
    for xref in range(1, doc.xref_length()):
        try:
            kind, value = doc.xref_get_key(xref, "ToUnicode")
        except Exception:
            continue
        if kind != "xref":
            continue
        cmap_xref = int(value.split()[0])
        data = doc.xref_stream(cmap_xref)
        cleaned = _clean_cmap(data)
        if cleaned != data:
            doc.update_stream(cmap_xref, cleaned)
    if doc.get_toc():
        doc.set_pagemode("UseOutlines")
    _set_creator(doc)


def licensee_note() -> str:
    """«Lizenziert für …» für Berichte; leer ohne geprüfte Lizenz."""
    from ..services.license_service import licensed_to
    customer = licensed_to()
    return f"Lizenziert für {customer}" if customer else ""


def _set_creator(doc) -> None:
    from .. import __version__, __copyright__
    creator = f"KNiX Arranger {__version__}"
    note = licensee_note()
    if note:
        creator += f" – {note}"
    metadata = dict(doc.metadata or {})
    metadata["creator"] = creator
    # Copyright-Hinweis in jedem Bericht (NFA-082), unsichtbar für den Bauherrn
    metadata["producer"] = f"{creator} – {__copyright__}. Alle Rechte vorbehalten."
    doc.set_metadata(metadata)


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
