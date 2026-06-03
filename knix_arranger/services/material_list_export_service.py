"""
Materialliste Excel-Export (FA-2307)
Exportiert die Materialliste als formatierte .xlsx-Datei.
"""
from __future__ import annotations
import logging
from datetime import datetime

logger = logging.getLogger("knix_arranger.material_list_export")


class MaterialListExportService:
    """
    Exportiert eine MaterialList als Excel-Datei (FA-2307).

    Blatt 1 – Alle Positionen: vollständige Tabelle aller Einträge
    Blatt 2 – Zusammenfassung:  Mengen und Preise nach Kategorie
    """

    def export_xlsx(self, material_list, project_name: str, filepath: str) -> None:
        """
        Erzeugt eine .xlsx-Datei mit zwei Blättern.

        Args:
            material_list: MaterialList-Objekt
            project_name:  Projektname für Kopfzeile
            filepath:      Zielpfad (wird auf .xlsx normiert)
        """
        try:
            from ..utils.excel_generator import ExcelGenerator, HAS_OPENPYXL
        except ImportError:
            HAS_OPENPYXL = False

        if not HAS_OPENPYXL:
            raise ImportError(
                "openpyxl ist nicht installiert. "
                "Bitte installieren mit: pip install openpyxl"
            )

        from ..utils.excel_generator import ExcelGenerator

        gen = ExcelGenerator(
            title="Materialliste",
            company="",
            project_name=project_name,
        )

        # ── Blatt 1: Alle Positionen ──────────────────────────────────────────
        gen.add_header()
        gen.add_heading("Alle Positionen", level=1)
        gen.add_empty_row()

        headers = [
            "Anz.", "Kategorie", "Typ / Gerätebezeichnung",
            "Hersteller", "Bestellnummer", "Produktname",
            "Einbauort", "Linie", "Einzelpreis (CHF)", "Gesamtpreis (CHF)",
        ]
        col_widths = [6, 14, 28, 18, 18, 32, 22, 24, 18, 18]

        rows = []
        for entry in material_list.entries:
            unit_price_str = f"{entry.unit_price:.2f}" if entry.unit_price else ""
            total_price_str = (
                f"{entry.total_price:.2f}" if entry.unit_price else ""
            )
            rows.append([
                entry.quantity,
                entry.category,
                entry.device_type,
                entry.manufacturer or "– (Platzhalter)",
                entry.order_number,
                entry.product_name or entry.device_type,
                entry.installation_location,
                entry.line_name,
                unit_price_str,
                total_price_str,
            ])

        gen.add_table(headers, rows, col_widths=col_widths)

        # Gesamtsumme
        total_price = material_list.total_price
        total_qty = material_list.total_quantity
        if total_price:
            gen.add_paragraph(
                f"Gesamtanzahl: {total_qty} Geräte  |  "
                f"Materialwert total: CHF {total_price:,.2f}"
            )

        # ── Blatt 2: Zusammenfassung nach Kategorie ───────────────────────────
        gen.add_sheet("Zusammenfassung")
        gen.add_header()
        gen.add_heading("Zusammenfassung nach Kategorie", level=1)
        gen.add_empty_row()

        # Kategorien aggregieren
        from collections import defaultdict
        cat_qty: dict[str, int] = defaultdict(int)
        cat_assigned: dict[str, int] = defaultdict(int)
        cat_price: dict[str, float] = defaultdict(float)

        for entry in material_list.entries:
            cat_qty[entry.category] += entry.quantity
            if entry.manufacturer:
                cat_assigned[entry.category] += entry.quantity
            cat_price[entry.category] += entry.total_price

        sum_headers = [
            "Kategorie", "Anzahl gesamt", "davon zugewiesen",
            "davon Platzhalter", "Materialwert (CHF)",
        ]
        sum_rows = []
        for cat in sorted(cat_qty.keys()):
            qty = cat_qty[cat]
            assigned = cat_assigned[cat]
            placeholder = qty - assigned
            price = cat_price[cat]
            sum_rows.append([
                cat,
                qty,
                assigned,
                placeholder,
                f"{price:,.2f}" if price else "",
            ])

        # Summenzeile
        total_assigned = sum(cat_assigned.values())
        total_placeholder = total_qty - total_assigned
        sum_rows.append([
            "TOTAL",
            total_qty,
            total_assigned,
            total_placeholder,
            f"{total_price:,.2f}" if total_price else "",
        ])

        gen.add_table(sum_headers, sum_rows, col_widths=[22, 16, 18, 18, 20])

        gen.add_empty_row()
        gen.add_paragraph(
            f"Exportiert am {datetime.now().strftime('%d.%m.%Y %H:%M')} "
            f"– Projekt: {project_name}"
        )

        if not filepath.endswith(".xlsx"):
            filepath += ".xlsx"
        gen.save(filepath)
        logger.info(f"Materialliste exportiert: {filepath}")
