"""
Sammelanfrage, Offerten erfassen, Preisvergleich und Zuschlag
(FA-1615, FA-1621 bis FA-1625).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import pytest

from knix_arranger.models.material_list import MaterialEntry
from knix_arranger.models.project import KnxProject
from knix_arranger.models.quotation import QuotationItem, QuotationRequest, Supplier
from knix_arranger.services.quotation_compare import (
    award, build_comparison, chf, comparison_set, send_to_more_suppliers,
    write_comparison_pdf,
)


def _project():
    project = KnxProject(name="Chalet")
    a, b, c = (Supplier(company_name=n) for n in ("Elektro AG", "Grosshandel GmbH", "Fachhandel"))
    project.suppliers = [a, b, c]
    qr = QuotationRequest(request_number="OA-2026-001", supplier_id=a.id, items=[
        QuotationItem(position=1, manufacturer="MDT", order_number="AKS-0816.03",
                      product_name="Schaltaktor", quantity=2),
        QuotationItem(position=2, manufacturer="MDT", order_number="BE-TA55P6.01",
                      product_name="Taster", quantity=10),
    ])
    project.quotation_requests = [qr]
    project.material_list.entries = [
        MaterialEntry(manufacturer="MDT", order_number="AKS-0816.03", quantity=2),
        MaterialEntry(manufacturer="MDT", order_number="BE-TA55P6.01", quantity=10),
    ]
    return project, qr, (a, b, c)


def _offer(qr, prices, discount=0.0, delivery=""):
    for item, price in zip(qr.items, prices):
        if price is not None:
            item.unit_price = price
            item.discount_percent = discount
            item.delivery_time = delivery
            item.update_total()


def test_item_net_price():
    item = QuotationItem(quantity=4, unit_price=100.0, discount_percent=15)
    item.update_total()
    assert item.net_unit_price == 85.0 and item.total_price == 340.0
    restored = QuotationItem.from_dict(item.to_dict())
    assert (restored.discount_percent, restored.delivery_time) == (15, "")


def test_send_to_more_suppliers():
    project, qr, (a, b, c) = _project()
    _offer(qr, [300.0, 80.0], discount=10, delivery="2 Wochen")
    created = send_to_more_suppliers(project, qr, [b.id, c.id, a.id])
    assert [r.supplier_id for r in created] == [b.id, c.id]      # nicht an sich selbst
    assert {r.group_id for r in project.quotation_requests} == {qr.group_id}
    assert [r.request_number for r in created] == ["OA-2026-002", "OA-2026-003"]
    copy_item = created[0].items[0]
    assert (copy_item.order_number, copy_item.quantity) == ("AKS-0816.03", 2)
    assert (copy_item.unit_price, copy_item.discount_percent, copy_item.delivery_time) == (0, 0, "")
    # erneut an dieselben Lieferanten: keine Doppel
    assert send_to_more_suppliers(project, qr, [b.id]) == []


def test_comparison_highlights_cheapest():
    project, qr, (a, b, c) = _project()
    second, third = send_to_more_suppliers(project, qr, [b.id, c.id])
    _offer(qr, [300.0, 80.0], discount=10)           # 540 + 720 = 1260
    _offer(second, [280.0, 85.0])                     # 560 + 850 = 1410
    _offer(third, [250.0, None])                      # 500, Taster fehlt
    assert comparison_set(project, second) == project.quotation_requests

    comp = build_comparison(project, project.quotation_requests)
    assert comp.suppliers[0] == "Elektro AG (OA-2026-001)"
    aktor, taster = comp.rows
    assert aktor.totals == [540.0, 560.0, 500.0] and aktor.cheapest == 2
    assert taster.totals == [720.0, 850.0, None] and taster.cheapest == 0
    assert comp.totals == [1260.0, 1410.0, 500.0]
    assert comp.missing == [0, 0, 1]
    assert comp.cheapest_total == 0                   # nur unter vollständigen


def test_comparison_pdf(tmp_path):
    project, qr, (a, b, _c) = _project()
    (second,) = send_to_more_suppliers(project, qr, [b.id])
    _offer(qr, [300.0, 80.0], delivery="3 Wochen")
    _offer(second, [280.0, 90.0])
    path = tmp_path / "vergleich.pdf"
    write_comparison_pdf(project, build_comparison(project, [qr, second]), None, str(path))
    with fitz.open(path) as doc:
        text = " ".join("".join(p.get_text() for p in doc).split())
    assert "Preisvergleich" in text and "Grosshandel GmbH" in text
    assert "1'400.00" in text and "3 Wochen" in text
    assert "Günstigster Anbieter gesamt: Elektro AG (OA-2026-001) – CHF 1'400.00" in text


def test_award_uses_net_prices_and_rejects_others():
    project, qr, (a, b, c) = _project()
    second, third = send_to_more_suppliers(project, qr, [b.id, c.id])
    _offer(second, [280.0, 85.0], discount=5)
    updated, rejected = award(project, second)
    assert second.status == "Zugeschlagen"
    assert (updated, rejected) == (2, 2)
    assert {qr.status, third.status} == {"Abgelehnt"}
    prices = [e.unit_price for e in project.material_list.entries]
    assert prices == [266.0, 80.75]


def test_chf():
    assert chf(1234.5) == "1'234.50" and chf(None) == "–"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def test_view_offer_entry_sets_received_and_total(qapp):
    from knix_arranger.ui.views.quotation_view import (
        QuotationView, _COL_DISCOUNT, _COL_PRICE, _COL_TOTAL,
    )
    project, qr, _ = _project()
    view = QuotationView()
    view.set_project(project)
    view._request_table.setCurrentCell(0, 0)
    view._items_table.item(0, _COL_PRICE).setText("300")
    qapp.processEvents()
    view._items_table.item(0, _COL_DISCOUNT).setText("10")
    qapp.processEvents()
    assert qr.items[0].total_price == 540.0
    assert qr.status == "Erhalten"
    assert view._items_table.item(0, _COL_TOTAL).text() == "540.00"
    assert view._request_table.item(0, 3).text() == "Erhalten"
