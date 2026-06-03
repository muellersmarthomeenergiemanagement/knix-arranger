"""
Nachkalkulation (FA-2201 bis FA-2204)
Soll-Ist-Vergleich für Kundenofferten.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime

from ..models.quotation import CustomerQuote
from ..utils.pdf_generator import PdfGenerator

logger = logging.getLogger("knix_arranger.post_calculation")


@dataclass
class PostCalculationResult:
    """Ergebnis der Nachkalkulation (FA-2202)."""
    # Soll (aus Offerte)
    planned_material: float = 0.0
    planned_labor: float = 0.0
    planned_overhead: float = 0.0
    planned_total: float = 0.0
    # Ist (tatsaechlich)
    actual_material: float = 0.0
    actual_labor: float = 0.0
    actual_overhead: float = 0.0
    actual_total: float = 0.0
    # Delta
    delta_material: float = 0.0
    delta_labor: float = 0.0
    delta_overhead: float = 0.0
    delta_total: float = 0.0
    delta_percent: float = 0.0


class PostCalculationService:
    """Erzeugt Soll-Ist-Vergleiche für Kundenofferten (FA-2201)."""

    def calculate_comparison(self, quote: CustomerQuote) -> PostCalculationResult:
        """Berechnet den Soll-Ist-Vergleich (FA-2202)."""
        result = PostCalculationResult()

        # Soll-Werte aus Offerte
        result.planned_material = quote.material_with_markup
        result.planned_labor = quote.labor_total
        result.planned_overhead = quote.overhead_costs
        result.planned_total = quote.net_total

        # Ist-Werte
        result.actual_material = quote.actual_material_cost
        result.actual_labor = quote.actual_labor_total
        result.actual_overhead = quote.actual_overhead_costs
        result.actual_total = (
            result.actual_material + result.actual_labor + result.actual_overhead
        )

        # Delta
        result.delta_material = result.actual_material - result.planned_material
        result.delta_labor = result.actual_labor - result.planned_labor
        result.delta_overhead = result.actual_overhead - result.planned_overhead
        result.delta_total = result.actual_total - result.planned_total

        if result.planned_total > 0:
            result.delta_percent = (result.delta_total / result.planned_total) * 100

        return result

    def generate_report(self, quote: CustomerQuote,
                        filepath: str, project_name: str = "",
                        company_profile=None, project_info=None):
        """Erzeugt einen Nachkalkulations-Bericht als PDF (FA-2203)."""
        result = self.calculate_comparison(quote)

        pdf = PdfGenerator(
            title="Nachkalkulation",
            project_name=project_name,
            company_profile=company_profile,
            project_info=project_info,
        )

        pdf.add_heading("Nachkalkulation", level=1)
        pdf.add_paragraph(
            f"Offerte: {quote.quote_number} Rev. {quote.revision} | "
            f"Kunde: {quote.customer_name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y')}"
        )
        pdf.add_separator()

        # Soll-Ist-Tabelle (FA-2204)
        pdf.add_heading("Soll-Ist-Vergleich", level=2)
        headers = ["Kostenart", "Soll (CHF)", "Ist (CHF)", "Abweichung (CHF)", "Abweichung (%)"]
        rows = [
            [
                "Material",
                f"{result.planned_material:,.2f}",
                f"{result.actual_material:,.2f}",
                f"{result.delta_material:+,.2f}",
                self._percent_str(result.planned_material, result.delta_material),
            ],
            [
                "Arbeitszeit",
                f"{result.planned_labor:,.2f}",
                f"{result.actual_labor:,.2f}",
                f"{result.delta_labor:+,.2f}",
                self._percent_str(result.planned_labor, result.delta_labor),
            ],
            [
                "Nebenkosten",
                f"{result.planned_overhead:,.2f}",
                f"{result.actual_overhead:,.2f}",
                f"{result.delta_overhead:+,.2f}",
                self._percent_str(result.planned_overhead, result.delta_overhead),
            ],
            [
                "GESAMT",
                f"{result.planned_total:,.2f}",
                f"{result.actual_total:,.2f}",
                f"{result.delta_total:+,.2f}",
                f"{result.delta_percent:+.1f}%",
            ],
        ]
        pdf.add_table(headers, rows)

        # Stundenvergleich
        pdf.add_separator()
        pdf.add_heading("Stundenvergleich", level=2)
        headers2 = ["Taetigkeit", "Soll (h)", "Ist (h)", "Abweichung (h)"]
        rows2 = [
            [
                "Montage",
                f"{quote.labor_mounting_hours:.1f}",
                f"{quote.actual_mounting_hours:.1f}",
                f"{quote.actual_mounting_hours - quote.labor_mounting_hours:+.1f}",
            ],
            [
                "Programmierung",
                f"{quote.labor_programming_hours:.1f}",
                f"{quote.actual_programming_hours:.1f}",
                f"{quote.actual_programming_hours - quote.labor_programming_hours:+.1f}",
            ],
            [
                "Inbetriebnahme",
                f"{quote.labor_commissioning_hours:.1f}",
                f"{quote.actual_commissioning_hours:.1f}",
                f"{quote.actual_commissioning_hours - quote.labor_commissioning_hours:+.1f}",
            ],
        ]
        pdf.add_table(headers2, rows2)

        # Bewertung
        pdf.add_separator()
        pdf.add_heading("Bewertung", level=2)
        if result.delta_percent > 5:
            pdf.add_paragraph(
                f"Das Projekt ueberschreitet das Budget um {result.delta_percent:.1f}%. "
                "Eine Analyse der Ursachen wird empfohlen."
            )
        elif result.delta_percent < -5:
            pdf.add_paragraph(
                f"Das Projekt liegt {abs(result.delta_percent):.1f}% unter dem Budget. "
                "Die Kalkulation kann für zukuenftige Projekte optimiert werden."
            )
        else:
            pdf.add_paragraph(
                f"Das Projekt liegt mit {result.delta_percent:+.1f}% im Rahmen des Budgets."
            )

        pdf.save(filepath)
        logger.info(f"Nachkalkulations-Bericht erstellt: {filepath}")
        return result

    @staticmethod
    def _percent_str(planned: float, delta: float) -> str:
        if planned > 0:
            return f"{(delta / planned) * 100:+.1f}%"
        return "-"
