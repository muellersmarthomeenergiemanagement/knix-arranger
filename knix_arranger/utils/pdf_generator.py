"""
PDF-Erzeugung (NFA-050, FA-855–857)
Erzeugt Berichte mit Firmenprofil-Header (Logo, Firma, Projekt)
und Footer (Bearbeiter, Seite X/Y) auf jeder Seite.
Schrift: Inter (mitgeliefert, siehe utils/fonts.py), sonst Helvetica.
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


from .fonts import (
    INTER_REGULAR as _INTER_REGULAR, INTER_BOLD as _INTER_BOLD,
    register_fonts as _register_fonts, text_length as _text_length,
)

# Akzentfarben für den Abschnittsbalken am linken Rand
ACCENT_DEFAULT = (0.37, 0.63, 0.15)   # KNX-Grün
ACCENT_ERROR   = (0.80, 0.16, 0.16)   # Rot
ACCENT_WARNING = (0.93, 0.55, 0.05)   # Orange
ACCENT_INFO    = (0.16, 0.45, 0.75)   # Blau


class PageRef:
    """Platzhalter in einer Tabellenzelle für die Seitenzahl eines Ankers
    (add_anchor). Wird beim Speichern in einem zweiten Durchlauf ersetzt."""

    def __init__(self, key: str):
        self.key = key


def _cell_text(cell) -> str:
    """Tabellenzelle als einfacher Text (Tupel = Haupttext + Zusatz)."""
    if isinstance(cell, PageRef):
        return ""
    if isinstance(cell, tuple):
        main, sub = cell
        return f"{main} – {sub}" if sub else str(main)
    return str(cell)


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

        # Laufender Abschnitt beim Rendern (Akzentbalken, Fortsetzungstitel)
        self._sec_title = ""
        self._sub_title = ""
        self._accent: tuple | None = None
        self._bar_y0 = 0.0
        self._cur_page: Any = None

    @property
    def content_width(self) -> float:
        """Nutzbare Breite zwischen den Seitenrändern in Punkten."""
        return float(self.PAGE_W - 2 * self.MARGIN)

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
        return _text_length(text, fontsize, bold)

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

    def add_heading(self, text: str, level: int = 1, accent: tuple | None = None):
        """Überschrift. Level 2 beginnt einen Abschnitt mit farbigem Balken am
        linken Rand (accent, Standard KNX-Grün); Level 3 ist ein Unterabschnitt.
        Beide erscheinen als Fortsetzungstitel, wenn eine Tabelle umbricht."""
        self._blocks.append({"type": "heading", "text": text, "level": level,
                             "accent": accent})

    def add_anchor(self, key: str) -> None:
        """Merkt sich die aktuelle Seite unter key (für PageRef in Tabellen)."""
        self._blocks.append({"type": "anchor", "key": key})

    def add_card_header(self, title: str, detail: str = "", bookmark: str = "") -> None:
        """Kopfband einer Gerätekarte: fetter Titel, darunter graue Details.
        bookmark: Eintrag im PDF-Inhaltsverzeichnis (Ebene unter der
        letzten Überschrift)."""
        self._blocks.append({"type": "card_header", "title": title,
                             "detail": detail, "bookmark": bookmark})

    def add_button_plan(self, rows: list[dict]) -> None:
        """Tastenplan eines Tasters, so wie er an der Wand aussieht.

        rows: je Tastenpaar {"number": int, "cells": [(Titel, Detail), ...]}
        mit einer Zelle (ganze Taste) oder zwei Zellen (links, rechts);
        eine leere Zelle ist ("", "")."""
        self._blocks.append({"type": "button_plan", "rows": rows})

    def add_note(self, label: str, text: str):
        """Kurzer Erläuterungstext mit fettem Präfix, z.B. 'Massnahme: …'."""
        self._blocks.append({"type": "note", "label": label, "text": text})

    def add_paragraph(self, text: str):
        self._blocks.append({"type": "paragraph", "text": text})

    def add_table(self, headers: list[str], rows: list[list[str]],
                  col_widths: list[float] | None = None,
                  align: list[str] | None = None):
        """col_widths: optionale Spaltenbreiten – absolut in Punkten
        (Summe = content_width) oder als Anteile (Summe = 1.0).
        align: je Spalte "left" oder "right"."""
        if col_widths and sum(col_widths) <= 1.001:
            col_widths = [f * self.content_width for f in col_widths]
        self._blocks.append({"type": "table", "headers": headers, "rows": rows,
                              "col_widths": col_widths, "align": align})

    def add_separator(self):
        self._blocks.append({"type": "separator"})

    def add_page_break(self):
        self._blocks.append({"type": "page_break"})

    def add_conditional_break(self, min_height: float = 150.0):
        """Seitenumbruch nur wenn weniger als min_height Punkte auf der Seite verbleiben."""
        self._blocks.append({"type": "conditional_break", "min_height": min_height})

    def add_topology_schema(self, areas: list[dict]) -> None:
        """Prinzipschema der Topologie: je Bereich ein Balken, darunter die
        Linien als Kästen mit Koppler, Auslastung und Gerätezahlen.

        areas: [{"title": str, "info": str, "lines": [{"title": str,
        "coupler": str, "count": int, "max": int, "stats": [(Label, Anzahl)]}]}]
        """
        self._blocks.append({"type": "topology_schema", "areas": areas})

    def add_link(self, text: str, url: str):
        """Fügt einen klickbaren Hyperlink ein (blau, unterstrichen)."""
        self._blocks.append({"type": "link", "text": text, "url": url})

    # ── Speichern ─────────────────────────────────────────────────────────────

    def save(self, filepath: str):
        if HAS_PYMUPDF:
            self._anchors: dict[str, int] = {}
            if any(b["type"] == "anchor" for b in self._blocks):
                # Erster Durchlauf nur zum Ermitteln der Seitenzahlen
                self._save_pdf(None)
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
            elif btype == "note":
                lines += [f"{block['label']} {block['text']}", ""]
            elif btype == "card_header":
                lines += [f"== {block['title']}", block["detail"], ""]
            elif btype == "button_plan":
                for row in block["rows"]:
                    cells = " | ".join(" ".join(p for p in c if p) or "–" for c in row["cells"])
                    lines.append(f"  Taste {row['number']}: {cells}")
                lines.append("")
            elif btype == "separator":
                lines += ["-" * 60, ""]
            elif btype == "page_break":
                lines += ["", "=" * 70, ""]
            elif btype == "link":
                lines += [f"  -> {block['text']}  [ {block['url']} ]", ""]
            elif btype == "topology_schema":
                for area in block["areas"]:
                    lines.append(f"[{area['title']}]  {area['info']}")
                    for ln in area["lines"]:
                        stats = ", ".join(f"{k} {v}" for k, v in ln["stats"])
                        lines.append(f"  {ln['title']} ({ln['coupler']}): "
                                     f"{ln['count']}/{ln['max']} Geräte – {stats}")
                    lines.append("")
            elif btype == "table":
                hdrs = block["headers"]
                rows = [[_cell_text(c) for c in r] for r in block["rows"]]
                widths = [
                    max([len(str(h))] + [len(str(r[i])) if i < len(r) else 0 for r in rows])
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

    def _save_pdf(self, filepath: str | None):
        doc = fitz.open()
        self._sec_title = self._sub_title = ""
        self._accent = None
        self._cur_page = None
        self._toc: list[list] = []
        cover_offset = 1 if self._client_profile is not None else 0

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
                if level <= 2:
                    self._close_section_bar(y)
                    self._accent = None
                y += space
                if y + fs + min_after > bottom:
                    page, y = self._new_page(doc)
                if level <= 2:
                    self._sec_title = text if level == 2 else ""
                    self._sub_title = ""
                    self._accent = (block.get("accent") or ACCENT_DEFAULT) if level == 2 else None
                    self._bar_y0 = y - fs
                elif level == 3:
                    self._sub_title = text
                self._txt(page, fitz.Point(self.MARGIN, y), text, fs, bold=True)
                self._add_bookmark(level, text, len(doc))
                y += fs + 5

            elif btype == "paragraph":
                text = block["text"]
                fs   = 9
                avail_w = self.content_width
                chunks = [
                    line
                    for part in text.split("\n")
                    for line in self._wrap_cell(part, avail_w, fs)
                ]
                for chunk in chunks:
                    if y + fs + 4 > bottom:
                        page, y = self._new_page(doc)
                    self._txt(page, fitz.Point(self.MARGIN, y), chunk, fs)
                    y += fs + 4
                y += 2

            elif btype == "note":
                page, y = self._draw_note(doc, page, y, block["label"], block["text"])

            elif btype == "anchor":
                self._anchors[block["key"]] = len(doc) - cover_offset

            elif btype == "card_header":
                page, y = self._draw_card_header(doc, page, y, block)

            elif btype == "button_plan":
                page, y = self._draw_button_plan(doc, page, y, block["rows"])

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

            elif btype == "topology_schema":
                page, y = self._draw_topology_schema(doc, page, y, block["areas"])

            elif btype == "table":
                page, y = self._draw_table(doc, page, y, block["headers"], block["rows"],
                                           block.get("col_widths"), block.get("align"))

        self._close_section_bar(y)

        # Footer auf Content-Seiten (nicht auf Deckblatt = Seite 0)
        total = len(doc) - cover_offset
        for i, pg in enumerate(doc):
            if i < cover_offset:
                continue
            self._draw_footer(pg, i + 1 - cover_offset, total)

        if filepath is None:
            doc.close()
            return
        if self._toc:
            try:
                doc.set_toc(self._toc)
            except Exception as exc:          # Lesezeichen sind nur Komfort
                logger.debug(f"PDF-Lesezeichen nicht gesetzt: {exc}")
        doc.save(filepath)
        doc.close()
        logger.info(f"PDF gespeichert: {filepath}")

    def _add_bookmark(self, level: int, title: str, page_no: int) -> None:
        """PDF-Lesezeichen; Ebenen dürfen nur um 1 tiefer springen."""
        prev = self._toc[-1][0] if self._toc else 0
        self._toc.append([max(1, min(level, prev + 1)), title, page_no])

    def _new_page(self, doc) -> tuple:
        """Neue Seite; registriert Inter-Fonts und zeichnet Header.
        Ein laufender Abschnittsbalken wird auf der alten Seite bis zum
        Inhaltsende gezogen und auf der neuen Seite fortgesetzt."""
        self._close_section_bar(self.PAGE_H - self.MARGIN - self.FOOTER_H)
        page = doc.new_page(width=self.PAGE_W, height=self.PAGE_H)
        _register_fonts(page)
        y = self._draw_header(page)
        self._cur_page = page
        self._bar_y0 = y - 8
        return page, y

    # ── Abschnitte ────────────────────────────────────────────────────────────

    def _close_section_bar(self, y_end: float) -> None:
        """Zeichnet den Akzentbalken des laufenden Abschnitts auf der
        aktuellen Seite (vom Abschnittsbeginn bzw. Seitenanfang bis y_end)."""
        if self._accent is None or self._cur_page is None or y_end <= self._bar_y0:
            return
        x = self.MARGIN - 12
        self._cur_page.draw_rect(
            fitz.Rect(x, self._bar_y0, x + 3, y_end),
            color=None, fill=self._accent,
        )

    def _draw_continuation_title(self, page, y: float) -> float:
        """Fortsetzungstitel über einer umgebrochenen Tabelle."""
        parts = [p for p in (self._sec_title, self._sub_title) if p]
        if not parts:
            return y
        fs = 8.5
        label = "  –  ".join(parts) + "  (Fortsetzung)"
        label = self._wrap_cell(label, self.content_width, fs)[0]
        color = self._accent or (0.3, 0.3, 0.3)
        self._txt(page, fitz.Point(self.MARGIN, y + fs - 4), label, fs,
                  bold=True, color=color)
        return y + fs + 6

    def _draw_note(self, doc, page, y: float, label: str, text: str) -> tuple:
        """Fettes Präfix, danach umgebrochener Text mit hängendem Einzug."""
        fs = 8.5
        line_h = fs + 3.5
        bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H
        label_w = self._tw(label + " ", fs, bold=True) if label else 0.0
        lines = self._wrap_cell(text, self.content_width - label_w, fs)
        y += 4
        for i, line in enumerate(lines):
            if y + line_h > bottom:
                page, y = self._new_page(doc)
            if i == 0 and label:
                self._txt(page, fitz.Point(self.MARGIN, y), label, fs,
                          bold=True, color=(0.2, 0.2, 0.2))
            self._txt(page, fitz.Point(self.MARGIN + label_w, y), line, fs,
                      color=(0.3, 0.3, 0.3))
            y += line_h
        return page, y + 2

    # ── Tabellen ──────────────────────────────────────────────────────────────

    def _draw_topology_schema(self, doc, page, y: float, areas: list[dict]) -> tuple:
        """Zeichnet das Prinzipschema (siehe add_topology_schema)."""
        bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H
        x0 = float(self.MARGIN)
        gap = 16.0
        box_w = (self.content_width - gap) / 2
        pad = 8.0
        fs = 8.0
        stub = 12.0                     # senkrechte Verbindung Bereich -> Linie
        dark = (0.14, 0.20, 0.35)
        grey = (0.45, 0.45, 0.45)

        def stats_lines(ln):
            text = "  ·  ".join(f"{label} {n}" for label, n in ln["stats"])
            return self._wrap_cell(text, box_w - 2 * pad, fs)

        def box_height(ln):
            return pad + 11 + 11 + 14 + len(stats_lines(ln)) * (fs + 3) + pad - 2

        for area in areas:
            lines = area["lines"]
            first_row_h = max((box_height(ln) for ln in lines[:2]), default=0)
            if y + 20 + stub + first_row_h > bottom:
                page, y = self._new_page(doc)

            # Bereichsbalken
            page.draw_rect(fitz.Rect(x0, y, x0 + self.content_width, y + 18),
                           color=None, fill=dark)
            self._txt(page, fitz.Point(x0 + pad, y + 12.5), area["title"], 9,
                      bold=True, color=(1, 1, 1))
            if area.get("info"):
                tw = self._tw(area["info"], fs)
                self._txt(page, fitz.Point(x0 + self.content_width - pad - tw, y + 12.5),
                          area["info"], fs, color=(0.80, 0.85, 0.92))
            y += 18

            for row_start in range(0, len(lines), 2):
                row = lines[row_start:row_start + 2]
                row_h = max(box_height(ln) for ln in row)
                if y + stub + row_h > bottom:
                    page, y = self._new_page(doc)
                    stub_top = y
                else:
                    stub_top = y
                for col, ln in enumerate(row):
                    bx = x0 + col * (box_w + gap)
                    by = y + stub
                    cx = bx + box_w / 2
                    page.draw_line(fitz.Point(cx, stub_top), fitz.Point(cx, by),
                                   color=(0.6, 0.6, 0.6), width=1.0)
                    page.draw_rect(fitz.Rect(bx, by, bx + box_w, by + row_h),
                                   color=(0.75, 0.75, 0.75), fill=(1, 1, 1), width=0.6)
                    page.draw_rect(fitz.Rect(bx, by, bx + 3, by + row_h),
                                   color=None, fill=ACCENT_DEFAULT)

                    ty = by + pad + 8
                    self._txt(page, fitz.Point(bx + pad, ty),
                              self._wrap_cell(ln["title"], box_w * 0.62, 9.5)[0],
                              9.5, bold=True, color=dark)
                    if ln.get("coupler"):
                        label = f"Koppler {ln['coupler']}"
                        tw = self._tw(label, fs)
                        self._txt(page, fitz.Point(bx + box_w - pad - tw, ty),
                                  label, fs, color=grey)

                    # Auslastung
                    ty += 11
                    count, maximum = ln["count"], max(ln["max"], 1)
                    ratio = count / maximum
                    bar_w = box_w - 2 * pad - 70
                    bar = fitz.Rect(bx + pad, ty, bx + pad + bar_w, ty + 7)
                    page.draw_rect(bar, color=None, fill=(0.90, 0.91, 0.93))
                    color = (ACCENT_ERROR if ratio > 1 else
                             ACCENT_WARNING if ratio >= 0.9 else ACCENT_DEFAULT)
                    page.draw_rect(
                        fitz.Rect(bar.x0, bar.y0, bar.x0 + bar_w * min(ratio, 1.0), bar.y1),
                        color=None, fill=color)
                    label = f"{count} / {ln['max']} Geräte"
                    tw = self._tw(label, fs)
                    self._txt(page, fitz.Point(bx + box_w - pad - tw, ty + 6.5),
                              label, fs, color=grey)

                    ty += 7 + 14
                    for text in stats_lines(ln):
                        self._txt(page, fitz.Point(bx + pad, ty), text, fs)
                        ty += fs + 3
                y += stub + row_h
            y += 14
        return page, y

    def _wrap_lines(self, text: str, avail_w: float, fs: float) -> list[str]:
        """Wie _wrap_cell, behält aber Zeilenumbrüche im Text."""
        return [line for part in text.split("\n")
                for line in self._wrap_cell(part, avail_w, fs)]

    # ── Gerätekarte ───────────────────────────────────────────────────────────

    def _draw_card_header(self, doc, page, y: float, block: dict) -> tuple:
        bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H
        pad = 6.0
        detail_lines = self._wrap_lines(block["detail"], self.content_width - 2 * pad, 8) \
            if block["detail"] else []
        h = pad + 11 + len(detail_lines) * 11 + pad - 2
        y += 6
        if y + h + 60 > bottom:
            page, y = self._new_page(doc)
        page.draw_rect(fitz.Rect(self.MARGIN, y, self.MARGIN + self.content_width, y + h),
                       color=None, fill=(0.92, 0.94, 0.97))
        page.draw_rect(fitz.Rect(self.MARGIN, y, self.MARGIN + 3, y + h),
                       color=None, fill=(0.14, 0.20, 0.35))
        ty = y + pad + 8
        self._txt(page, fitz.Point(self.MARGIN + pad + 3, ty), block["title"], 9.5,
                  bold=True, color=(0.14, 0.20, 0.35))
        for line in detail_lines:
            ty += 11
            self._txt(page, fitz.Point(self.MARGIN + pad + 3, ty), line, 8,
                      color=(0.35, 0.35, 0.35))
        if block.get("bookmark"):
            self._add_bookmark(4, block["bookmark"], len(doc))
        return page, y + h + 8

    def _draw_button_plan(self, doc, page, y: float, rows: list[dict]) -> tuple:
        """Tasten als Raster: je Tastenpaar eine Zeile, links/rechts nebeneinander."""
        if not rows:
            return page, y
        bottom = self.PAGE_H - self.MARGIN - self.FOOTER_H
        cell_w = 118.0
        row_h = 34.0
        width = 2 * cell_w
        x0 = float(self.MARGIN)
        height = len(rows) * row_h
        if y + height + 10 > bottom:
            page, y = self._new_page(doc)
        # Rahmen wie ein Tasterrahmen
        page.draw_rect(fitz.Rect(x0 - 4, y - 4, x0 + width + 4, y + height + 4),
                       color=(0.70, 0.70, 0.70), fill=(0.97, 0.97, 0.98), width=0.8)
        for r, row in enumerate(rows):
            cells = row["cells"]
            ry = y + r * row_h
            w = width / len(cells)
            for c, (title, detail) in enumerate(cells):
                cx = x0 + c * w
                rect = fitz.Rect(cx + 1.5, ry + 1.5, cx + w - 1.5, ry + row_h - 1.5)
                filled = bool(title)
                page.draw_rect(rect, color=(0.75, 0.75, 0.75),
                               fill=(1, 1, 1) if filled else (0.94, 0.94, 0.95), width=0.6)
                self._txt(page, fitz.Point(rect.x0 + 4, rect.y0 + 9),
                          str(row["number"]), 7, bold=True, color=(0.55, 0.55, 0.55))
                if not filled:
                    continue
                tx = rect.x0 + 14
                avail = rect.x1 - tx - 3
                self._txt(page, fitz.Point(tx, rect.y0 + 10),
                          self._wrap_cell(title, avail, 7.5)[0], 7.5, bold=True,
                          color=(0.14, 0.20, 0.35))
                for li, line in enumerate(self._wrap_cell(detail, avail, 7)[:2] if detail else []):
                    self._txt(page, fitz.Point(tx, rect.y0 + 19 + li * 8.5), line, 7,
                              color=(0.40, 0.40, 0.40))
        return page, y + height + 14

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
            data_w   = max((self._tw(_cell_text(row[i]), fs) if i < len(row) else 0.0)
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
                               fs: float, align: list[str] | None = None) -> tuple:
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
            right = bool(align) and i < len(align) and align[i] == "right"
            for li, line_text in enumerate(lines):
                ty = y + fs + 2 + li * line_h
                tx = (x + col_widths[i] - self.TBL_COL_PAD - self._tw(line_text, fs, bold=True)
                      if right else x + self.TBL_COL_PAD)
                self._txt(page, fitz.Point(tx, ty),
                          line_text, fs, bold=True, color=(0.1, 0.1, 0.1))
            x += col_widths[i]
        return page, y + hdr_h

    def _draw_table(self, doc, page, y: float,
                    headers: list[str], rows: list[list[str]],
                    col_widths: list[float] | None = None,
                    align: list[str] | None = None) -> tuple:
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
            y = self._draw_continuation_title(page, y)

        # Kopfzeile
        page, y = self._draw_table_header_row(doc, page, y, headers, col_widths, fs, align)

        # Datenzeilen
        fs_sub = 7.0
        sub_line_h = fs_sub + 2.5
        for row_idx, row in enumerate(rows):
            # Zeilenumbruch pro Zelle berechnen. Eine Zelle als Tupel
            # (Haupttext, Zusatz) erhält den Zusatz als graue zweite Zeile.
            wrapped = []
            for i in range(n_cols):
                cell = row[i] if i < len(row) else ""
                avail = col_widths[i] - 2 * self.TBL_COL_PAD
                if isinstance(cell, PageRef):
                    cell = str(self._anchors.get(cell.key, ""))
                main, sub = cell if isinstance(cell, tuple) else (cell, "")
                parts = [(t, fs, (0, 0, 0)) for t in self._wrap_lines(str(main), avail, fs)]
                if sub:
                    parts += [(t, fs_sub, (0.45, 0.45, 0.45))
                              for t in self._wrap_lines(str(sub), avail, fs_sub)]
                wrapped.append(parts)
            cell_heights = [
                sum(line_h if f == fs else sub_line_h for _t, f, _c in parts)
                for parts in wrapped
            ]
            row_h = max(self.TBL_ROW_H, max(cell_heights) + 2)

            if y + row_h > bottom:
                page, y = self._new_page(doc)
                y = self._draw_continuation_title(page, y)
                page, y = self._draw_table_header_row(
                    doc, page, y, headers, col_widths, fs, align)

            # Zebra-Hintergrund
            if row_idx % 2 == 1:
                bg = fitz.Rect(self.MARGIN, y - 1,
                               self.PAGE_W - self.MARGIN, y + row_h - 1)
                page.draw_rect(bg, color=None, fill=(0.96, 0.96, 0.97))

            x = float(self.MARGIN)
            for i in range(n_cols):
                right = bool(align) and i < len(align) and align[i] == "right"
                ty = y + fs + 2
                for line_text, f, color in wrapped[i]:
                    tx = (x + col_widths[i] - self.TBL_COL_PAD - self._tw(line_text, f)
                          if right else x + self.TBL_COL_PAD)
                    self._txt(page, fitz.Point(tx, ty), line_text, f, color=color)
                    ty += line_h if f == fs else sub_line_h
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
        _register_fonts(page)

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

        # Quellenangabe unterhalb des Fotos (nur wenn Foto + Quelle vorhanden)
        photo_source = getattr(cp, "photo_source", "") if cp else ""
        if photo_drawn and photo_source:
            caption = f"Quelle: {photo_source}"
            tw_cap = self._tw(caption, 6.5)
            self._txt(page, fitz.Point(W - M - tw_cap, photo_bottom + 8.5),
                      caption, 6.5, color=(0.55, 0.55, 0.55))

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
