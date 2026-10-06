"""
Kundenofferte-Verwaltung (FA-1701 bis FA-1715)
"""
from __future__ import annotations
import hashlib
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QSpinBox,
    QLineEdit, QGroupBox, QFormLayout, QAbstractItemView,
    QMessageBox, QDoubleSpinBox, QTabWidget, QFileDialog, QPlainTextEdit,
)
from PySide6.QtCore import Qt
from ...models.project import KnxProject
from ...models.quotation import CustomerQuote, QuotationItem, round_rappen
from ...services.material_list_export_service import MaterialListExportService
from ..column_utils import fit_columns


def address_block(text: str) -> str:
    """Postadresse für den Briefkopf: das Kundenprofil speichert sie
    einzeilig ("Musterstrasse 1, 8000 Zürich") -> eine Zeile je Teil."""
    if "\n" in text:
        return text.strip()
    return "\n".join(p.strip() for p in text.split(",") if p.strip())


def _material_signature(ml) -> str:
    """Signatur des bepreisten Materiallisten-Stands -- dieselbe Filterung
    wie beim Positionsimport (nur Einträge mit unit_price), damit Signatur
    und importierte Positionen immer synchron bleiben."""
    parts = sorted(
        f"{e.manufacturer}|{e.order_number}|{e.quantity}"
        for e in ml.entries if e.unit_price
    )
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


class CustomerQuoteView(QWidget):
    """Kundenofferte: Kalkulation, Positionen, Kostenübersicht."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        self._bus = None

        layout = QVBoxLayout(self)

        title = QLabel("Kundenofferte")
        title.setObjectName("title")
        layout.addWidget(title)

        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        # Tabs: Offerten | Kalkulation | Nachkalkulation
        self._tabs = QTabWidget()
        self._tabs.addTab(self._create_quotes_tab(), "Offerten")
        self._tabs.addTab(self._create_calculation_tab(), "Kalkulation")
        self._tabs.addTab(self._create_postcalc_tab(), "Nachkalkulation")
        layout.addWidget(self._tabs)

    # ── Offerten-Tab ──

    def _create_quotes_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        content = QHBoxLayout()

        # Tabelle
        left = QVBoxLayout()
        self._quote_table = QTableWidget()
        self._quote_table.setColumnCount(7)
        self._quote_table.setHorizontalHeaderLabels([
            "Offert-Nr.", "Rev.", "Datum", "Kunde", "Status", "Total (CHF)",
            "Aktualität",
        ])
        self._quote_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._quote_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._quote_table.horizontalHeader().setStretchLastSection(True)
        self._quote_table.setAlternatingRowColors(True)
        self._quote_table.currentCellChanged.connect(self._on_quote_selected)
        left.addWidget(self._quote_table)

        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("+ Neue Offerte")
        self._btn_add.clicked.connect(self._add_quote)
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("danger")
        self._btn_remove.clicked.connect(self._remove_quote)
        self._btn_export_quote = QPushButton("Als Excel exportieren…")
        self._btn_export_quote.setToolTip(
            "Ausgewählte Offerte als .xlsx exportieren"
        )
        self._btn_export_quote.clicked.connect(self._export_quote_excel)
        self._btn_create_letter = QPushButton("Brief erstellen…")
        self._btn_create_letter.setToolTip(
            "Offerte als professionellen PDF-Brief exportieren"
        )
        self._btn_create_letter.clicked.connect(self._create_letter)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_remove)
        btn_layout.addWidget(self._btn_export_quote)
        btn_layout.addWidget(self._btn_create_letter)
        btn_layout.addStretch()
        left.addLayout(btn_layout)

        content.addLayout(left, 2)

        # Detail-Panel
        right = QVBoxLayout()
        self._detail_group = QGroupBox("Offert-Details")
        form = QFormLayout()

        self._quote_number = QLineEdit()
        self._quote_number.setReadOnly(True)
        form.addRow("Offert-Nr.:", self._quote_number)

        self._quote_rev = QLineEdit()
        self._quote_rev.setMaximumWidth(60)
        form.addRow("Revision:", self._quote_rev)

        self._quote_date = QLineEdit()
        self._quote_date.setReadOnly(True)
        form.addRow("Datum:", self._quote_date)

        self._quote_customer = QLineEdit()
        self._quote_customer.setPlaceholderText("Name des Bauherrn")
        form.addRow("Kunde:", self._quote_customer)

        self._quote_address = QPlainTextEdit()
        self._quote_address.setPlaceholderText("Strasse\nPLZ Ort")
        self._quote_address.setFixedHeight(64)
        form.addRow("Adresse:", self._quote_address)

        self._quote_salutation = QLineEdit()
        self._quote_salutation.setPlaceholderText("Sehr geehrte Damen und Herren")
        form.addRow("Anrede:", self._quote_salutation)

        self._btn_from_client = QPushButton("Aus Kundenprofil übernehmen")
        self._btn_from_client.setToolTip(
            "Name, Postadresse und Anrede aus dem Kundenprofil (Berichte → Kundenprofil) "
            "in diese Offerte übernehmen. Bestehende Offerten ändern sich sonst "
            "nicht, wenn das Kundenprofil später angepasst wird.")
        self._btn_from_client.clicked.connect(self._fill_from_client)
        self._btn_edit_client = QPushButton("Kundenprofil bearbeiten…")
        self._btn_edit_client.setToolTip("Bauherr, Objekt- und Postadresse, Anrede "
                                         "(auch unter Datei → Kundenprofil)")
        self._btn_edit_client.clicked.connect(self._edit_client)
        client_row = QHBoxLayout()
        client_row.addWidget(self._btn_from_client)
        client_row.addWidget(self._btn_edit_client)
        form.addRow("", client_row)

        self._quote_status = QComboBox()
        # Anzeige mit Umlaut, gespeichert wird der bisherige Wert (Kompatibilität
        # mit bestehenden Projektdateien)
        for label, value in (
            ("Entwurf", "Entwurf"), ("Versendet", "Versendet"),
            ("Akzeptiert", "Akzeptiert"), ("Abgelehnt", "Abgelehnt"),
            ("Überarbeitung", "Ueberarbeitung"),
        ):
            self._quote_status.addItem(label, value)
        form.addRow("Status:", self._quote_status)

        self._quote_validity = QSpinBox()
        self._quote_validity.setRange(1, 365)
        self._quote_validity.setValue(60)
        self._quote_validity.setSuffix(" Tage")
        form.addRow("Gültigkeit:", self._quote_validity)

        self._quote_payment = QLineEdit()
        self._quote_payment.setText("30 Tage netto")
        form.addRow("Zahlung:", self._quote_payment)

        self._btn_apply = QPushButton("Übernehmen")
        self._btn_apply.clicked.connect(self._apply_quote)
        form.addRow("", self._btn_apply)

        self._detail_group.setLayout(form)
        right.addWidget(self._detail_group)

        self._stale_warning = QLabel("")
        self._stale_warning.setStyleSheet("color: #c62828; font-weight: bold;")
        self._stale_warning.setWordWrap(True)
        self._stale_warning.setVisible(False)
        right.addWidget(self._stale_warning)

        right.addStretch()

        content.addLayout(right, 1)

        # Obere Hälfte: Offertenliste + Detailformular
        layout.addLayout(content, 0)

        # Untere Hälfte: Positionstabelle über volle Breite
        self._items_group = QGroupBox("Positionen")
        items_layout = QVBoxLayout()

        self._items_table = QTableWidget()
        self._items_table.setColumnCount(5)
        self._items_table.setHorizontalHeaderLabels([
            "Pos.", "Produkt", "Menge", "Einzelpreis (CHF)", "Total (CHF)",
        ])
        self._items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._items_table.horizontalHeader().setStretchLastSection(True)
        # Standardbreite (100 px) war schmaler als "Einzelpreis (CHF)"
        for col in range(self._items_table.columnCount()):
            self._items_table.setColumnWidth(
                col, max(100, self._items_table.horizontalHeader().sectionSizeHint(col) + 16))
        items_layout.addWidget(self._items_table)

        add_layout = QHBoxLayout()
        self._item_product = QLineEdit()
        self._item_product.setPlaceholderText("Produkt/Leistung")
        add_layout.addWidget(self._item_product, 3)

        self._item_qty = QSpinBox()
        self._item_qty.setRange(1, 999)
        add_layout.addWidget(self._item_qty)

        self._item_price = QDoubleSpinBox()
        self._item_price.setRange(0, 999999)
        self._item_price.setDecimals(2)
        self._item_price.setPrefix("CHF ")
        add_layout.addWidget(self._item_price)

        # Padding-Override: das globale QPushButton-Padding (8px 16px) ist
        # breiter als diese schmalen Buttons -- ohne Override verschwindet
        # das "+"/"-" spurlos, weil kein Platz dafuer bleibt.
        self._btn_add_item = QPushButton("+")
        self._btn_add_item.setFixedWidth(30)
        self._btn_add_item.setStyleSheet("padding: 2px;")
        self._btn_add_item.clicked.connect(self._add_item)
        add_layout.addWidget(self._btn_add_item)

        self._btn_remove_item = QPushButton("-")
        self._btn_remove_item.setFixedWidth(30)
        self._btn_remove_item.setObjectName("danger")
        self._btn_remove_item.setStyleSheet("padding: 2px;")
        self._btn_remove_item.clicked.connect(self._remove_item)
        add_layout.addWidget(self._btn_remove_item)

        add_layout.addStretch()
        items_layout.addLayout(add_layout)
        self._items_group.setLayout(items_layout)
        layout.addWidget(self._items_group, 1)

        return widget

    # ── Kalkulations-Tab ──

    def _create_calculation_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        hint = QLabel(
            "Wählen Sie in der Offerten-Ansicht eine Offerte aus,\n"
            "um hier die Kalkulation zu bearbeiten."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        calc_layout = QHBoxLayout()

        # Kosten-Eingabe
        left = QVBoxLayout()
        cost_group = QGroupBox("Kostenarten")
        cost_form = QFormLayout()

        self._material_total = QDoubleSpinBox()
        self._material_total.setRange(0, 9999999)
        self._material_total.setDecimals(2)
        self._material_total.setPrefix("CHF ")
        cost_form.addRow("Material gesamt:", self._material_total)

        self._material_markup = QDoubleSpinBox()
        self._material_markup.setRange(0, 100)
        self._material_markup.setDecimals(1)
        self._material_markup.setSuffix(" %")
        self._material_markup.setValue(15.0)
        cost_form.addRow("Material-Aufschlag:", self._material_markup)

        self._hours_mounting = QDoubleSpinBox()
        self._hours_mounting.setRange(0, 9999)
        self._hours_mounting.setDecimals(1)
        self._hours_mounting.setSuffix(" h")
        cost_form.addRow("Montage:", self._hours_mounting)

        self._rate_mounting = QDoubleSpinBox()
        self._rate_mounting.setRange(0, 999)
        self._rate_mounting.setDecimals(2)
        self._rate_mounting.setPrefix("CHF ")
        self._rate_mounting.setValue(125.0)
        cost_form.addRow("Stundensatz Montage:", self._rate_mounting)

        self._hours_programming = QDoubleSpinBox()
        self._hours_programming.setRange(0, 9999)
        self._hours_programming.setDecimals(1)
        self._hours_programming.setSuffix(" h")
        cost_form.addRow("Programmierung:", self._hours_programming)

        self._rate_programming = QDoubleSpinBox()
        self._rate_programming.setRange(0, 999)
        self._rate_programming.setDecimals(2)
        self._rate_programming.setPrefix("CHF ")
        self._rate_programming.setValue(145.0)
        cost_form.addRow("Stundensatz Progr.:", self._rate_programming)

        self._hours_commissioning = QDoubleSpinBox()
        self._hours_commissioning.setRange(0, 9999)
        self._hours_commissioning.setDecimals(1)
        self._hours_commissioning.setSuffix(" h")
        cost_form.addRow("Inbetriebnahme:", self._hours_commissioning)

        self._rate_commissioning = QDoubleSpinBox()
        self._rate_commissioning.setRange(0, 999)
        self._rate_commissioning.setDecimals(2)
        self._rate_commissioning.setPrefix("CHF ")
        self._rate_commissioning.setValue(145.0)
        cost_form.addRow("Stundensatz IBN:", self._rate_commissioning)

        self._hours_documentation = QDoubleSpinBox()
        self._hours_documentation.setRange(0, 9999)
        self._hours_documentation.setDecimals(1)
        self._hours_documentation.setSuffix(" h")
        cost_form.addRow("Dokumentation:", self._hours_documentation)

        self._rate_documentation = QDoubleSpinBox()
        self._rate_documentation.setRange(0, 999)
        self._rate_documentation.setDecimals(2)
        self._rate_documentation.setPrefix("CHF ")
        self._rate_documentation.setValue(125.0)
        cost_form.addRow("Stundensatz Dok.:", self._rate_documentation)

        self._overhead = QDoubleSpinBox()
        self._overhead.setRange(0, 999999)
        self._overhead.setDecimals(2)
        self._overhead.setPrefix("CHF ")
        cost_form.addRow("Nebenkosten:", self._overhead)

        self._discount = QDoubleSpinBox()
        self._discount.setRange(0, 100)
        self._discount.setDecimals(1)
        self._discount.setSuffix(" %")
        cost_form.addRow("Rabatt:", self._discount)

        self._vat = QDoubleSpinBox()
        self._vat.setRange(0, 30)
        self._vat.setDecimals(1)
        self._vat.setSuffix(" %")
        self._vat.setValue(8.1)
        cost_form.addRow("MwSt.:", self._vat)

        self._btn_import_material = QPushButton("Aus Materialliste importieren")
        self._btn_import_material.setToolTip(
            "Materialwert und Positionen aus der Projektmaterialliste übernehmen"
        )
        self._btn_import_material.clicked.connect(self._import_from_material_list)
        cost_form.addRow("", self._btn_import_material)

        self._btn_import_awarded = QPushButton("Aus Lieferantenofferten übernehmen…")
        self._btn_import_awarded.setToolTip(
            "Materialkosten aus zugeschlagenen Offertanfragen übernehmen.\n"
            "Voraussetzung: Offertanfragen mit Status 'Zugeschlagen' vorhanden."
        )
        self._btn_import_awarded.clicked.connect(self._import_from_awarded_requests)
        cost_form.addRow("", self._btn_import_awarded)

        self._btn_estimate_effort = QPushButton("Aufwand automatisch schätzen…")
        self._btn_estimate_effort.setToolTip(
            "Schätzt Programmier- und Inbetriebnahmestunden aus der Anzahl "
            "Busgeräte in der Topologie.\n"
            "Richtwerte editierbar unter Einstellungen → Stundensätze."
        )
        self._btn_estimate_effort.clicked.connect(self._estimate_effort)
        cost_form.addRow("", self._btn_estimate_effort)

        self._btn_calc = QPushButton("Berechnen + Übernehmen")
        self._btn_calc.clicked.connect(self._calculate)
        cost_form.addRow("", self._btn_calc)

        cost_group.setLayout(cost_form)
        left.addWidget(cost_group)

        calc_layout.addLayout(left, 1)

        # Ergebnis
        right = QVBoxLayout()
        result_group = QGroupBox("Kalkulations-Ergebnis")
        result_layout = QVBoxLayout()

        self._result_table = QTableWidget()
        self._result_table.setColumnCount(2)
        self._result_table.setHorizontalHeaderLabels(["Position", "Betrag (CHF)"])
        self._result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._result_table.horizontalHeader().setStretchLastSection(True)
        result_layout.addWidget(self._result_table)

        self._grand_total_label = QLabel("Gesamtbetrag: CHF 0.00")
        self._grand_total_label.setStyleSheet("font-size: 20px; font-weight: bold; padding: 10px;")
        result_layout.addWidget(self._grand_total_label)

        result_group.setLayout(result_layout)
        right.addWidget(result_group)
        right.addStretch()

        calc_layout.addLayout(right, 1)
        layout.addLayout(calc_layout)

        return widget

    # ── Nachkalkulation-Tab (FA-2201) ──

    def _create_postcalc_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        hint = QLabel(
            "Erfassen Sie die tatsächlichen Kosten (Ist-Werte) und vergleichen\n"
            "Sie diese mit der ursprünglichen Kalkulation (Soll-Werte)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        calc_layout = QHBoxLayout()

        # Ist-Eingabe
        left = QVBoxLayout()
        actual_group = QGroupBox("Ist-Werte erfassen")
        actual_form = QFormLayout()

        self._actual_material = QDoubleSpinBox()
        self._actual_material.setRange(0, 9999999)
        self._actual_material.setDecimals(2)
        self._actual_material.setPrefix("CHF ")
        actual_form.addRow("Material (Ist):", self._actual_material)

        self._actual_mounting = QDoubleSpinBox()
        self._actual_mounting.setRange(0, 9999)
        self._actual_mounting.setDecimals(1)
        self._actual_mounting.setSuffix(" h")
        actual_form.addRow("Montage (Ist):", self._actual_mounting)

        self._actual_programming = QDoubleSpinBox()
        self._actual_programming.setRange(0, 9999)
        self._actual_programming.setDecimals(1)
        self._actual_programming.setSuffix(" h")
        actual_form.addRow("Programmierung (Ist):", self._actual_programming)

        self._actual_commissioning = QDoubleSpinBox()
        self._actual_commissioning.setRange(0, 9999)
        self._actual_commissioning.setDecimals(1)
        self._actual_commissioning.setSuffix(" h")
        actual_form.addRow("Inbetriebnahme (Ist):", self._actual_commissioning)

        self._actual_documentation = QDoubleSpinBox()
        self._actual_documentation.setRange(0, 9999)
        self._actual_documentation.setDecimals(1)
        self._actual_documentation.setSuffix(" h")
        actual_form.addRow("Dokumentation (Ist):", self._actual_documentation)

        self._actual_overhead = QDoubleSpinBox()
        self._actual_overhead.setRange(0, 999999)
        self._actual_overhead.setDecimals(2)
        self._actual_overhead.setPrefix("CHF ")
        actual_form.addRow("Nebenkosten (Ist):", self._actual_overhead)

        self._btn_postcalc = QPushButton("Soll/Ist vergleichen")
        self._btn_postcalc.clicked.connect(self._run_postcalc)
        actual_form.addRow("", self._btn_postcalc)

        actual_group.setLayout(actual_form)
        left.addWidget(actual_group)
        left.addStretch()
        calc_layout.addLayout(left, 1)

        # Vergleich (FA-2202)
        right = QVBoxLayout()
        compare_group = QGroupBox("Soll/Ist-Vergleich")
        compare_layout = QVBoxLayout()

        self._postcalc_table = QTableWidget()
        self._postcalc_table.setColumnCount(4)
        self._postcalc_table.setHorizontalHeaderLabels([
            "Position", "Soll (CHF)", "Ist (CHF)", "Delta (CHF)",
        ])
        self._postcalc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._postcalc_table.horizontalHeader().setStretchLastSection(True)
        compare_layout.addWidget(self._postcalc_table)

        self._postcalc_summary = QLabel("")
        self._postcalc_summary.setStyleSheet(
            "font-size: 16px; font-weight: bold; padding: 10px;"
        )
        compare_layout.addWidget(self._postcalc_summary)

        compare_group.setLayout(compare_layout)
        right.addWidget(compare_group)
        right.addStretch()
        calc_layout.addLayout(right, 1)

        layout.addLayout(calc_layout)
        return widget

    def _run_postcalc(self):
        """Fuehrt den Soll/Ist-Vergleich durch (FA-2202)."""
        cq = self._get_selected_quote()
        if not cq:
            return

        # Ist-Werte ins Modell uebernehmen
        cq.actual_material_cost = self._actual_material.value()
        cq.actual_mounting_hours = self._actual_mounting.value()
        cq.actual_programming_hours = self._actual_programming.value()
        cq.actual_commissioning_hours = self._actual_commissioning.value()
        cq.actual_documentation_hours = self._actual_documentation.value()
        cq.actual_overhead_costs = self._actual_overhead.value()

        # Vergleichstabelle
        rows = [
            ("Material",
             f"{cq.material_with_markup:,.2f}",
             f"{cq.actual_material_cost:,.2f}",
             f"{cq.delta_material:,.2f}"),
            ("Arbeitszeit",
             f"{cq.labor_total:,.2f}",
             f"{cq.actual_labor_total:,.2f}",
             f"{cq.delta_labor:,.2f}"),
            ("Nebenkosten",
             f"{cq.overhead_costs:,.2f}",
             f"{cq.actual_overhead_costs:,.2f}",
             f"{cq.actual_overhead_costs - cq.overhead_costs:,.2f}"),
            ("TOTAL",
             f"{cq.subtotal:,.2f}",
             f"{cq.actual_total:,.2f}",
             f"{cq.delta_total:,.2f}"),
        ]

        self._postcalc_table.setRowCount(len(rows))
        for i, (label, soll, ist, delta) in enumerate(rows):
            items = [
                QTableWidgetItem(label),
                QTableWidgetItem(soll),
                QTableWidgetItem(ist),
                QTableWidgetItem(delta),
            ]
            if label == "TOTAL":
                for item in items:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            self._postcalc_table.setItem(i, 0, items[0])
            self._postcalc_table.setItem(i, 1, items[1])
            self._postcalc_table.setItem(i, 2, items[2])
            self._postcalc_table.setItem(i, 3, items[3])
        fit_columns(self._postcalc_table)

        pct = cq.delta_percent
        color = "green" if pct <= 0 else ("orange" if pct < 10 else "red")
        self._postcalc_summary.setStyleSheet(
            f"font-size: 16px; font-weight: bold; padding: 10px; color: {color};"
        )
        self._postcalc_summary.setText(
            f"Abweichung: CHF {cq.delta_total:,.2f} ({pct:+.1f}%)"
        )

    def _load_postcalc(self, cq: CustomerQuote):
        """Lädt Ist-Werte in die Nachkalkulation."""
        self._actual_material.setValue(cq.actual_material_cost)
        self._actual_mounting.setValue(cq.actual_mounting_hours)
        self._actual_programming.setValue(cq.actual_programming_hours)
        self._actual_commissioning.setValue(cq.actual_commissioning_hours)
        self._actual_documentation.setValue(cq.actual_documentation_hours)
        self._actual_overhead.setValue(cq.actual_overhead_costs)

    # ── Public ──

    def set_bus(self, bus) -> None:
        """ProjectBus für Rückgängig-Punkte (Kundenprofil bearbeiten)."""
        self._bus = bus

    def set_project(self, project: KnxProject):
        self._project = project
        self._refresh_quotes()

    # ── Offerten-Logik ──

    def _is_stale(self, cq: CustomerQuote) -> bool:
        """True wenn sich die Materialliste seit dem letzten Positionsimport
        in diese Offerte verändert hat (Offerte entspricht nicht mehr dem
        aktuellen Planungsstand)."""
        if not cq.material_snapshot or not self._project:
            return False
        return cq.material_snapshot != _material_signature(self._project.material_list)

    def _refresh_quotes(self):
        if not self._project:
            self._quote_table.setRowCount(0)
            return

        quotes = self._project.customer_quotes
        self._quote_table.setRowCount(len(quotes))
        for i, cq in enumerate(quotes):
            self._quote_table.setItem(i, 0, QTableWidgetItem(cq.quote_number))
            self._quote_table.setItem(i, 1, QTableWidgetItem(cq.revision))
            self._quote_table.setItem(i, 2, QTableWidgetItem(cq.date_created))
            self._quote_table.setItem(i, 3, QTableWidgetItem(cq.customer_name))
            self._quote_table.setItem(i, 4, QTableWidgetItem(cq.status))
            self._quote_table.setItem(
                i, 5, QTableWidgetItem(f"{round_rappen(cq.grand_total):,.2f}")
            )
            staleness = "⚠ Material geändert" if self._is_stale(cq) else ""
            self._quote_table.setItem(i, 6, QTableWidgetItem(staleness))
        fit_columns(self._quote_table)
        self._info.setText(f"{len(quotes)} Kundenofferten")

    def _on_quote_selected(self, row, col, prev_row, prev_col):
        if not self._project or row < 0 or row >= len(self._project.customer_quotes):
            return
        cq = self._project.customer_quotes[row]
        self._quote_number.setText(cq.quote_number)
        self._quote_rev.setText(cq.revision)
        self._quote_date.setText(cq.date_created)
        self._quote_customer.setText(cq.customer_name)
        self._quote_address.setPlainText(cq.customer_address)
        self._quote_salutation.setText(cq.salutation)

        idx = self._quote_status.findData(cq.status)
        if idx >= 0:
            self._quote_status.setCurrentIndex(idx)

        self._quote_validity.setValue(cq.validity_days)
        self._quote_payment.setText(cq.payment_terms)

        if self._is_stale(cq):
            if cq.status in ("Versendet", "Akzeptiert"):
                text = (
                    "Achtung: Diese bereits versendete Offerte entspricht "
                    "nicht mehr dem aktuellen Planungsstand."
                )
            else:
                text = "Hinweis: Die Materialliste wurde seit dem letzten Import verändert."
            self._stale_warning.setText(text)
            self._stale_warning.setVisible(True)
        else:
            self._stale_warning.setText("")
            self._stale_warning.setVisible(False)

        self._refresh_items(cq)
        self._load_calculation(cq)
        self._load_postcalc(cq)

    def _refresh_items(self, cq: CustomerQuote):
        self._items_table.setRowCount(len(cq.items))
        for i, item in enumerate(cq.items):
            self._items_table.setItem(i, 0, QTableWidgetItem(str(item.position)))
            self._items_table.setItem(i, 1, QTableWidgetItem(item.product_name))
            self._items_table.setItem(i, 2, QTableWidgetItem(str(item.quantity)))
            self._items_table.setItem(
                i, 3, QTableWidgetItem(f"{item.unit_price:,.2f}")
            )
            self._items_table.setItem(
                i, 4, QTableWidgetItem(f"{item.total_price:,.2f}")
            )
        fit_columns(self._items_table)

    def _load_calculation(self, cq: CustomerQuote):
        self._material_total.setValue(cq.material_total)
        self._material_markup.setValue(cq.material_markup_percent)
        self._hours_mounting.setValue(cq.labor_mounting_hours)
        self._rate_mounting.setValue(cq.hourly_rate_mounting)
        self._hours_programming.setValue(cq.labor_programming_hours)
        self._rate_programming.setValue(cq.hourly_rate_programming)
        self._hours_commissioning.setValue(cq.labor_commissioning_hours)
        self._rate_commissioning.setValue(cq.hourly_rate_commissioning)
        self._hours_documentation.setValue(cq.labor_documentation_hours)
        self._rate_documentation.setValue(cq.hourly_rate_documentation)
        self._overhead.setValue(cq.overhead_costs)
        self._discount.setValue(cq.discount_percent)
        self._vat.setValue(cq.vat_percent)
        self._update_result(cq)

    def _update_result(self, cq: CustomerQuote):
        rows = [
            ("Material (netto)", f"{round_rappen(cq.material_total):,.2f}"),
            (f"Material-Aufschlag ({cq.material_markup_percent}%)",
             f"{round_rappen(cq.material_with_markup - cq.material_total):,.2f}"),
            ("Material (brutto)", f"{round_rappen(cq.material_with_markup):,.2f}"),
            ("", ""),
            (f"Montage ({cq.labor_mounting_hours}h x CHF {cq.hourly_rate_mounting})",
             f"{round_rappen(cq.labor_mounting_hours * cq.hourly_rate_mounting):,.2f}"),
            (f"Programmierung ({cq.labor_programming_hours}h x CHF {cq.hourly_rate_programming})",
             f"{round_rappen(cq.labor_programming_hours * cq.hourly_rate_programming):,.2f}"),
            (f"Inbetriebnahme ({cq.labor_commissioning_hours}h x CHF {cq.hourly_rate_commissioning})",
             f"{round_rappen(cq.labor_commissioning_hours * cq.hourly_rate_commissioning):,.2f}"),
            (f"Dokumentation ({cq.labor_documentation_hours}h x CHF {cq.hourly_rate_documentation})",
             f"{round_rappen(cq.labor_documentation_hours * cq.hourly_rate_documentation):,.2f}"),
            ("Arbeitszeit total", f"{round_rappen(cq.labor_total):,.2f}"),
            ("", ""),
            ("Nebenkosten", f"{round_rappen(cq.overhead_costs):,.2f}"),
            ("Zwischensumme", f"{round_rappen(cq.subtotal):,.2f}"),
            (f"Rabatt ({cq.discount_percent}%)", f"-{round_rappen(cq.discount_amount):,.2f}"),
            ("Nettobetrag", f"{round_rappen(cq.net_total):,.2f}"),
            (f"MwSt. ({cq.vat_percent}%)", f"{round_rappen(cq.vat_amount):,.2f}"),
            ("GESAMTBETRAG", f"{round_rappen(cq.grand_total):,.2f}"),
        ]

        self._result_table.setRowCount(len(rows))
        for i, (label, amount) in enumerate(rows):
            item_label = QTableWidgetItem(label)
            item_amount = QTableWidgetItem(amount)
            if label in ("Material (brutto)", "Arbeitszeit total",
                         "Zwischensumme", "Nettobetrag", "GESAMTBETRAG"):
                font = item_label.font()
                font.setBold(True)
                item_label.setFont(font)
                item_amount.setFont(font)
            self._result_table.setItem(i, 0, item_label)
            self._result_table.setItem(i, 1, item_amount)
        fit_columns(self._result_table)

        self._grand_total_label.setText(f"Gesamtbetrag: CHF {round_rappen(cq.grand_total):,.2f}")

    def _add_quote(self):
        if not self._project:
            return
        next_num = len(self._project.customer_quotes) + 1
        client = getattr(self._project, "client_profile", None)
        cq = CustomerQuote(
            quote_number=f"OF-{date.today().year}-{next_num:03d}",
            date_created=date.today().isoformat(),
            # Neue Offerte mit den Daten des Kundenprofils vorbelegen
            customer_name=client.name if client else "",
            customer_address=address_block(client.contact_address) if client else "",
            salutation=client.salutation if client else "",
        )
        self._project.customer_quotes.append(cq)
        self._refresh_quotes()
        self._quote_table.selectRow(len(self._project.customer_quotes) - 1)

    def _remove_quote(self):
        if not self._project:
            return
        row = self._quote_table.currentRow()
        if row < 0 or row >= len(self._project.customer_quotes):
            return
        cq = self._project.customer_quotes[row]
        reply = QMessageBox.question(
            self, "Offerte entfernen",
            f"Kundenofferte '{cq.quote_number}' wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._project.customer_quotes.pop(row)
            self._refresh_quotes()
            self._items_table.setRowCount(0)
            self._result_table.setRowCount(0)

    def _apply_quote(self):
        if not self._project:
            return
        row = self._quote_table.currentRow()
        if row < 0 or row >= len(self._project.customer_quotes):
            return
        cq = self._project.customer_quotes[row]
        cq.revision = self._quote_rev.text()
        cq.customer_name = self._quote_customer.text()
        cq.customer_address = self._quote_address.toPlainText().strip()
        cq.salutation = self._quote_salutation.text().strip().rstrip(",")
        cq.status = self._quote_status.currentData()
        cq.validity_days = self._quote_validity.value()
        cq.payment_terms = self._quote_payment.text()
        self._refresh_quotes()

    def _edit_client(self):
        if not self._project:
            return
        from ..dialogs.client_profile_dialog import edit_client_profile
        edit_client_profile(self._project, self, self._bus)

    def _fill_from_client(self):
        """Name, Postadresse und Anrede aus dem Kundenprofil übernehmen
        (gespeichert wird erst mit "Übernehmen")."""
        client = getattr(self._project, "client_profile", None) if self._project else None
        if client is None or not (client.name or client.contact_address or client.salutation):
            QMessageBox.information(
                self, "Kundenprofil leer",
                "Im Kundenprofil sind noch kein Name und keine Postadresse erfasst "
                "(Berichte → Kundenprofil bearbeiten).",
            )
            return
        self._quote_customer.setText(client.name)
        self._quote_address.setPlainText(address_block(client.contact_address))
        self._quote_salutation.setText(client.salutation)

    def _get_selected_quote(self) -> CustomerQuote | None:
        if not self._project:
            return None
        row = self._quote_table.currentRow()
        if row < 0 or row >= len(self._project.customer_quotes):
            return None
        return self._project.customer_quotes[row]

    def _add_item(self):
        cq = self._get_selected_quote()
        if not cq:
            return
        product = self._item_product.text().strip()
        qty = self._item_qty.value()
        price = self._item_price.value()
        if not product:
            return

        next_pos = len(cq.items) + 1
        cq.items.append(QuotationItem(
            position=next_pos,
            product_name=product,
            quantity=qty,
            unit_price=price,
            total_price=qty * price,
        ))
        self._refresh_items(cq)
        self._refresh_quotes()

        self._item_product.clear()
        self._item_qty.setValue(1)
        self._item_price.setValue(0)

    def _remove_item(self):
        cq = self._get_selected_quote()
        if not cq:
            return
        row = self._items_table.currentRow()
        if 0 <= row < len(cq.items):
            cq.items.pop(row)
            self._refresh_items(cq)
            self._refresh_quotes()

    def _calculate(self):
        cq = self._get_selected_quote()
        if not cq:
            return

        cq.material_total = self._material_total.value()
        cq.material_markup_percent = self._material_markup.value()
        cq.labor_mounting_hours = self._hours_mounting.value()
        cq.hourly_rate_mounting = self._rate_mounting.value()
        cq.labor_programming_hours = self._hours_programming.value()
        cq.hourly_rate_programming = self._rate_programming.value()
        cq.labor_commissioning_hours = self._hours_commissioning.value()
        cq.hourly_rate_commissioning = self._rate_commissioning.value()
        cq.labor_documentation_hours = self._hours_documentation.value()
        cq.hourly_rate_documentation = self._rate_documentation.value()
        cq.overhead_costs = self._overhead.value()
        cq.discount_percent = self._discount.value()
        cq.vat_percent = self._vat.value()

        self._update_result(cq)
        self._refresh_quotes()

    def _import_from_material_list(self) -> None:
        """
        Übernimmt Materialwert und Positionen aus der Projektmaterialliste
        in die aktuell ausgewählte Kundenofferte (FA-2308).
        """
        cq = self._get_selected_quote()
        if not cq:
            QMessageBox.information(
                self, "Keine Offerte gewählt",
                "Bitte zuerst eine Offerte auswählen oder anlegen.",
            )
            return
        if not self._project or self._project.material_list.is_empty():
            QMessageBox.information(
                self, "Materialliste leer",
                "Die Projektmaterialliste enthält noch keine Einträge.",
            )
            return

        ml = self._project.material_list

        # Aktuellen Aufschlagssatz übernehmen, bevor er auf die Positionspreise
        # angewendet wird (Spinbox kann noch nicht via "Berechnen" gespeichert sein).
        cq.material_markup_percent = self._material_markup.value()

        # Materialwert aus den Einträgen mit bekanntem Preis summieren
        material_total = sum(
            e.total_price for e in ml.entries if e.unit_price
        )
        self._material_total.setValue(material_total)

        # Positionen aus Materialliste übernehmen (nur Einträge mit Produkt)
        reply = QMessageBox.question(
            self, "Positionen importieren",
            "Sollen die Materiallisten-Positionen (mit zugewiesenem Produkt) "
            "als Offert-Positionen übernommen werden?\n"
            "Bestehende Positionen in der Offerte werden dabei ersetzt.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            # Positionen zeigen dem Kunden den Endpreis inkl. Zuschlag, nicht
            # den Einkaufspreis aus der Materialliste (auf 5 Rappen gerundet).
            # Es werden alle bepreisten Einträge übernommen -- exakt dieselben,
            # die oben in material_total einfliessen (Filter "if unit_price").
            # Sonst würde ein Eintrag ohne zugewiesenen Hersteller zwar den
            # Material-Betrag erhöhen, aber ohne sichtbare Position bleiben.
            markup_factor = 1 + cq.material_markup_percent / 100
            cq.items.clear()
            pos = 1
            for entry in ml.entries:
                if not entry.unit_price:
                    continue
                base_name = entry.product_name or entry.device_type or "Material"
                if entry.manufacturer or entry.order_number:
                    name = f"{base_name} [{entry.manufacturer} {entry.order_number}]".strip()
                else:
                    name = base_name
                customer_unit_price = round_rappen((entry.unit_price or 0) * markup_factor)
                cq.items.append(QuotationItem(
                    position=pos,
                    manufacturer=entry.manufacturer,
                    order_number=entry.order_number,
                    product_name=name,
                    quantity=entry.quantity,
                    unit="Stk.",
                    unit_price=customer_unit_price,
                    total_price=round_rappen(customer_unit_price * entry.quantity),
                ))
                pos += 1
            cq.material_snapshot = _material_signature(ml)
            self._stale_warning.setText("")
            self._stale_warning.setVisible(False)
            self._refresh_items(cq)

        cq.material_total = material_total
        self._update_result(cq)
        self._refresh_quotes()

    def _get_supplier_name(self, supplier_id: str) -> str:
        if not self._project or not supplier_id:
            return ""
        for s in self._project.suppliers:
            if s.id == supplier_id:
                return s.company_name
        return ""

    def _import_from_awarded_requests(self) -> None:
        """
        Uebernimmt Materialkosten aus allen zugeschlagenen Offertanfragen
        in die aktuell ausgewaehlte Kundenofferte (FA-1625).
        """
        cq = self._get_selected_quote()
        if not cq:
            QMessageBox.information(
                self, "Keine Offerte gewählt",
                "Bitte zuerst eine Offerte auswählen oder anlegen.",
            )
            return
        if not self._project:
            return

        awarded = [
            qr for qr in self._project.quotation_requests
            if qr.status == "Zugeschlagen"
        ]
        if not awarded:
            QMessageBox.information(
                self, "Keine zugeschlagenen Anfragen",
                "Es gibt noch keine Offertanfragen mit Status 'Zugeschlagen'.\n\n"
                "Vorgehen:\n"
                "1. Offertanfragen-Verwaltung öffnen\n"
                "2. Preise des Lieferanten in der Spalte 'Angebotspreis' eintragen\n"
                "3. Schaltfläche 'Zuschlag erteilen…' klicken",
            )
            return

        # Zusammenfassung berechnen
        total = sum(
            it.unit_price * it.quantity
            for qr in awarded
            for it in qr.items
            if it.unit_price
        )
        n_items = sum(len(qr.items) for qr in awarded)
        supplier_names = []
        for qr in awarded:
            name = self._get_supplier_name(qr.supplier_id) or f"({qr.request_number})"
            if name not in supplier_names:
                supplier_names.append(name)

        reply = QMessageBox.question(
            self, "Materialkosten aus Lieferantenofferten übernehmen",
            f"Es werden {len(awarded)} zugeschlagene Offertanfrage(n) übernommen:\n\n"
            f"  Lieferanten: {', '.join(supplier_names)}\n"
            f"  Positionen gesamt: {n_items}\n"
            f"  Materialwert (Einkauf): CHF {total:,.2f}\n\n"
            "Sollen auch die Einzelpositionen übernommen werden?\n"
            "(Bestehende Positionen in der Offerte werden ersetzt.)",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        )
        if reply == QMessageBox.Cancel:
            return

        cq.material_total = total
        self._material_total.setValue(total)
        # Aktuellen Aufschlagssatz übernehmen, bevor er auf die Positionspreise
        # angewendet wird (Spinbox kann noch nicht via "Berechnen" gespeichert sein).
        cq.material_markup_percent = self._material_markup.value()

        if reply == QMessageBox.Yes:
            # Positionen zeigen dem Kunden den Endpreis inkl. Zuschlag, nicht
            # den Einkaufspreis des Lieferanten (auf 5 Rappen gerundet).
            markup_factor = 1 + cq.material_markup_percent / 100
            cq.items.clear()
            pos = 1
            for qr in awarded:
                supplier_name = self._get_supplier_name(qr.supplier_id)
                for item in qr.items:
                    customer_unit_price = round_rappen((item.unit_price or 0) * markup_factor)
                    cq.items.append(QuotationItem(
                        position=pos,
                        manufacturer=item.manufacturer,
                        order_number=item.order_number,
                        product_name=item.product_name,
                        quantity=item.quantity,
                        unit=item.unit,
                        unit_price=customer_unit_price,
                        total_price=round_rappen(customer_unit_price * item.quantity),
                        notes=f"Lieferant: {supplier_name}" if supplier_name else "",
                    ))
                    pos += 1
            self._refresh_items(cq)

        self._update_result(cq)
        self._refresh_quotes()

    def _count_programmable_devices(self) -> int:
        """Zählt Busgeräte, die programmiert/in Betrieb genommen werden müssen
        (Aktoren, Sensoren, Gateways) – Koppler und Spannungsversorgungen
        werden nicht mitgezählt, da sie kaum Projektierungsaufwand verursachen."""
        if not self._project:
            return 0
        count = 0
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type not in ("coupler", "power_supply"):
                        count += 1
        return count

    def _estimate_effort(self) -> None:
        """Schätzt Programmier-/Inbetriebnahmestunden aus der Geräteanzahl (FA-1707).

        Basiert auf editierbaren Min./Gerät-Richtwerten aus dem Firmenprofil
        (Startwerte angelehnt an die ZVEH-Kalkulationshilfe KFE). Die Montage
        wird bewusst nicht geschätzt, da der Einbauaufwand je nach Gerätetyp
        und Einbausituation zu stark streut, um mit einem einzelnen Faktor
        sinnvoll abgebildet zu werden.
        """
        cq = self._get_selected_quote()
        if not cq:
            QMessageBox.information(
                self, "Keine Offerte gewählt",
                "Bitte zuerst eine Offerte auswählen oder anlegen.",
            )
            return
        if not self._project:
            return

        device_count = self._count_programmable_devices()
        if device_count == 0:
            QMessageBox.information(
                self, "Keine Geräte gefunden",
                "In der Projekttopologie sind noch keine Busgeräte vorhanden.\n"
                "Bitte zuerst die Topologie berechnen (Schritt 7).",
            )
            return

        from ...services.project_service import ProjectService
        profile = ProjectService().load_company_profile()

        programming_hours = round(
            device_count * profile.minutes_programming_per_device / 60, 1
        )
        commissioning_hours = round(
            profile.commissioning_base_hours
            + device_count * profile.minutes_commissioning_per_device / 60, 1
        )
        documentation_hours = round(
            profile.documentation_base_hours
            + device_count * profile.minutes_documentation_per_device / 60, 1
        )

        reply = QMessageBox.question(
            self, "Aufwand automatisch schätzen",
            f"Basis: {device_count} Busgeräte (Aktoren, Sensoren, Gateways) "
            f"aus der Topologie.\n\n"
            f"Programmierung: {device_count} × "
            f"{profile.minutes_programming_per_device:.0f} Min. "
            f"= {programming_hours:.1f} h\n"
            f"Inbetriebnahme: {profile.commissioning_base_hours:.1f} h Sockel + "
            f"{device_count} × {profile.minutes_commissioning_per_device:.0f} Min. "
            f"= {commissioning_hours:.1f} h\n"
            f"Dokumentation: {profile.documentation_base_hours:.1f} h Sockel + "
            f"{device_count} × {profile.minutes_documentation_per_device:.0f} Min. "
            f"= {documentation_hours:.1f} h\n\n"
            "Dies sind Richtwerte (Faktoren unter Einstellungen → Stundensätze "
            "editierbar) – bitte prüfen und bei Bedarf anpassen.\n\n"
            "Bestehende Werte für Programmierung, Inbetriebnahme und "
            "Dokumentation werden ersetzt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._hours_programming.setValue(programming_hours)
        self._hours_commissioning.setValue(commissioning_hours)
        self._hours_documentation.setValue(documentation_hours)
        self._calculate()

    def _export_quote_excel(self) -> None:
        """Exportiert die ausgewählte Offerte als .xlsx (FA-1713)."""
        cq = self._get_selected_quote()
        if not cq:
            QMessageBox.information(
                self, "Keine Offerte gewählt",
                "Bitte zuerst eine Offerte auswählen.",
            )
            return

        project_name = self._project.name if self._project else "KNX-Projekt"
        default_name = (
            f"Offerte_{cq.quote_number}_{cq.revision}_{project_name}.xlsx"
            .replace(" ", "_").replace("/", "-")
        )

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Offerte exportieren",
            default_name,
            "Excel-Datei (*.xlsx)",
        )
        if not filepath:
            return

        try:
            self._write_quote_xlsx(cq, project_name, filepath)
            QMessageBox.information(
                self, "Export erfolgreich",
                f"Offerte wurde exportiert:\n{filepath}",
            )
        except ImportError as exc:
            QMessageBox.warning(self, "openpyxl fehlt", str(exc))
        except Exception as exc:
            QMessageBox.critical(
                self, "Export fehlgeschlagen", f"Fehler beim Export:\n{exc}"
            )

    def _write_quote_xlsx(self, cq: CustomerQuote,
                          project_name: str, filepath: str) -> None:
        """Erstellt die Offert-Excel-Datei."""
        from ...utils.excel_generator import ExcelGenerator

        company = ""
        if self._project and hasattr(self._project, "project_info"):
            company = getattr(self._project.project_info, "company_name", "")

        gen = ExcelGenerator(
            title=f"Kundenofferte {cq.quote_number} Rev. {cq.revision}",
            company=company,
            project_name=project_name,
        )

        # ── Blatt 1: Deckblatt / Offert-Kopf ──
        gen.add_header()
        gen.add_empty_row()
        gen.add_heading("Offert-Details", level=2)
        gen.add_table(
            headers=["Feld", "Wert"],
            rows=[
                ["Offert-Nr.", cq.quote_number],
                ["Revision", cq.revision],
                ["Datum", cq.date_created],
                ["Status", cq.status],
                ["Kunde", cq.customer_name],
                ["Adresse", cq.customer_address],
                ["Gültigkeit", f"{cq.validity_days} Tage"],
                ["Zahlungsbedingungen", cq.payment_terms],
            ],
            col_widths=[24, 40],
        )

        # ── Blatt 2: Positionen ──
        gen.add_sheet("Positionen")
        gen.add_header()
        gen.add_heading("Offert-Positionen", level=1)
        gen.add_empty_row()

        pos_rows = [
            [
                item.position,
                item.product_name,
                item.quantity,
                item.unit,
                f"{item.unit_price:,.2f}" if item.unit_price else "",
                f"{item.total_price:,.2f}" if item.total_price else "",
                item.notes,
            ]
            for item in cq.items
        ]
        gen.add_table(
            headers=["Pos.", "Produkt / Leistung", "Menge", "Einheit",
                     "Einzelpreis (CHF)", "Gesamtpreis (CHF)", "Bemerkung"],
            rows=pos_rows,
            col_widths=[6, 50, 8, 10, 18, 18, 30],
        )

        # ── Blatt 3: Kalkulation ──
        gen.add_sheet("Kalkulation")
        gen.add_header()
        gen.add_heading("Kalkulations-Ergebnis", level=1)
        gen.add_empty_row()

        calc_rows = [
            ["Material (netto)", f"{round_rappen(cq.material_total):,.2f}"],
            [f"Material-Aufschlag ({cq.material_markup_percent}%)",
             f"{round_rappen(cq.material_with_markup - cq.material_total):,.2f}"],
            ["Material (brutto)", f"{round_rappen(cq.material_with_markup):,.2f}"],
            ["", ""],
            [f"Montage ({cq.labor_mounting_hours}h × CHF {cq.hourly_rate_mounting})",
             f"{round_rappen(cq.labor_mounting_hours * cq.hourly_rate_mounting):,.2f}"],
            [f"Programmierung ({cq.labor_programming_hours}h × CHF {cq.hourly_rate_programming})",
             f"{round_rappen(cq.labor_programming_hours * cq.hourly_rate_programming):,.2f}"],
            [f"Inbetriebnahme ({cq.labor_commissioning_hours}h × CHF {cq.hourly_rate_commissioning})",
             f"{round_rappen(cq.labor_commissioning_hours * cq.hourly_rate_commissioning):,.2f}"],
            [f"Dokumentation ({cq.labor_documentation_hours}h × CHF {cq.hourly_rate_documentation})",
             f"{round_rappen(cq.labor_documentation_hours * cq.hourly_rate_documentation):,.2f}"],
            ["Arbeitszeit total", f"{round_rappen(cq.labor_total):,.2f}"],
            ["", ""],
            ["Nebenkosten", f"{round_rappen(cq.overhead_costs):,.2f}"],
            ["Zwischensumme", f"{round_rappen(cq.subtotal):,.2f}"],
            [f"Rabatt ({cq.discount_percent}%)", f"-{round_rappen(cq.discount_amount):,.2f}"],
            ["Nettobetrag", f"{round_rappen(cq.net_total):,.2f}"],
            [f"MwSt. ({cq.vat_percent}%)", f"{round_rappen(cq.vat_amount):,.2f}"],
            ["GESAMTBETRAG (CHF)", f"{round_rappen(cq.grand_total):,.2f}"],
        ]
        gen.add_table(
            headers=["Position", "Betrag (CHF)"],
            rows=calc_rows,
            col_widths=[50, 20],
        )

        if not filepath.endswith(".xlsx"):
            filepath += ".xlsx"
        gen.save(filepath)

    # ── Brief-Export (PDF) ──

    def _create_letter(self) -> None:
        """Exportiert die ausgewaehlte Offerte als professionellen PDF-Brief."""
        cq = self._get_selected_quote()
        if not cq:
            QMessageBox.information(
                self, "Keine Offerte gewählt",
                "Bitte zuerst eine Offerte auswählen.",
            )
            return

        project_name = self._project.name if self._project else "KNX-Projekt"
        default_name = (
            f"Brief_Offerte_{cq.quote_number}_{cq.revision}_{project_name}.pdf"
            .replace(" ", "_").replace("/", "-")
        )

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Offert-Brief exportieren",
            default_name,
            "PDF-Datei (*.pdf)",
        )
        if not filepath:
            return

        try:
            self._write_quote_letter_pdf(cq, project_name, filepath)
            QMessageBox.information(
                self, "Brief erstellt",
                f"Offert-Brief wurde exportiert:\n{filepath}",
            )
        except ImportError:
            QMessageBox.warning(
                self, "PyMuPDF fehlt",
                "Für die PDF-Erstellung wird PyMuPDF (fitz) benötigt.\n"
                "Bitte mit 'pip install pymupdf' installieren.",
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Fehler", f"Brief konnte nicht erstellt werden:\n{exc}"
            )

    def _write_quote_letter_pdf(
        self, cq: "CustomerQuote", project_name: str, filepath: str
    ) -> None:
        """Erzeugt einen professionellen Offert-Brief als A4-PDF via PyMuPDF."""
        from ...services.quote_letter_service import write_quote_letter_pdf
        write_quote_letter_pdf(self._project, cq, project_name, filepath)
