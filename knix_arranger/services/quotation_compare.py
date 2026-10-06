"""
Sammelanfrage, Preisvergleich und Zuschlag der Offertanfragen
(FA-1615, FA-1621 bis FA-1625).
"""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from datetime import date
import uuid

from ..models.quotation import QuotationItem, QuotationRequest

# Status, deren Offerte im Preisvergleich zählt (Preise eingetragen)
STATUS_REJECTED = "Abgelehnt"
STATUS_AWARDED = "Zugeschlagen"


def next_request_number(project) -> str:
    """Nächste freie Anfrage-Nummer OA-<Jahr>-<laufend>."""
    used = {qr.request_number for qr in project.quotation_requests}
    n = len(project.quotation_requests) + 1
    while True:
        number = f"OA-{date.today().year}-{n:03d}"
        if number not in used:
            return number
        n += 1


def send_to_more_suppliers(project, qr: QuotationRequest,
                           supplier_ids: list[str]) -> list[QuotationRequest]:
    """Sammelanfrage (FA-1615): dieselben Positionen zusätzlich bei weiteren
    Lieferanten anfragen. Die Kopien sind ohne Preise und gehören zur selben
    Gruppe wie die Vorlage, damit der Preisvergleich sie zusammenführt."""
    if not qr.group_id:
        qr.group_id = str(uuid.uuid4())
    created = []
    for supplier_id in supplier_ids:
        if supplier_id == qr.supplier_id or any(
                r.group_id == qr.group_id and r.supplier_id == supplier_id
                for r in project.quotation_requests):
            continue
        new = QuotationRequest(
            request_number=next_request_number(project),
            date_created=date.today().isoformat(),
            supplier_id=supplier_id,
            delivery_date_requested=qr.delivery_date_requested,
            group_id=qr.group_id,
        )
        for item in qr.items:
            copy_item = copy.deepcopy(item)
            copy_item.unit_price = copy_item.total_price = 0.0
            copy_item.discount_percent = 0.0
            copy_item.delivery_time = ""
            copy_item.notes = ""
            new.items.append(copy_item)
        project.quotation_requests.append(new)
        created.append(new)
    return created


def comparison_set(project, qr: QuotationRequest) -> list[QuotationRequest]:
    """Anfragen für den Preisvergleich: die Sammelanfrage der gewählten
    Anfrage, sonst alle Anfragen mit mindestens einem Preis."""
    if qr.group_id:
        group = [r for r in project.quotation_requests if r.group_id == qr.group_id]
        if len(group) > 1:
            return group
    return [r for r in project.quotation_requests
            if any(item.unit_price for item in r.items)]


def _item_key(item: QuotationItem) -> tuple[str, str]:
    """Positionen verschiedener Anfragen über Hersteller + Bestellnummer
    zusammenführen, ohne Bestellnummer über die Bezeichnung."""
    if item.order_number:
        return (item.manufacturer.lower(), item.order_number.lower().replace(" ", ""))
    return ("", item.product_name.lower())


@dataclass
class ComparisonRow:
    label: str
    quantity: int
    totals: list[float | None]          # je Lieferant Nettobetrag der Position
    delivery: list[str]                 # je Lieferant Lieferfrist
    cheapest: int | None = None         # Index des günstigsten Lieferanten


@dataclass
class Comparison:
    requests: list[QuotationRequest]
    suppliers: list[str]
    rows: list[ComparisonRow] = field(default_factory=list)
    totals: list[float] = field(default_factory=list)       # Summe je Lieferant
    missing: list[int] = field(default_factory=list)        # Positionen ohne Preis
    cheapest_total: int | None = None    # günstigster unter den vollständigen


def build_comparison(project, requests: list[QuotationRequest]) -> Comparison:
    """Preisvergleich (FA-1623): je Position die Nettobeträge aller Lieferanten,
    günstigster je Position und gesamt. "Gesamt günstigster" nur unter den
    Lieferanten, die alle Positionen angeboten haben."""
    names = {s.id: s.company_name for s in project.suppliers}
    suppliers = [f"{names.get(r.supplier_id, 'ohne Lieferant')} ({r.request_number})"
                 for r in requests]
    comparison = Comparison(requests=requests, suppliers=suppliers)

    order: list[tuple] = []
    labels: dict[tuple, tuple[str, int]] = {}
    by_request: list[dict[tuple, QuotationItem]] = []
    for r in requests:
        items = {}
        for item in r.items:
            key = _item_key(item)
            items[key] = item
            if key not in labels:
                order.append(key)
                label = " ".join(p for p in (item.manufacturer, item.order_number,
                                             item.product_name) if p)
                labels[key] = (label, item.quantity)
        by_request.append(items)

    n = len(requests)
    comparison.totals = [0.0] * n
    comparison.missing = [0] * n
    for key in order:
        label, qty = labels[key]
        totals: list[float | None] = []
        delivery: list[str] = []
        for i, items in enumerate(by_request):
            item = items.get(key)
            if item is None or not item.unit_price:
                totals.append(None)
                delivery.append("")
                comparison.missing[i] += 1
                continue
            value = round(item.net_unit_price * item.quantity, 2)
            totals.append(value)
            delivery.append(item.delivery_time)
            comparison.totals[i] += value
        offered = [(v, i) for i, v in enumerate(totals) if v is not None]
        cheapest = min(offered)[1] if len(offered) > 1 else None
        comparison.rows.append(ComparisonRow(label, qty, totals, delivery, cheapest))

    complete = [(comparison.totals[i], i) for i in range(n)
                if comparison.missing[i] == 0 and comparison.totals[i] > 0]
    comparison.cheapest_total = min(complete)[1] if len(complete) > 1 else None
    return comparison


def chf(value: float | None) -> str:
    """Betrag im Schweizer Format, z.B. 1'234.50."""
    if value is None:
        return "–"
    return f"{value:,.2f}".replace(",", "'")


def write_comparison_pdf(project, comparison: Comparison, company_profile,
                         filepath: str) -> None:
    """Preisvergleich als PDF (FA-1624)."""
    from ..utils.pdf_generator import PdfGenerator

    pdf = PdfGenerator(title="Preisvergleich", company_profile=company_profile,
                       project_name=project.name if project else "",
                       project_info=getattr(project, "project_info", None))
    pdf.add_heading("Preisvergleich Offerten", level=1)
    pdf.add_paragraph(
        "Nettobeträge je Position (Einzelpreis abzüglich Rabatt, mal Menge) in CHF. "
        "Mit * markiert: günstigster Anbieter der Position.")

    n = len(comparison.suppliers)
    headers = ["Position", "Menge"] + comparison.suppliers
    rows = []
    for row in comparison.rows:
        cells = [row.label, str(row.quantity)]
        for i, value in enumerate(row.totals):
            text = chf(value)
            if row.delivery[i]:
                text += f"\n{row.delivery[i]}"
            if row.cheapest == i:
                text = "* " + text
            cells.append(text)
        rows.append(cells)
    total_cells = ["Total", ""]
    for i, total in enumerate(comparison.totals):
        text = chf(total)
        if comparison.missing[i]:
            text += f"\n{comparison.missing[i]} ohne Preis"
        if comparison.cheapest_total == i:
            text = "* " + text
        total_cells.append(text)
    rows.append(total_cells)

    supplier_share = 0.62 / max(n, 1)
    pdf.add_table(headers, rows,
                  col_widths=[0.30, 0.08] + [supplier_share] * n,
                  align=["left", "right"] + ["right"] * n)
    if comparison.cheapest_total is not None:
        pdf.add_note("Günstigster Anbieter gesamt:",
                     f"{comparison.suppliers[comparison.cheapest_total]} – "
                     f"CHF {chf(comparison.totals[comparison.cheapest_total])}")
    else:
        pdf.add_note("Hinweis:", "Kein Anbieter hat alle Positionen angeboten, oder es "
                                 "liegt nur eine vollständige Offerte vor.")
    pdf.save(filepath)


def award(project, qr: QuotationRequest) -> tuple[int, int]:
    """Zuschlag (FA-1625): Status "Zugeschlagen", Nettopreise in die
    Materialliste; die übrigen Anfragen derselben Sammelanfrage werden
    "Abgelehnt". Gibt (übernommene Preise, abgelehnte Anfragen) zurück."""
    qr.status = STATUS_AWARDED
    updated = 0
    for item in qr.items:
        if not item.order_number or not item.unit_price:
            continue
        for entry in project.material_list.entries:
            if (entry.order_number == item.order_number
                    and entry.manufacturer == item.manufacturer):
                entry.unit_price = round(item.net_unit_price, 2)
                updated += 1
    rejected = 0
    if qr.group_id:
        for other in project.quotation_requests:
            if other is not qr and other.group_id == qr.group_id \
                    and other.status != STATUS_REJECTED:
                other.status = STATUS_REJECTED
                rejected += 1
    return updated, rejected
