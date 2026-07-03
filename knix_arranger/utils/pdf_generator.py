"""
PDF-Erzeugung (NFA-050, FA-855–857)
Erzeugt Berichte mit Firmenprofil-Header (Logo, Firma, Projekt)
und Footer (Bearbeiter, Seite X/Y) auf jeder Seite.
Schrift: Inter (falls installiert), sonst Helvetica.
Verwendet PyMuPDF wenn verfügbar, sonst Textformat.
"""
from __future__ import annotations
import os
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("knix_arranger.pdf_generator")

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    logger.info("PyMuPDF nicht installiert. PDF-Export nutzt Textformat.")


# ── Inter-Font suchen ─────────────────────────────────────────────────────────

def _find_font(names: list[str]) -> str:
    dirs = [
        "C:/Windows/Fonts",
        os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts"),
        os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"),
    ]
    for d in dirs:
        for name in names:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return ""


_INTER_REGULAR = _find_font(["Inter-Regular.ttf", "Inter_Regular.ttf", "Inter.ttf"])
_INTER_BOLD    = _find_font(["Inter-Bold.ttf", "Inter-SemiBold.ttf", "Inter_Bold.ttf"])


class PdfGenerator:
    """Erzeugt PDF-Dokumente für Berichte (FA-855–857)."""

    # A4 in Punkten
    PAGE_W  = 595
    PAGE_H  = 842
    MARGIN  = 50
    HEADER_H = 82
    FOOTER_H = 25

    # Tabellen-Maße
    TBL_HDR_H   = 16   # Kopfzeilenhöhe
    TBL_ROW_H   = 14   # Datenzeilenhöhe
    TBL_COL_PAD =  5   # Horizontaler Zellenabstand

    def __init__(self,
                 title: str = "",
                 company: str = "",
                 project_name: str = "",
                 company_profile=None,
                 project_info=None):
        self.title = title
        self.project_name = project_name

        if company_profile is not None:
            self.company         = company_profile.company_name
            self.company_address = company_profile.address
            self.company_phone   = company_profile.phone
            self.company_email   = company_profile.email
            self.logo_path       = company_profile.logo_path
            self.user_name       = company_profile.user_name
            self.user_role       = company_profile.role
        else:
            self.company         = company
            self.company_address = ""
            self.company_phone   = ""
            self.company_email   = ""
            self.logo_path       = ""
            self.user_name       = ""
            self.user_role       = ""

        if project_info is not None:
            self.project_name    = project_info.project_name or project_name
            self.project_number  = project_info.project_number
            self.client_name     = project_info.client_name
            self.project_address = project_info.project_address
            self.project_date    = project_info.date or datetime.now().strftime("%d.%m.%Y")
        else:
            self.project_number  = ""
            self.client_name     = ""
            self.project_address = ""
            self.project_date    = datetime.now().strftime("%d.%m.%Y")

        self._blocks: list[dict] = []
        self._client_profile = None   # ClientProfile für Deckblatt

        # Font-Objekte für Breitenberechnung (lazy)
        self._fitz_font_reg:  Any = None
        self._fitz_font_bold: Any = None

    # ── Font-Hilfsmethoden ────────────────────────────────────────────────────

    @property
    def _fn(self) -> str:
        """Fontname für normalen Text."""
        return "inter" if _INTER_REGULAR else "helv"

    @property
    def _fn_bold(self) -> str:
        """Fontname für fetten Text."""
        return "inter-bo" if _INTER_BOLD else "hebo"

    def _tw(self, text: str, fontsize: float, bold: bool = False) -> float:
        """Gibt die Textbreite in Punkten zurück."""
        if not HAS_PYMUPDF:
            return len(text) * fontsize * 0.52
        if bold:
            if self._fitz_font_bold is None:
                self._fitz_font_bold = (
                    fitz.Font(fontfile=_INTER_BOLD)
                    if _INTER_BOLD else fitz.Font(fontname="hebo")
                )
            return self._fitz_font_bold.text_length(text, fontsize)
        else:
            if self._fitz_font_reg is None:
                self._fitz_font_reg = (
                    fitz.Font(fontfile=_INTER_REGULAR)
                    if _INTER_REGULAR else fitz.Font(fontname="helv")
                )
            return self._fitz_font_reg.text_length(text, fontsize)

    def _txt(self, page, point, text: str, fontsize: float,
             bold: bool = False, color=(0, 0, 0)):
        """Fügt Text auf der Seite ein."""
        page.insert_text(
            point, text,
            fontsize=fontsize,
            fontname=self._fn_bold if bold else self._fn,
            color=color,
        )

    def set_client_profile(self, client_profile) -> None:
        """Aktiviert das Deckblatt mit Kundenprofil-Daten."""
        self._client_profile = client_profile

    # ── Inhalt hinzufügen ─────────────────────────────────────────────────────

    def add_heading(self, text: str, level: int = 1):
        self._blocks.append({"type": "heading", "text": text, "level": level})

    def add_paragraph(self, text: str):
        self._blocks.append({"type": "paragraph", "text": text})

    def add_table(self, headers: list[str], rows: list[list[str]],
                  col_widths: list[float] | None = None):
        """col_widths: optionale absolute Spaltenbreiten in Punkten (Summe = PAGE_W - 2*MARGIN)."""
        self._blocks.append({"type": "table", "headers": headers, "rows": rows,
                              "col_widths": col_widths})

    def add_separator(self):
        self._blocks.append({"type": "separator"})

    def add_page_break(self):
        self._blocks.append({"type": "page_break"})

    def add_conditional_break(self, min_height: float = 150.0):
        """Seitenumbruch nur wenn weniger als min_height Punkte auf der Seite verbleiben."""
        self._blocks.append({"type": "conditional_break", "min_height": min_height})

    def add_topology_diagram(self, topology) -> None:
        """Zeichnet ein Baumdiagramm der KNX-Topologie (Bereiche → Linien → Geräte)."""
        self._blocks.append({"type": "topology_diagram", "topology": topology})

    def add_link(self, text: str, url: str):
        """Fügt einen klickbaren Hyperlink ein (blau, unterstrichen)."""
        self._blocks.append({"type": "link", "text": text, "url": url})

    # ── Speichern ─────────────────────────────────────────────────────────────

    def save(self, filepath: str):
        if HAS_PYMUPDF:
            self._save_pdf(filepath)
        else:
            self._save_text(filepath)

    # ── Textformat-Fallback ───────────────────────────────────────────────────

    def _save_text(self, filepath: str):
        if not filepath.endswith(".txt"):
            filepath = filepath.rsplit(".", 1)[0] + ".txt"

        contact_parts = [p for p in [self.company_phone, self.company_email] if p]
        lines = [
            "=" * 70,
            f"  {self.title}",
            f"  Firma: {self.company}" + (f", {self.company_address}" if self.company_address else ""),
            *(([f"  Kontakt: {' | '.join(contact_parts)}"] if contact_parts else [])),
            f"  Projekt: {self.project_name}" + (f" (Nr. {self.project_number})" if self.project_number else ""),
            *(([f"  Kunde: {self.client_name}"] if self.client_name else [])),
            *(([f"  Objekt: {self.project_address}"] if self.project_address else [])),
            f"  Datum: {self.project_date}",
            *(([f"  Bearbeiter: {self.user_name}" + (f", {self.user_role}" if self.user_role else "")] if self.user_name else [])),
            "=" * 70,
            "",
        ]

        for block in self._blocks:
            btype = block["type"]
            if btype == "heading":
                prefix = "#" * block["level"]
                lines += [f"{prefix} {block['text']}", ""]
            elif btype == "paragraph":
                lines += [block["text"], ""]
            elif btype == "separator":
                lines += ["-" * 60, ""]
            elif btype == "page_break":
                lines += ["", "=" * 70, ""]
            elif btype == "link":
                lines += [f"  -> {block['text']}  [ {block['url']} ]", ""]
            elif btype == "table":
                hdrs, rows = block["headers"], block["rows"]
                widths = [
                    max(len(str(h)), *(len(str(r[i])) if i < len(r) else 0 for r in rows))
                    for i, h in enumerate(hdrs)
                ]
                row_line = " | ".join(str(h).ljust(w) for h, w in zip(hdrs, widths))
                lines.append(row_line)
                lines.append("-" * len(row_line))
                for row in rows:
                    cells = [
                        str(row[i]).ljust(widths[i]) if i < len(row) else " " * widths[i]
                        for i in range(len(hdrs))
                    ]
                    lines.append(" | ".join(cells))
                lines.append("")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info(f"Bericht gespeichert: {filepath}")

    # ── PDF mit PyMuPDF ───────────────────────────────────────────────────────

    def _save_pdf(self, filepath: str):
        doc = fitz.open()

        # Deckblatt (falls Kundenprofil vorhanden)
        if self._client_profile is not None:
            self._draw_cover_page(doc)

        page, y = self._new_page(doc)
        bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H

        for block in self._blocks:
            btype = block["type"]

            if btype == "page_break":
                page, y = self._new_page(doc)

            elif btype == "separator":
                if y + 10 > bottom:
                    page, y = self._new_page(doc)
                page.draw_line(
                    fitz.Point(self.MARGIN, y),
                    fitz.Point(self.PAGE_W - self.MARGIN, y),
                    color=(0.75, 0.75, 0.75), width=0.5,
                )
                y += 10

            elif btype == "heading":
                level = block["level"]
                text  = block["text"]
                fs_map        = {1: 13, 2: 11, 3: 10, 4: 9}
                space_map     = {1: 10, 2: 18, 3: 14, 4:  8}
                min_after_map = {1: 20, 2: 45, 3: 50, 4: 35}
                fs        = fs_map.get(level, 9)
                space     = space_map.get(level, 4)
                min_after = min_after_map.get(level, 20)
                y += space
                if y + fs + min_after > bottom:
                    page, y = self._new_page(doc)
                self._txt(page, fitz.Point(self.MARGIN, y), text, fs, bold=True)
                y += fs + 5

            elif btype == "paragraph":
                text = block["text"]
                fs   = 9
                avail_w  = self.PAGE_W - 2 * self.MARGIN
                max_chars = max(1, int(avail_w / (fs * 0.52)))
                chunks = [text[i:i + max_chars] for i in range(0, max(len(text), 1), max_chars)]
                for chunk in chunks:
                    if y + fs + 4 > bottom:
                        page, y = self._new_page(doc)
                    self._txt(page, fitz.Point(self.MARGIN, y), chunk, fs)
                    y += fs + 4
                y += 2

            elif btype == "conditional_break":
                bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H
                if bottom - y < block["min_height"]:
                    page, y = self._new_page(doc)

            elif btype == "link":
                text = block["text"]
                url  = block["url"]
                fs   = 9
                if y + fs + 6 > bottom:
                    page, y = self._new_page(doc)
                blue = (0.05, 0.30, 0.70)
                self._txt(page, fitz.Point(self.MARGIN, y), text, fs, color=blue)
                tw = self._tw(text, fs)
                page.draw_line(
                    fitz.Point(self.MARGIN, y + 1.5),
                    fitz.Point(self.MARGIN + tw, y + 1.5),
                    color=blue, width=0.5,
                )
                page.insert_link({
                    "kind": fitz.LINK_URI,
                    "from": fitz.Rect(self.MARGIN, y - fs, self.MARGIN + tw, y + 2),
                    "uri":  url,
                })
                y += fs + 6

            elif btype == "topology_diagram":
                page, y = self._draw_topology_diagram(doc, page, y, block["topology"])

            elif btype == "table":
                page, y = self._draw_table(doc, page, y, block["headers"], block["rows"],
                                           block.get("col_widths"))

        # Footer auf Content-Seiten (nicht auf Deckblatt = Seite 0)
        cover_offset = 1 if self._client_profile is not None else 0
        total = len(doc) - cover_offset
        for i, pg in enumerate(doc):
            if i < cover_offset:
                continue
            self._draw_footer(pg, i + 1 - cover_offset, total)

        doc.save(filepath)
        doc.close()
        logger.info(f"PDF gespeichert: {filepath}")

    def _new_page(self, doc) -> tuple:
        """Neue Seite; registriert Inter-Fonts und zeichnet Header."""
        page = doc.new_page(width=self.PAGE_W, height=self.PAGE_H)
        if _INTER_REGULAR:
            try:
                page.insert_font(fontname="inter", fontfile=_INTER_REGULAR)
            except Exception:
                pass
        if _INTER_BOLD:
            try:
                page.insert_font(fontname="inter-bo", fontfile=_INTER_BOLD)
            except Exception:
                pass
        y = self._draw_header(page)
        return page, y

    # ── Tabellen ──────────────────────────────────────────────────────────────

    def _draw_topology_diagram(self, doc, page, y: float, topology) -> tuple:
        """Zeichnet ein Baumdiagramm der KNX-Topologie."""
        if not HAS_PYMUPDF:
            return page, y

        bottom  = self.PAGE_H - self.MARGIN - self.FOOTER_H
        x0      = float(self.MARGIN)
        fs      = 8.5
        row_h   = 13.0
        indent  = 16.0

        # Farben
        COL_AREA   = (0.08, 0.35, 0.65)   # dunkelblau  – Bereich
        COL_LINE   = (0.15, 0.50, 0.80)   # mittelblau  – Linie
        COL_COUPL  = (0.08, 0.35, 0.65)   # blau        – Koppler/SV
        COL_SENSOR = (0.10, 0.55, 0.20)   # grün        – Sensor
        COL_ACTOR  = (0.55, 0.20, 0.10)   # rot         – Aktor
        COL_OTHER  = (0.40, 0.40, 0.40)   # grau        – other/coupler

        TYPE_COLOR = {
            "sensor":  COL_SENSOR,
            "actor":   COL_ACTOR,
            "coupler": COL_COUPL,
        }

        def _new_if_needed(pg, cy, needed=row_h):
            if cy + needed > bottom:
                pg, cy = self._new_page(doc)
            return pg, cy

        def _draw_row(pg, cy, x_indent, label, color=(0.1, 0.1, 0.1), bold=False):
            pg, cy = _new_if_needed(pg, cy)
            self._txt(pg, fitz.Point(x_indent, cy), label, fs, bold=bold, color=color)
            return pg, cy + row_h

        def _draw_connector(pg, x_line, y_top, y_bot):
            """Senkrechte Verbindungslinie im Baum."""
            pg.draw_line(
                fitz.Point(x_line, y_top),
                fitz.Point(x_line, y_bot),
                color=(0.70, 0.70, 0.70), width=0.5,
            )
            pg.draw_line(
                fitz.Point(x_line, y_bot),
                fitz.Point(x_line + 6, y_bot),
                color=(0.70, 0.70, 0.70), width=0.5,
            )

        # Nur Bereiche mit Inhalt
        areas = [
            a for a in topology.areas
            if any(line.devices for line in a.lines)
        ]

        for area in areas:
            # Bereichszeile
            n_devices = sum(len(line.devices) for line in area.lines)
            area_label = f"Bereich {area.area_number}: {area.name}  ({n_devices} Geräte)"
            page, y = _draw_row(page, y, x0, area_label, color=COL_AREA, bold=True)

            lines_with_devs = [l for l in area.lines if l.devices]
            for li, line in enumerate(lines_with_devs):
                is_last_line = (li == len(lines_with_devs) - 1)
                x1 = x0 + indent

                # Liniensymbol
                n_s = sum(1 for d in line.devices if d.device_type == "sensor")
                n_a = sum(1 for d in line.devices if d.device_type == "actor")
                n_o = len(line.devices) - n_s - n_a
                line_label = (
                    f"Linie {area.area_number}.{line.line_number}: {line.name}"
                    f"  –  {len(line.devices)} Geräte"
                    f"  ({n_s} Sensor{'en' if n_s!=1 else ''}, "
                    f"{n_a} Aktor{'en' if n_a!=1 else ''}"
                    + (f", {n_o} weitere" if n_o else "") + ")"
                )
                y_line_start = y
                page, y = _draw_row(page, y, x1, line_label, color=COL_LINE, bold=True)

                # Geräte sortiert nach Adresse
                try:
                    sorted_devs = sorted(
                        line.devices,
                        key=lambda d: tuple(int(p) for p in d.physical_address.split("."))
                    )
                except Exception:
                    sorted_devs = line.devices

                for di, dev in enumerate(sorted_devs):
                    is_last_dev = (di == len(sorted_devs) - 1)
                    x2 = x1 + indent
                    color = TYPE_COLOR.get(dev.device_type, COL_OTHER)
                    prod = (dev.product or "")[:45]
                    dev_label = f"{dev.physical_address}   {prod}  [{dev.device_type}]"
                    y_before = y
                    page, y = _draw_row(page, y, x2 + 8, dev_label, color=color)
                    _draw_connector(page, x2, y_before - fs, y_before - fs + 1)

                # Lücke zwischen Linien
                y += 2

            # Lücke zwischen Bereichen
            y += 4

        return page, y

    def _wrap_cell(self, text: str, avail_w: float, fs: float) -> list[str]:
        """Bricht Zellentext an Wortgrenzen um; bei Einzelwörtern zeichenweise."""
        text = text.strip()
        if not text:
            return [""]
        if self._tw(text, fs) <= avail_w:
            return [text]
        result: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip() if current else word
            if self._tw(candidate, fs) <= avail_w:
                current = candidate
            else:
                if current:
                    result.append(current)
                if self._tw(word, fs) > avail_w:
                    # Einzelwort zu lang → zeichenweise aufteilen
                    while word:
                        lo, hi = 1, len(word)
                        while lo < hi:
                            mid = (lo + hi + 1) // 2
                            if self._tw(word[:mid], fs) <= avail_w:
                                lo = mid
                            else:
                                hi = mid - 1
                        result.append(word[:lo])
                        word = word[lo:]
                    current = ""
                else:
                    current = word
        if current:
            result.append(current)
        return result or [""]

    def _col_widths(self, headers: list[str], rows: list[list[str]],
                    max_fraction: float = 0.40) -> list[float]:
        """Berechnet Spaltenbreiten; Spalten über max_fraction werden gekappt,
        der gesparte Platz iterativ an die übrigen verteilt."""
        avail = float(self.PAGE_W - 2 * self.MARGIN)
        fs = 8.0
        max_col_w = max_fraction * avail
        n = len(headers)

        nat: list[float] = []
        for i, h in enumerate(headers):
            header_w = self._tw(str(h), fs, bold=True)
            data_w   = max((self._tw(str(row[i]), fs) if i < len(row) else 0.0)
                           for row in rows) if rows else 0.0
            max_px   = max(header_w, data_w) + 2 * self.TBL_COL_PAD
            nat.append(max(max_px, 25.0))

        result = [0.0] * n
        remaining = avail
        unresolved: set[int] = set(range(n))

        for _ in range(n + 1):
            if not unresolved:
                break
            total_nat = sum(nat[i] for i in unresolved) or 1.0
            newly_capped: set[int] = set()
            for i in unresolved:
                prop = remaining * nat[i] / total_nat
                if prop > max_col_w:
                    result[i] = max_col_w
                    remaining -= max_col_w
                    newly_capped.add(i)
            if not newly_capped:
                # Keine weitere Kappung – restlichen Platz verteilen
                for i in unresolved:
                    result[i] = remaining * nat[i] / total_nat
                unresolved = set()
                break
            unresolved -= newly_capped

        # Mindestbreite 25 pt, dann auf avail normieren
        final = [max(w, 25.0) for w in result]
        scale = avail / sum(final)
        return [w * scale for w in final]

    def _draw_table_header_row(self, doc, page, y: float,
                               headers: list[str], col_widths: list[float],
                               fs: float) -> tuple:
        """Zeichnet die Kopfzeile; Header werden bei Bedarf umgebrochen."""
        line_h = fs + 2.5
        wrapped_hdrs = [
            self._wrap_cell(str(h), col_widths[i] - 2 * self.TBL_COL_PAD, fs)
            for i, h in enumerate(headers)
        ]
        max_lines = max(len(w) for w in wrapped_hdrs)
        hdr_h = max(self.TBL_HDR_H, max_lines * line_h + 4)

        bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H
        if y + hdr_h > bottom:
            page, y = self._new_page(doc)
        bg = fitz.Rect(self.MARGIN, y - 1,
                       self.PAGE_W - self.MARGIN, y + hdr_h - 1)
        page.draw_rect(bg, color=None, fill=(0.85, 0.88, 0.92))
        x = float(self.MARGIN)
        for i, lines in enumerate(wrapped_hdrs):
            for li, line_text in enumerate(lines):
                ty = y + fs + 2 + li * line_h
                self._txt(page, fitz.Point(x + self.TBL_COL_PAD, ty),
                          line_text, fs, bold=True, color=(0.1, 0.1, 0.1))
            x += col_widths[i]
        return page, y + hdr_h

    def _draw_table(self, doc, page, y: float,
                    headers: list[str], rows: list[list[str]],
                    col_widths: list[float] | None = None) -> tuple:
        """Zeichnet eine vollständige Tabelle mit Zeilenumbruch statt Abschneiden."""
        if not headers:
            return page, y

        bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H
        n_cols = len(headers)
        if col_widths is None:
            col_widths = self._col_widths(headers, rows)
        fs     = 8.0
        line_h = fs + 2.5  # Zeilenhöhe für umgebrochenen Text

        # Kleine Tabellen zusammenhalten (keep-together)
        total_h = self.TBL_HDR_H + len(rows) * self.TBL_ROW_H + 8
        if total_h <= 220 and y + total_h > bottom:
            page, y = self._new_page(doc)

        # Kopfzeile
        page, y = self._draw_table_header_row(doc, page, y, headers, col_widths, fs)

        # Datenzeilen
        for row_idx, row in enumerate(rows):
            # Zeilenumbruch pro Zelle berechnen
            wrapped = [
                self._wrap_cell(str(row[i]) if i < len(row) else "",
                                col_widths[i] - 2 * self.TBL_COL_PAD, fs)
                for i in range(n_cols)
            ]
            max_lines = max(len(w) for w in wrapped)
            row_h = max(self.TBL_ROW_H, max_lines * line_h + 2)

            if y + row_h > bottom:
                page, y = self._new_page(doc)
                page, y = self._draw_table_header_row(
                    doc, page, y, headers, col_widths, fs)

            # Zebra-Hintergrund
            if row_idx % 2 == 1:
                bg = fitz.Rect(self.MARGIN, y - 1,
                               self.PAGE_W - self.MARGIN, y + row_h - 1)
                page.draw_rect(bg, color=None, fill=(0.96, 0.96, 0.97))

            x = float(self.MARGIN)
            for i in range(n_cols):
                for li, line_text in enumerate(wrapped[i]):
                    ty = y + fs + 2 + li * line_h
                    self._txt(page, fitz.Point(x + self.TBL_COL_PAD, ty), line_text, fs)
                x += col_widths[i]
            y += row_h

        # Untere Abschlusslinie
        page.draw_line(
            fitz.Point(self.MARGIN, y),
            fitz.Point(self.PAGE_W - self.MARGIN, y),
            color=(0.75, 0.75, 0.75), width=0.5,
        )
        y += 8
        return page, y

    # ── Header ────────────────────────────────────────────────────────────────

    def _draw_header(self, page) -> float:
        """
        Kopfbereich (FA-855/857):
        Links: Logo + Firmenname, Adresse, Kontakt
        Rechts: Projektname, Kunde, Objekt, Datum
        """
        margin = self.MARGIN
        y_top  = 20.0
        logo_w = 80.0
        header_bottom = y_top + self.HEADER_H

        # KNX-grüne Trennlinie
        page.draw_line(
            fitz.Point(margin, header_bottom),
            fitz.Point(self.PAGE_W - margin, header_bottom),
            color=(0.37, 0.63, 0.15), width=1.5,
        )

        x_left = margin
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                page.insert_image(
                    fitz.Rect(x_left, y_top, x_left + logo_w, y_top + 50),
                    filename=self.logo_path, keep_proportion=True,
                )
                x_left += logo_w + 10
            except Exception:
                pass

        # Firmeninfos links
        y = y_top + 12
        if self.company:
            self._txt(page, fitz.Point(x_left, y), self.company,
                      11, bold=True, color=(0.15, 0.15, 0.15))
            y += 15
        if self.company_address:
            self._txt(page, fitz.Point(x_left, y), self.company_address,
                      8, color=(0.4, 0.4, 0.4))
            y += 12
        contact = " | ".join(p for p in [self.company_phone, self.company_email] if p)
        if contact:
            self._txt(page, fitz.Point(x_left, y), contact,
                      8, color=(0.4, 0.4, 0.4))

        # Projektinfos rechts (rechtsbündig)
        right_x = self.PAGE_W - margin
        yr = y_top + 12

        proj_label = self.project_name
        if self.project_number:
            proj_label += f"  |  Nr. {self.project_number}"
        if proj_label:
            tw = self._tw(proj_label, 9.5, bold=True)
            self._txt(page, fitz.Point(right_x - tw, yr), proj_label,
                      9.5, bold=True, color=(0.15, 0.15, 0.15))
            yr += 14

        for label, value in [
            ("Kunde",  self.client_name),
            ("Objekt", self.project_address),
            ("Datum",  self.project_date),
        ]:
            if not value:
                continue
            lbl = f"{label}: {value}"
            tw = self._tw(lbl, 8)
            self._txt(page, fitz.Point(right_x - tw, yr), lbl,
                      8, color=(0.4, 0.4, 0.4))
            yr += 12

        return header_bottom + 12

    # ── Footer ────────────────────────────────────────────────────────────────

    def _draw_footer(self, page, page_num: int, total: int):
        """Footer: Bearbeiter links, Seite X/Y rechts."""
        margin = self.MARGIN
        y = self.PAGE_H - self.FOOTER_H + 8

        page.draw_line(
            fitz.Point(margin, y - 6),
            fitz.Point(self.PAGE_W - margin, y - 6),
            color=(0.75, 0.75, 0.75), width=0.5,
        )

        if self.user_name:
            bearbeiter = self.user_name
            if self.user_role:
                bearbeiter += f", {self.user_role}"
            self._txt(page, fitz.Point(margin, y), bearbeiter,
                      7.5, color=(0.5, 0.5, 0.5))

        page_text = f"Seite {page_num} / {total}"
        tw = self._tw(page_text, 7.5)
        self._txt(page, fitz.Point(self.PAGE_W - margin - tw, y),
                  page_text, 7.5, color=(0.5, 0.5, 0.5))

    # ── Deckblatt ─────────────────────────────────────────────────────────────

    def _draw_cover_page(self, doc):
        """
        Erzeugt ein Deckblatt als erste Seite (vor dem Inhaltsverzeichnis).

        Layout:
          Top (0–100):    Firmenbereich  – Logo links, Kontakt rechts
          Band (100–108): KNX-grüne Trennlinie
          Mitte (115–480): Projektfoto (zentriert, max 340 pt Höhe)
          Titelband (490–560): Dunkler Hintergrund + Berichtstitel
          Info (575–780): Kundendaten links / Projektdaten rechts
          Bottom (800–842): Grüner Footer-Streifen
        """
        cp   = self._client_profile   # ClientProfile
        W    = self.PAGE_W
        H    = self.PAGE_H
        M    = self.MARGIN

        # Neue leere Seite (ganz vorne – doc hat noch keine Seiten)
        page = doc.new_page(width=W, height=H)
        if _INTER_REGULAR:
            try:
                page.insert_font(fontname="inter", fontfile=_INTER_REGULAR)
            except Exception:
                pass
        if _INTER_BOLD:
            try:
                page.insert_font(fontname="inter-bo", fontfile=_INTER_BOLD)
            except Exception:
                pass

        # ── Firmenbereich (oben) ─────────────────────────────────────────────
        x_left = M
        y_co   = 25.0
        logo_w = 90.0

        if self.logo_path and os.path.exists(self.logo_path):
            try:
                page.insert_image(
                    fitz.Rect(x_left, y_co, x_left + logo_w, y_co + 55),
                    filename=self.logo_path, keep_proportion=True,
                )
                x_left += logo_w + 12
            except Exception:
                pass

        y = y_co + 10
        if self.company:
            self._txt(page, fitz.Point(x_left, y), self.company,
                      12, bold=True, color=(0.12, 0.12, 0.12))
            y += 16
        if self.company_address:
            self._txt(page, fitz.Point(x_left, y), self.company_address,
                      8.5, color=(0.4, 0.4, 0.4))
            y += 12
        contact = " | ".join(p for p in [self.company_phone, self.company_email] if p)
        if contact:
            self._txt(page, fitz.Point(x_left, y), contact,
                      8.5, color=(0.4, 0.4, 0.4))

        # Datum oben rechts
        date_lbl = self.project_date
        tw = self._tw(date_lbl, 8.5)
        self._txt(page, fitz.Point(W - M - tw, y_co + 10), date_lbl,
                  8.5, color=(0.4, 0.4, 0.4))

        # KNX-grüne Trennlinie
        line_y = 100.0
        page.draw_line(fitz.Point(M, line_y), fitz.Point(W - M, line_y),
                       color=(0.37, 0.63, 0.15), width=2.0)

        # ── Projektfoto (Mitte) ──────────────────────────────────────────────
        photo_top    = 115.0
        photo_max_h  = 335.0
        photo_bottom = photo_top + photo_max_h

        photo_drawn = False
        if cp and cp.photo_path and os.path.exists(cp.photo_path):
            try:
                photo_w = W - 2 * M
                # Qt dreht im Uhrzeigersinn, PyMuPDF gegen den Uhrzeigersinn
                # → Vorzeichen umkehren: (360 - angle) % 360
                qt_rotation = getattr(cp, "photo_rotation", 0) or 0
                pdf_rotation = (360 - qt_rotation) % 360
                page.insert_image(
                    fitz.Rect(M, photo_top, M + photo_w, photo_bottom),
                    filename=cp.photo_path,
                    rotate=pdf_rotation,
                )
                photo_drawn = True
            except Exception:
                pass

        if not photo_drawn:
            # Dekoratives Farbfeld als Platzhalter
            page.draw_rect(
                fitz.Rect(M, photo_top, W - M, photo_bottom),
                color=None, fill=(0.93, 0.95, 0.97),
            )
            # Subtile diagonale Musterlinien
            for i in range(0, int(photo_max_h) + int(W - 2 * M), 30):
                x1 = M + i
                y1 = photo_top
                x2 = M
                y2 = photo_top + i
                if x1 > W - M:
                    diff = x1 - (W - M)
                    x1   = W - M
                    y1   = photo_top + diff
                if y2 > photo_bottom:
                    diff = y2 - photo_bottom
                    y2   = photo_bottom
                    x2   = M + diff
                page.draw_line(fitz.Point(x1, y1), fitz.Point(x2, y2),
                               color=(0.85, 0.88, 0.92), width=0.5)
            # Projektname als Wasserzeichen
            hint = self.project_name or self.title
            if hint:
                tw = self._tw(hint, 18, bold=True)
                self._txt(
                    page,
                    fitz.Point((W - tw) / 2, photo_top + photo_max_h / 2 + 6),
                    hint, 18, bold=True, color=(0.78, 0.82, 0.87),
                )

        # ── Titelband ────────────────────────────────────────────────────────
        band_top    = photo_bottom + 12
        band_bottom = band_top + 62
        page.draw_rect(fitz.Rect(0, band_top, W, band_bottom),
                       color=None, fill=(0.14, 0.20, 0.35))

        title_text = self.title or "Bericht"
        tw = self._tw(title_text, 20, bold=True)
        self._txt(page,
                  fitz.Point((W - tw) / 2, band_top + 40),
                  title_text, 20, bold=True, color=(1.0, 1.0, 1.0))

        proj_sub = self.project_name
        if self.project_number:
            proj_sub += f"  ·  Nr. {self.project_number}"
        if proj_sub:
            tw2 = self._tw(proj_sub, 9)
            self._txt(page,
                      fitz.Point((W - tw2) / 2, band_top + 54),
                      proj_sub, 9, color=(0.75, 0.82, 0.92))

        # ── Infospalten (Kunde links / Projekt rechts) ───────────────────────
        info_top  = band_bottom + 18
        col_left  = M
        col_right = W / 2 + 10

        def _info_label(px, py, lbl, val, fs_l=7.5, fs_v=9.0):
            if not val:
                return py
            self._txt(page, fitz.Point(px, py), lbl,
                      fs_l, color=(0.5, 0.5, 0.5))
            self._txt(page, fitz.Point(px, py + fs_l + 2), val,
                      fs_v, bold=True, color=(0.12, 0.12, 0.12))
            return py + fs_l + fs_v + 6

        # Linke Spalte – Kundendaten
        y_l = info_top
        if cp:
            self._txt(page, fitz.Point(col_left, y_l), "AUFTRAGGEBER",
                      7, bold=True, color=(0.37, 0.63, 0.15))
            y_l += 12
            page.draw_line(fitz.Point(col_left, y_l),
                           fitz.Point(col_left + (W / 2 - M - 15), y_l),
                           color=(0.37, 0.63, 0.15), width=0.8)
            y_l += 8
            y_l = _info_label(col_left, y_l, "Name", cp.name)
            y_l = _info_label(col_left, y_l, "Objekt / Bauvorhaben", cp.object_address)
            y_l = _info_label(col_left, y_l, "Postadresse", cp.contact_address)
            y_l = _info_label(col_left, y_l, "Telefon", cp.phone)
            y_l = _info_label(col_left, y_l, "E-Mail", cp.email)

        # Rechte Spalte – Projektdaten
        y_r = info_top
        self._txt(page, fitz.Point(col_right, y_r), "PROJEKTDATEN",
                  7, bold=True, color=(0.37, 0.63, 0.15))
        y_r += 12
        page.draw_line(fitz.Point(col_right, y_r),
                       fitz.Point(W - M, y_r),
                       color=(0.37, 0.63, 0.15), width=0.8)
        y_r += 8
        y_r = _info_label(col_right, y_r, "Projektname", self.project_name)
        y_r = _info_label(col_right, y_r, "Projektnummer", self.project_number)
        y_r = _info_label(col_right, y_r, "Datum", self.project_date)
        if self.user_name:
            user_val = self.user_name + (f", {self.user_role}" if self.user_role else "")
            y_r = _info_label(col_right, y_r, "Bearbeiter", user_val)

        # ── Grüner Footer-Streifen ───────────────────────────────────────────
        footer_top = H - 30
        page.draw_rect(fitz.Rect(0, footer_top, W, H),
                       color=None, fill=(0.37, 0.63, 0.15))
        conf_text = "KNiX Arranger  ·  Vertraulich / Konfidentiell"
        tw = self._tw(conf_text, 8)
        self._txt(page, fitz.Point((W - tw) / 2, footer_top + 18),
                  conf_text, 8, color=(1.0, 1.0, 1.0))
