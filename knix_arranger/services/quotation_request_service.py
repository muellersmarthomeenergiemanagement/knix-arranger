"""
Offertanfrage an einen Lieferanten als PDF und als E-Mail-Entwurf (FA-1612,
FA-1614 a und c).

Die E-Mail entsteht als .eml-Entwurf mit PDF-Anhang und der Kennzeichnung
"X-Unsent: 1": Outlook öffnet ihn als bearbeitbare neue Nachricht, andere
Programme (z.B. Thunderbird) zeigen ihn an und bieten "Als neu bearbeiten".
So braucht es weder Zugangsdaten noch eine Mail-Bibliothek.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate
import os

from ..models.quotation import QuotationRequest, Supplier

# Frist für die Offerte ab Erstelldatum, wenn nichts anderes vereinbart ist
OFFER_DAYS = 14


def _parse_date(text: str) -> datetime | None:
    """Datum aus der Anfrage: gespeichert als ISO (2026-10-06), von Hand
    eventuell als TT.MM.JJJJ."""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime((text or "").strip(), fmt)
        except ValueError:
            continue
    return None


def display_date(text: str) -> str:
    """Datum im Schweizer Format TT.MM.JJJJ; Unlesbares bleibt wie es ist."""
    parsed = _parse_date(text)
    return parsed.strftime("%d.%m.%Y") if parsed else text


def offer_deadline(qr: QuotationRequest) -> str:
    """Gewünschtes Offertdatum: Erstelldatum + 14 Tage (TT.MM.JJJJ)."""
    start = _parse_date(qr.date_created) or datetime.now()
    return (start + timedelta(days=OFFER_DAYS)).strftime("%d.%m.%Y")


def request_filename(qr: QuotationRequest, supplier: Supplier | None, ext: str) -> str:
    name = supplier.company_name if supplier else "Lieferant"
    return (f"Offertanfrage_{qr.request_number}_{name}.{ext}"
            .replace(" ", "_").replace("/", "-"))


def write_request_pdf(project, qr: QuotationRequest, supplier: Supplier | None,
                      company_profile, filepath: str) -> None:
    """Offertanfrage als PDF im einheitlichen Berichtslayout (FA-1612)."""
    from ..utils.pdf_generator import PdfGenerator

    pdf = PdfGenerator(title=f"Offertanfrage {qr.request_number}",
                       company_profile=company_profile,
                       project_name=project.name if project else "",
                       project_info=getattr(project, "project_info", None))
    pdf.add_heading(f"Offertanfrage {qr.request_number}", level=1)

    # Adressfeld Lieferant
    if supplier:
        lines = [supplier.company_name,
                 f"z.H. {supplier.contact_person}" if supplier.contact_person else "",
                 supplier.address, supplier.email,
                 f"Kundennummer: {supplier.customer_number}" if supplier.customer_number else ""]
        pdf.add_paragraph("\n".join(line for line in lines if line))
    pdf.add_separator()

    # Projektangaben
    client = getattr(project, "client_profile", None)
    rows = [
        ["Datum", display_date(qr.date_created) or datetime.now().strftime("%d.%m.%Y")],
        ["Projekt", project.name if project else ""],
        ["Projektnummer", (project.project_number if project else "") or "–"],
        ["Objekt / Standort", (client.object_address if client else "") or "–"],
        ["Gewünschter Liefertermin",
         display_date(qr.delivery_date_requested) or "nach Absprache"],
    ]
    pdf.add_table(["Angabe", ""], rows, col_widths=[0.32, 0.68])

    pdf.add_paragraph(
        "Wir bitten Sie um ein Angebot für die folgenden Positionen. Bitte geben "
        "Sie je Position Einzelpreis, allfällige Rabatte und die Lieferfrist an.")

    # Positionsliste
    pos_rows = [[str(item.position or i), item.manufacturer, item.order_number,
                 item.product_name, str(item.quantity), item.unit, item.notes]
                for i, item in enumerate(qr.items, 1)]
    pdf.add_table(
        ["Pos.", "Hersteller", "Bestellnr.", "Bezeichnung", "Menge", "Einheit", "Bemerkung"],
        pos_rows or [["", "", "", "Keine Positionen", "", "", ""]],
        col_widths=[0.06, 0.14, 0.15, 0.31, 0.08, 0.08, 0.18],
        align=["right", "left", "left", "left", "right", "left", "left"],
    )

    # Fussbereich
    pdf.add_heading("Konditionen", level=3)
    pdf.add_paragraph("\n".join((
        f"Offerte erbeten bis: {offer_deadline(qr)}",
        "Lieferung: an die Projektadresse oder nach Absprache, "
        "Lieferfrist bitte je Position angeben.",
    )))
    c = company_profile
    if c and (c.company_name or c.user_name):
        pdf.add_heading("Kontakt", level=3)
        person = ", ".join(p for p in (c.user_name, c.role) if p)
        lines = [c.company_name, person, c.address,
                 " | ".join(p for p in (c.phone, c.email) if p)]
        pdf.add_paragraph("\n".join(line for line in lines if line))
    pdf.add_table(["", "Besteller"],
                  [["Ort, Datum", ""], ["Unterschrift", " \n \n "]],
                  col_widths=[0.25, 0.75])
    pdf.save(filepath)


def build_request_email(project, qr: QuotationRequest, supplier: Supplier | None,
                        company_profile, pdf_path: str) -> EmailMessage:
    """E-Mail-Entwurf mit der Offertanfrage als PDF-Anhang (FA-1614 c)."""
    msg = EmailMessage()
    msg["X-Unsent"] = "1"      # Outlook: als neue, bearbeitbare Nachricht öffnen
    msg["Date"] = formatdate(localtime=True)
    if supplier and supplier.email:
        msg["To"] = supplier.email
    if company_profile and company_profile.email:
        msg["From"] = company_profile.email
    project_name = project.name if project else ""
    msg["Subject"] = " – ".join(p for p in (
        f"Offertanfrage {qr.request_number}", project_name) if p)

    greeting = (f"Guten Tag {supplier.contact_person}" if supplier and supplier.contact_person
                else "Sehr geehrte Damen und Herren")
    signature = "\n".join(p for p in (
        (company_profile.user_name if company_profile else ""),
        (company_profile.company_name if company_profile else ""),
        (company_profile.phone if company_profile else ""),
    ) if p)
    msg.set_content(
        f"{greeting}\n\n"
        f"Für das Projekt «{project_name}» bitten wir Sie um ein Angebot gemäss "
        f"beiliegender Offertanfrage {qr.request_number} "
        f"({len(qr.items)} Position{'en' if len(qr.items) != 1 else ''}).\n"
        f"Bitte senden Sie uns Ihre Offerte bis {offer_deadline(qr)}, mit "
        "Einzelpreisen, allfälligen Rabatten und Lieferfristen.\n\n"
        "Freundliche Grüsse\n" + signature + "\n")

    with open(pdf_path, "rb") as fh:
        msg.add_attachment(fh.read(), maintype="application", subtype="pdf",
                           filename=os.path.basename(pdf_path))
    return msg


def write_request_email(project, qr: QuotationRequest, supplier: Supplier | None,
                        company_profile, folder: str) -> str:
    """Erzeugt PDF und E-Mail-Entwurf (.eml) im Ordner; gibt den .eml-Pfad zurück."""
    os.makedirs(folder, exist_ok=True)
    pdf_path = os.path.join(folder, request_filename(qr, supplier, "pdf"))
    write_request_pdf(project, qr, supplier, company_profile, pdf_path)
    eml_path = os.path.join(folder, request_filename(qr, supplier, "eml"))
    msg = build_request_email(project, qr, supplier, company_profile, pdf_path)
    with open(eml_path, "wb") as fh:
        fh.write(bytes(msg))
    return eml_path
