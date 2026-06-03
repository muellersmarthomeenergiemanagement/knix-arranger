"""
Tests fuer Offert-Datenmodelle (FA-1601, FA-1611, FA-1700).

Abgedeckt: Supplier, QuotationItem, QuotationRequest, CustomerQuote
(Felder, Berechnungen, Serialisierung, Rundungsverhalten).
"""
import sys
import os
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.quotation import (
    Supplier,
    QuotationItem,
    QuotationRequest,
    CustomerQuote,
)


# ---------------------------------------------------------------------------
# Supplier (FA-1601)
# ---------------------------------------------------------------------------

class TestSupplier:
    """Lieferant/Haendler-Datenmodell."""

    def test_default_id_is_uuid(self):
        s = Supplier()
        # Muss ein gueltiges UUID-Format haben
        uuid.UUID(s.id)

    def test_unique_ids(self):
        s1 = Supplier()
        s2 = Supplier()
        assert s1.id != s2.id

    def test_default_empty_fields(self):
        s = Supplier()
        assert s.company_name == ""
        assert s.contact_person == ""
        assert s.email == ""
        assert s.phone == ""
        assert s.address == ""
        assert s.website == ""
        assert s.customer_number == ""
        assert s.category == ""
        assert s.brands == []
        assert s.notes == ""

    def test_constructor_fields(self):
        s = Supplier(
            company_name="Elektro-Material AG",
            contact_person="Hans Muster",
            email="info@em-ag.ch",
            phone="+41 44 987 65 43",
            address="Industriestrasse 10, 8005 Zuerich",
            website="www.em-ag.ch",
            customer_number="KD-2024-1234",
            category="Grosshaendler",
            brands=["ABB", "MDT"],
            notes="Rabattstaffel ab CHF 5000",
        )
        assert s.company_name == "Elektro-Material AG"
        assert s.email == "info@em-ag.ch"
        assert s.brands == ["ABB", "MDT"]

    def test_to_dict_contains_all_keys(self):
        s = Supplier(company_name="Test AG", email="test@test.ch", brands=["ABB"])
        d = s.to_dict()
        for key in ("id", "company_name", "contact_person", "email", "phone",
                    "address", "website", "customer_number", "category", "brands", "notes"):
            assert key in d, f"Schluessel '{key}' fehlt in to_dict()"

    def test_to_dict_values(self):
        s = Supplier(company_name="Test AG", brands=["Jung", "Gira"])
        d = s.to_dict()
        assert d["company_name"] == "Test AG"
        assert d["brands"] == ["Jung", "Gira"]

    def test_from_dict_round_trip(self):
        s = Supplier(
            company_name="Lieferant GmbH",
            email="order@lieferant.de",
            brands=["MDT"],
            category="Fachhandel",
        )
        d = s.to_dict()
        restored = Supplier.from_dict(d)
        assert restored.id == s.id
        assert restored.company_name == s.company_name
        assert restored.email == s.email
        assert restored.brands == s.brands
        assert restored.category == s.category

    def test_from_dict_missing_id_generates_new(self):
        d = {"company_name": "Ohne ID"}
        s = Supplier.from_dict(d)
        assert s.id != ""
        uuid.UUID(s.id)

    def test_brands_list_is_independent(self):
        """Brands-Liste soll nicht geteilt werden."""
        s1 = Supplier(brands=["ABB"])
        s2 = Supplier(brands=["MDT"])
        assert s1.brands != s2.brands


# ---------------------------------------------------------------------------
# QuotationItem
# ---------------------------------------------------------------------------

class TestQuotationItem:
    """Einzelne Position einer Offertanfrage."""

    def test_default_values(self):
        item = QuotationItem()
        assert item.position == 0
        assert item.quantity == 1
        assert item.unit == "Stk."
        assert item.unit_price == 0.0
        assert item.total_price == 0.0
        assert item.notes == ""

    def test_to_dict_contains_all_keys(self):
        item = QuotationItem(position=1, manufacturer="ABB", quantity=3)
        d = item.to_dict()
        for key in ("position", "manufacturer", "order_number", "product_name",
                    "quantity", "unit", "unit_price", "total_price", "notes"):
            assert key in d

    def test_from_dict_round_trip(self):
        item = QuotationItem(
            position=5,
            manufacturer="MDT",
            order_number="AKS-0816.01",
            product_name="AKS-0816 Schaltaktor 8x16A",
            quantity=2,
            unit="Stk.",
            unit_price=189.50,
            total_price=379.00,
            notes="REG-Einbau",
        )
        restored = QuotationItem.from_dict(item.to_dict())
        assert restored.position == 5
        assert restored.manufacturer == "MDT"
        assert restored.quantity == 2
        assert restored.unit_price == 189.50
        assert restored.total_price == 379.00

    def test_from_dict_defaults_for_missing_keys(self):
        item = QuotationItem.from_dict({})
        assert item.quantity == 1
        assert item.unit == "Stk."
        assert item.unit_price == 0.0


# ---------------------------------------------------------------------------
# QuotationRequest (FA-1611)
# ---------------------------------------------------------------------------

class TestQuotationRequest:
    """Offertanfrage an einen Lieferanten."""

    def test_default_status_is_entwurf(self):
        qr = QuotationRequest()
        assert qr.status == "Entwurf"

    def test_default_id_is_uuid(self):
        qr = QuotationRequest()
        uuid.UUID(qr.id)

    def test_unique_ids(self):
        assert QuotationRequest().id != QuotationRequest().id

    def test_to_dict_contains_all_keys(self):
        qr = QuotationRequest()
        d = qr.to_dict()
        for key in ("id", "request_number", "supplier_id", "date_created",
                    "date_sent", "delivery_date_requested", "status", "items"):
            assert key in d

    def test_items_serialized(self):
        qr = QuotationRequest()
        qr.items.append(QuotationItem(position=1, manufacturer="ABB", quantity=4))
        qr.items.append(QuotationItem(position=2, manufacturer="MDT", quantity=2))
        d = qr.to_dict()
        assert len(d["items"]) == 2
        assert d["items"][0]["manufacturer"] == "ABB"

    def test_from_dict_round_trip(self):
        qr = QuotationRequest(
            request_number="OA-2026-001",
            supplier_id="sup-123",
            date_created="2026-03-06",
            status="Versendet",
        )
        qr.items.append(QuotationItem(position=1, quantity=3, manufacturer="Gira"))
        d = qr.to_dict()
        restored = QuotationRequest.from_dict(d)
        assert restored.request_number == "OA-2026-001"
        assert restored.supplier_id == "sup-123"
        assert restored.status == "Versendet"
        assert len(restored.items) == 1
        assert restored.items[0].quantity == 3

    def test_from_dict_empty_items(self):
        qr = QuotationRequest.from_dict({"status": "Erhalten"})
        assert qr.status == "Erhalten"
        assert qr.items == []

    def test_valid_statuses(self):
        """Alle definierten Status-Werte muessen setzbar sein."""
        for status in ("Entwurf", "Versendet", "Erhalten", "Zugeschlagen", "Abgelehnt"):
            qr = QuotationRequest(status=status)
            assert qr.status == status


# ---------------------------------------------------------------------------
# CustomerQuote Berechnungen (FA-1701-1706)
# ---------------------------------------------------------------------------

class TestCustomerQuoteCalculations:
    """Berechnungslogik der Kundenofferte."""

    def _quote(self, **kwargs) -> CustomerQuote:
        defaults = dict(
            material_total=10_000.0,
            material_markup_percent=15.0,
            labor_mounting_hours=40.0,
            hourly_rate_mounting=125.0,
            labor_programming_hours=20.0,
            hourly_rate_programming=145.0,
            labor_commissioning_hours=16.0,
            hourly_rate_commissioning=145.0,
            overhead_costs=500.0,
            discount_percent=10.0,
            vat_percent=8.1,
        )
        defaults.update(kwargs)
        return CustomerQuote(**defaults)

    # material_with_markup

    def test_material_with_markup_zero(self):
        q = self._quote(material_total=0.0, material_markup_percent=15.0)
        assert q.material_with_markup == 0.0

    def test_material_with_markup_15_percent(self):
        q = self._quote(material_total=10_000.0, material_markup_percent=15.0)
        assert q.material_with_markup == pytest.approx(11_500.0)

    def test_material_with_markup_zero_percent(self):
        q = self._quote(material_total=5_000.0, material_markup_percent=0.0)
        assert q.material_with_markup == 5_000.0

    # labor_total

    def test_labor_total_all_three_types(self):
        q = self._quote(
            labor_mounting_hours=40.0, hourly_rate_mounting=125.0,
            labor_programming_hours=20.0, hourly_rate_programming=145.0,
            labor_commissioning_hours=16.0, hourly_rate_commissioning=145.0,
        )
        expected = 40 * 125 + 20 * 145 + 16 * 145
        assert q.labor_total == pytest.approx(expected)

    def test_labor_total_zero_hours(self):
        q = self._quote(
            labor_mounting_hours=0.0, labor_programming_hours=0.0, labor_commissioning_hours=0.0
        )
        assert q.labor_total == 0.0

    # subtotal

    def test_subtotal(self):
        q = self._quote(overhead_costs=500.0)
        expected = q.material_with_markup + q.labor_total + 500.0
        assert q.subtotal == pytest.approx(expected)

    # discount_amount

    def test_discount_amount_zero(self):
        q = self._quote(discount_percent=0.0)
        assert q.discount_amount == 0.0

    def test_discount_amount_10_percent(self):
        q = self._quote(discount_percent=10.0)
        assert q.discount_amount == pytest.approx(q.subtotal * 0.10)

    def test_discount_amount_100_percent(self):
        q = self._quote(discount_percent=100.0)
        assert q.discount_amount == pytest.approx(q.subtotal)

    # net_total

    def test_net_total(self):
        q = self._quote(discount_percent=10.0)
        assert q.net_total == pytest.approx(q.subtotal - q.discount_amount)

    def test_net_total_no_discount(self):
        q = self._quote(discount_percent=0.0)
        assert q.net_total == pytest.approx(q.subtotal)

    # vat_amount

    def test_vat_amount(self):
        q = self._quote(vat_percent=8.1)
        assert q.vat_amount == pytest.approx(q.net_total * 0.081)

    def test_vat_amount_zero_rate(self):
        q = self._quote(vat_percent=0.0)
        assert q.vat_amount == 0.0

    # grand_total

    def test_grand_total(self):
        q = self._quote()
        assert q.grand_total == pytest.approx(q.net_total + q.vat_amount)

    def test_grand_total_zero_vat_and_discount(self):
        q = self._quote(discount_percent=0.0, vat_percent=0.0)
        assert q.grand_total == pytest.approx(q.subtotal)

    # delta_percent (Nachkalkulation)

    def test_delta_percent_no_division_by_zero(self):
        q = CustomerQuote(material_total=0.0, overhead_costs=0.0)
        # net_total == 0: delta_percent darf nicht werfen
        assert q.delta_percent == 0.0

    def test_delta_percent_positive_overrun(self):
        q = self._quote(discount_percent=0.0, vat_percent=0.0)
        q.actual_material_cost = q.material_with_markup + 1000.0
        q.actual_mounting_hours = q.labor_mounting_hours
        q.actual_programming_hours = q.labor_programming_hours
        q.actual_commissioning_hours = q.labor_commissioning_hours
        q.actual_overhead_costs = q.overhead_costs
        # Ist-Kosten > Plan → Ueberschreitung > 0
        assert q.delta_percent > 0.0


# ---------------------------------------------------------------------------
# CustomerQuote Serialisierung (FA-1721)
# ---------------------------------------------------------------------------

class TestCustomerQuoteSerialization:
    """Serialisierung und Deserialisierung der Kundenofferte."""

    def _full_quote(self) -> CustomerQuote:
        q = CustomerQuote(
            quote_number="OF-2026-001",
            revision="B",
            date_created="2026-03-06",
            status="Versendet",
            customer_name="Mustermann AG",
            customer_address="Musterstrasse 1, 8000 Zuerich",
            material_total=15_000.0,
            material_markup_percent=12.0,
            labor_mounting_hours=60.0,
            labor_programming_hours=30.0,
            labor_commissioning_hours=20.0,
            hourly_rate_mounting=120.0,
            hourly_rate_programming=150.0,
            hourly_rate_commissioning=150.0,
            overhead_costs=800.0,
            discount_percent=5.0,
            vat_percent=8.1,
            validity_days=30,
            payment_terms="14 Tage netto",
        )
        q.items.append(QuotationItem(position=1, manufacturer="MDT", quantity=2))
        return q

    def test_to_dict_contains_all_keys(self):
        q = self._full_quote()
        d = q.to_dict()
        for key in (
            "id", "quote_number", "revision", "date_created", "status",
            "customer_name", "customer_address",
            "material_total", "material_markup_percent",
            "labor_mounting_hours", "labor_programming_hours", "labor_commissioning_hours",
            "hourly_rate_mounting", "hourly_rate_programming", "hourly_rate_commissioning",
            "overhead_costs", "discount_percent", "vat_percent",
            "validity_days", "payment_terms", "items",
            "actual_material_cost", "actual_mounting_hours",
            "actual_programming_hours", "actual_commissioning_hours", "actual_overhead_costs",
        ):
            assert key in d, f"Schluessel '{key}' fehlt in to_dict()"

    def test_full_round_trip(self):
        q = self._full_quote()
        restored = CustomerQuote.from_dict(q.to_dict())
        assert restored.quote_number == "OF-2026-001"
        assert restored.revision == "B"
        assert restored.status == "Versendet"
        assert restored.customer_name == "Mustermann AG"
        assert restored.material_total == 15_000.0
        assert restored.material_markup_percent == 12.0
        assert restored.discount_percent == 5.0
        assert restored.vat_percent == 8.1
        assert restored.validity_days == 30
        assert restored.payment_terms == "14 Tage netto"

    def test_items_preserved_in_round_trip(self):
        q = self._full_quote()
        restored = CustomerQuote.from_dict(q.to_dict())
        assert len(restored.items) == 1
        assert restored.items[0].manufacturer == "MDT"
        assert restored.items[0].quantity == 2

    def test_default_values_after_from_dict_empty(self):
        q = CustomerQuote.from_dict({})
        assert q.material_markup_percent == 15.0
        assert q.vat_percent == 8.1
        assert q.validity_days == 60
        assert q.payment_terms == "30 Tage netto"
        assert q.items == []
