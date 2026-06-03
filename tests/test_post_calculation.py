"""Tests fuer PostCalculationService (FA-2201-2204)."""
from knix_arranger.models.quotation import CustomerQuote
from knix_arranger.services.post_calculation_service import (
    PostCalculationService, PostCalculationResult,
)


class TestPostCalculation:
    def setup_method(self):
        self.svc = PostCalculationService()
        self.quote = CustomerQuote(
            quote_number="OF-2026-001",
            material_total=10000.0,
            material_markup_percent=15.0,
            labor_mounting_hours=40.0,
            hourly_rate_mounting=125.0,
            labor_programming_hours=20.0,
            hourly_rate_programming=145.0,
            labor_commissioning_hours=16.0,
            hourly_rate_commissioning=145.0,
            overhead_costs=500.0,
            # Ist-Werte
            actual_material_cost=11000.0,
            actual_mounting_hours=45.0,
            actual_programming_hours=18.0,
            actual_commissioning_hours=20.0,
            actual_overhead_costs=600.0,
        )

    def test_actual_labor_total(self):
        """Ist-Arbeitszeit berechnet sich aus Stunden * Stundensaetzen."""
        expected = (
            45.0 * 125.0 +   # Montage
            18.0 * 145.0 +   # Programmierung
            20.0 * 145.0     # Inbetriebnahme
        )
        assert self.quote.actual_labor_total == expected

    def test_actual_total(self):
        total = self.quote.actual_material_cost + self.quote.actual_labor_total + 600.0
        assert self.quote.actual_total == total

    def test_delta_material(self):
        assert self.quote.delta_material == 11000.0 - self.quote.material_with_markup

    def test_delta_labor(self):
        assert self.quote.delta_labor == self.quote.actual_labor_total - self.quote.labor_total

    def test_delta_total(self):
        assert self.quote.delta_total == self.quote.actual_total - self.quote.subtotal

    def test_calculate_comparison(self):
        result = self.svc.calculate_comparison(self.quote)
        assert isinstance(result, PostCalculationResult)
        assert result.planned_material == self.quote.material_with_markup
        assert result.actual_material == 11000.0

    def test_serialization(self):
        """Ist-Werte muessen in to_dict/from_dict enthalten sein."""
        d = self.quote.to_dict()
        assert d["actual_material_cost"] == 11000.0
        assert d["actual_mounting_hours"] == 45.0

        restored = CustomerQuote.from_dict(d)
        assert restored.actual_material_cost == 11000.0
        assert restored.actual_mounting_hours == 45.0
