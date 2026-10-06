"""
Offert-Brief der Kundenofferte als A4-PDF (FA-1711, FA-1713).

Aus CustomerQuoteView herausgelöst, damit auch das Revisionspaket die
akzeptierte Offerte beilegen kann (FA-2102 Nr. 13).
"""
from __future__ import annotations

from ..models.quotation import round_rappen


def write_quote_letter_pdf(project, cq, project_name: str, filepath: str) -> None:
    """Erzeugt einen professionellen Offert-Brief als A4-PDF via PyMuPDF."""
    import fitz  # PyMuPDF

    # ── Firmendaten ermitteln ──
    company_name = ""
    company_address = ""
    company_phone = ""
    company_email = ""
    user_name = ""
    if project and hasattr(project, "project_info"):
        pi = project.project_info
        company_name = getattr(pi, "company_name", "")
    try:
        from .project_service import ProjectService
        profile = ProjectService().load_company_profile()
        if not company_name:
            company_name = profile.company_name
        company_address = profile.address
        company_phone = profile.phone
        company_email = profile.email
        user_name = profile.user_name
    except Exception:
        pass

    # ── Seite anlegen (A4) ──
    from ..utils.fonts import register_fonts, font_name, text_length, finalize_pdf
    doc = fitz.open()

    def add_page():
        pg = doc.new_page(width=595, height=842)
        register_fonts(pg)
        return pg

    page = add_page()

    LM = 70       # left margin
    RM = 525      # right margin (595 - 70)
    y = 60        # aktueller y-Cursor
    LINE = 14     # Zeilenhöhe normal
    GRAY_HEADER = (0.22, 0.40, 0.60)   # Blau für Tabellenköpfe (RGB 0..1)
    WHITE = (1.0, 1.0, 1.0)
    BLACK = (0.0, 0.0, 0.0)
    LIGHT_GRAY = (0.93, 0.93, 0.93)

    def text(px, py, txt, size=10, bold=False, color=BLACK, align="left"):
        page.insert_text(
            fitz.Point(px, py), txt,
            fontname=font_name(bold), fontsize=size, color=color,
        )

    def hline(py, x0=LM, x1=RM, width=0.5, color=(0.7, 0.7, 0.7)):
        page.draw_line(
            fitz.Point(x0, py), fitz.Point(x1, py),
            color=color, width=width,
        )

    def filled_rect(x0, y0, x1, y1, fill):
        page.draw_rect(
            fitz.Rect(x0, y0, x1, y1),
            color=None, fill=fill,
        )

    def new_page_if_needed(cur_y, needed=60):
        nonlocal page
        if cur_y + needed > 790:
            page = add_page()
            return 60
        return cur_y

    # ── Absender-Block (oben links) ──
    text(LM, y, company_name or "KNX-Systemintegrator", size=13, bold=True)
    y += 16
    if company_address:
        for line in company_address.splitlines():
            text(LM, y, line, size=9)
            y += 12
    contact_parts = []
    if company_phone:
        contact_parts.append(f"Tel. {company_phone}")
    if company_email:
        contact_parts.append(company_email)
    if contact_parts:
        text(LM, y, "  |  ".join(contact_parts), size=9)
        y += 12

    # Trennlinie nach Absender
    hline(y + 4, width=1.0, color=(0.22, 0.40, 0.60))
    y += 14

    # ── Datum (rechts) & Empfänger (links) ──
    recipient_y = y
    from datetime import date as _date
    months = [
        "", "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ]
    today = _date.today()
    date_str = f"{today.day}. {months[today.month]} {today.year}"
    text(RM - 120, recipient_y, date_str, size=10)

    text(LM, recipient_y, cq.customer_name or "Bauherr", size=10, bold=True)
    recipient_y += LINE
    for addr_line in (cq.customer_address or "").splitlines():
        text(LM, recipient_y, addr_line, size=10)
        recipient_y += LINE

    y = max(recipient_y, y) + 20

    # ── Betreff ──
    subject = (
        f"Offerte Nr. {cq.quote_number} Rev. {cq.revision}"
        f" \u2013 KNX-Gebäudeautomation {project_name}"
    )
    text(LM, y, subject, size=11, bold=True)
    y += 20
    client = getattr(project, "client_profile", None) if project else None
    if client and client.object_address:
        # Objektadresse aus dem Kundenprofil als zweite Betreffzeile
        y -= 4
        text(LM, y, f"Objekt: {client.object_address}", size=10)
        y += 20

    # ── Anrede & Einleitung ──
    text(LM, y, f"{cq.salutation or 'Sehr geehrte Damen und Herren'},", size=10)
    y += LINE + 4
    intro = (
        "gerne unterbreiten wir Ihnen folgende Offerte für die "
        "KNX-Gebäudeautomation des oben genannten Projekts."
    )
    text(LM, y, intro, size=10)
    y += LINE + 12

    # ── Hilfsfunktion: Tabelle zeichnen ──
    def draw_table(cur_y, headers, rows, col_widths, fontsize=9,
                   align=None, bold_labels=None):
        """Zeichnet eine Tabelle und gibt das neue y zurück.

        Wiederholt die Kopfzeile automatisch auf Folgeseiten, kürzt zu
        lange Zelltexte mit "…" statt sie in die Nachbarspalte laufen zu
        lassen, und erlaubt rechtsbündige Spalten (`align`, Liste von
        "left"/"right" je Spalte) sowie fett hervorgehobene Zeilen
        (`bold_labels`, Menge von Werten der ersten Spalte).
        """
        nonlocal page
        row_h = fontsize + 5
        total_w = sum(col_widths)
        xs = [LM]
        for w in col_widths[:-1]:
            xs.append(xs[-1] + w)
        xs.append(LM + total_w)
        aligns = align or ["left"] * len(headers)
        bold_labels = bold_labels or set()

        def fit(cell_str, c_idx, bold):
            max_w = xs[c_idx + 1] - xs[c_idx] - 6
            if text_length(cell_str, fontsize, bold) <= max_w:
                return cell_str
            # "…" (U+2026) fehlt im PyMuPDF-Basis-14-Helvetica und würde
            # als falsches Glyph gerendert -- ASCII-Punkte sind sicher.
            ell = "..."
            lo, hi = 0, len(cell_str)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                cand = cell_str[:mid].rstrip() + ell
                if text_length(cand, fontsize, bold) <= max_w:
                    lo = mid
                else:
                    hi = mid - 1
            return (cell_str[:lo].rstrip() + ell) if lo > 0 else ell

        def cell_x(c_idx, cell_str, bold):
            if aligns[c_idx] == "right":
                w = text_length(cell_str, fontsize, bold)
                return xs[c_idx + 1] - 5 - w
            return xs[c_idx] + 3

        def draw_header(y0):
            filled_rect(LM, y0 - row_h + 3, LM + total_w, y0 + 3, GRAY_HEADER)
            for i, hdr in enumerate(headers):
                text(cell_x(i, hdr, True), y0, hdr, size=fontsize, bold=True, color=WHITE)
            y1 = y0 + row_h
            hline(y1 - row_h + 3, LM, LM + total_w, width=0.8, color=(0.0, 0.0, 0.0))
            return y1

        cur_y = draw_header(cur_y)

        for r_idx, row in enumerate(rows):
            if cur_y + row_h + 2 > 790:
                page = add_page()
                cur_y = draw_header(60)
            is_bold_row = bool(row) and str(row[0]) in bold_labels
            if r_idx % 2 == 1:
                filled_rect(LM, cur_y - row_h + 3, LM + total_w, cur_y + 3, LIGHT_GRAY)
            for c_idx, cell in enumerate(row):
                cell_str = fit(str(cell), c_idx, is_bold_row)
                text(cell_x(c_idx, cell_str, is_bold_row), cur_y, cell_str,
                     size=fontsize, bold=is_bold_row)
            cur_y += row_h
        hline(cur_y - row_h + 3, LM, LM + total_w, width=0.5)
        return cur_y + 4

    # ── Einzelpositionen ──
    text(LM, y, "Offert-Positionen", size=10, bold=True)
    y += LINE + 2
    y = new_page_if_needed(y, 40)

    pos_headers = ["Pos.", "Produkt / Leistung", "Menge", "Einh.", "EP (CHF)", "GP (CHF)"]
    col_pos = [30, 220, 35, 30, 55, 55]
    pos_aligns = ["left", "left", "right", "left", "right", "right"]
    pos_rows = []
    for item in cq.items:
        # EP/GP zeigen den Kundenendpreis inkl. Aufschlag (bereits bei
        # Import/Erfassung als item.unit_price/total_price hinterlegt),
        # nicht den Einkaufspreis.
        ep = f"{item.unit_price:,.2f}" if item.unit_price else "-"
        gp = f"{item.total_price:,.2f}" if item.total_price else "-"
        pos_rows.append([str(item.position), item.product_name or "-",
                          str(item.quantity), item.unit or "Stk.", ep, gp])
    if pos_rows:
        y = draw_table(y, pos_headers, pos_rows, col_pos, align=pos_aligns)
    else:
        text(LM, y, "(Keine Positionen erfasst)", size=9,
             color=(0.5, 0.5, 0.5))
        y += LINE
    y += 10

    # ── Kostenzusammenfassung ──
    y = new_page_if_needed(y, 120)
    text(LM, y, "Kostenzusammenfassung", size=10, bold=True)
    y += LINE + 2

    def _chf(val):
        return f"CHF {round_rappen(val):,.2f}"

    cost_rows = [
        ["Material", _chf(cq.material_with_markup)],
    ]
    if cq.labor_mounting_hours:
        cost_rows.append([
            f"Montage ({cq.labor_mounting_hours:.1f} h \u00d7 CHF {cq.hourly_rate_mounting:.2f})",
            _chf(cq.labor_mounting_hours * cq.hourly_rate_mounting),
        ])
    if cq.labor_programming_hours:
        cost_rows.append([
            f"Programmierung ({cq.labor_programming_hours:.1f} h \u00d7 CHF {cq.hourly_rate_programming:.2f})",
            _chf(cq.labor_programming_hours * cq.hourly_rate_programming),
        ])
    if cq.labor_commissioning_hours:
        cost_rows.append([
            f"Inbetriebnahme ({cq.labor_commissioning_hours:.1f} h \u00d7 CHF {cq.hourly_rate_commissioning:.2f})",
            _chf(cq.labor_commissioning_hours * cq.hourly_rate_commissioning),
        ])
    if cq.labor_documentation_hours:
        cost_rows.append([
            f"Dokumentation ({cq.labor_documentation_hours:.1f} h \u00d7 CHF {cq.hourly_rate_documentation:.2f})",
            _chf(cq.labor_documentation_hours * cq.hourly_rate_documentation),
        ])
    if cq.overhead_costs:
        cost_rows.append(["Nebenkosten", _chf(cq.overhead_costs)])
    cost_rows.append(["Zwischensumme", _chf(cq.subtotal)])
    if cq.discount_percent:
        cost_rows.append([
            f"Rabatt ({cq.discount_percent:.1f} %)",
            f"- CHF {round_rappen(cq.discount_amount):,.2f}",
        ])
    cost_rows.append(["Nettobetrag", _chf(cq.net_total)])
    cost_rows.append([f"MwSt. {cq.vat_percent:.1f} %", _chf(cq.vat_amount)])
    # Gesamtbetrag als Sonderzeile – wird separat gezeichnet
    y = draw_table(y, ["Position", "Betrag"], cost_rows, [310, 115],
                   align=["left", "right"],
                   bold_labels={"Zwischensumme", "Nettobetrag"})

    # Gesamtbetrag-Box
    y = new_page_if_needed(y, 30)
    filled_rect(LM, y - 14, RM, y + 6, (0.22, 0.40, 0.60))
    text(LM + 4, y, "GESAMTBETRAG (inkl. MwSt.)", size=10, bold=True, color=WHITE)
    text(RM - 118, y, f"CHF {round_rappen(cq.grand_total):,.2f}", size=10, bold=True, color=WHITE)
    y += 22

    # ── Gültigkeit & Zahlungsbedingungen ──
    y = new_page_if_needed(y, 50)
    from datetime import timedelta
    valid_until = today + timedelta(days=cq.validity_days)
    valid_str = f"{valid_until.day}. {months[valid_until.month]} {valid_until.year}"
    text(LM, y,
         f"Diese Offerte ist gültig bis {valid_str} ({cq.validity_days} Tage).",
         size=9)
    y += LINE
    text(LM, y, f"Zahlungsbedingungen: {cq.payment_terms}.", size=9)
    y += LINE + 16

    # ── Grussformel ──
    y = new_page_if_needed(y, 60)
    text(LM, y, "Für Fragen stehen wir Ihnen gerne zur Verfügung.", size=10)
    y += LINE + 4
    text(LM, y, "Mit freundlichen Grüssen", size=10)
    y += LINE + 20
    text(LM, y, company_name or "KNX-Systemintegrator", size=10, bold=True)
    if user_name:
        y += LINE
        text(LM, y, user_name, size=10)

    # ── Seitenzahlen (nur bei mehrseitigen Briefen) ──
    if doc.page_count > 1:
        for i, pg in enumerate(doc):
            label = f"Seite {i + 1} von {doc.page_count}"
            w = text_length(label, 8)
            pg.insert_text(
                fitz.Point(RM - w, 815), label,
                fontname=font_name(), fontsize=8, color=(0.5, 0.5, 0.5),
            )

    if not filepath.endswith(".pdf"):
        filepath += ".pdf"
    finalize_pdf(doc)
    doc.save(filepath, garbage=3, deflate=True)
    doc.close()
