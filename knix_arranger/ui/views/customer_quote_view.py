"""
Kundenofferte-Verwaltung (FA-1701 bis FA-1715)
"""
from __future__ import annotations
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QSpinBox,
    QLineEdit, QGroupBox, QFormLayout, QAbstractItemView,
    QMessageBox, QDoubleSpinBox, QTabWidget, QFileDialog,
)
from PySide6.QtCore import Qt
from ...models.project import KnxProject
from ...models.quotation import CustomerQuote, QuotationItem
from ...services.material_list_export_service import MaterialListExportService
from ..column_utils import fit_columns


class CustomerQuoteView(QWidget):
    """Kundenofferte: Kalkulation, Positionen, Kostenübersicht."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None

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
        self._quote_table.setColumnCount(6)
        self._quote_table.setHorizontalHeaderLabels([
            "Offert-Nr.", "Rev.", "Datum", "Kunde", "Status", "Total (CHF)",
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
            "Ausgewählte Offerte als .xlsx exportieren (FA-1713)"
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

        self._quote_address = QLineEdit()
        form.addRow("Adresse:", self._quote_address)

        self._quote_status = QComboBox()
        self._quote_status.addItems([
            "Entwurf", "Versendet", "Akzeptiert", "Abgelehnt", "Ueberarbeitung",
        ])
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

        self._btn_add_item = QPushButton("+")
        self._btn_add_item.setFixedWidth(30)
        self._btn_add_item.clicked.connect(self._add_item)
        add_layout.addWidget(self._btn_add_item)

        self._btn_remove_item = QPushButton("-")
        self._btn_remove_item.setFixedWidth(30)
        self._btn_remove_item.setObjectName("danger")
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
            "Materialwert und Positionen aus der Projektmaterialliste übernehmen (FA-2308)"
        )
        self._btn_import_material.clicked.connect(self._import_from_material_list)
        cost_form.addRow("", self._btn_import_material)

        self._btn_import_awarded = QPushButton("Aus Lieferantenofferten übernehmen…")
        self._btn_import_awarded.setToolTip(
            "Materialkosten aus zugeschlagenen Offertanfragen übernehmen (FA-1625).\n"
            "Voraussetzung: Offertanfragen mit Status 'Zugeschlagen' vorhanden."
        )
        self._btn_import_awarded.clicked.connect(self._import_from_awarded_requests)
        cost_form.addRow("", self._btn_import_awarded)

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
        self._grand_total_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
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
        actual_group = QGroupBox("Ist-Werte erfassen (FA-2201)")
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
        compare_group = QGroupBox("Soll/Ist-Vergleich (FA-2202)")
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
            "font-size: 14px; font-weight: bold; padding: 10px;"
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
            f"font-size: 14px; font-weight: bold; padding: 10px; color: {color};"
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
        self._actual_overhead.setValue(cq.actual_overhead_costs)

    # ── Public ──

    def set_project(self, project: KnxProject):
        self._project = project
        self._refresh_quotes()

    # ── Offerten-Logik ──

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
                i, 5, QTableWidgetItem(f"{cq.grand_total:,.2f}")
            )
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
        self._quote_address.setText(cq.customer_address)

        idx = self._quote_status.findText(cq.status)
        if idx >= 0:
            self._quote_status.setCurrentIndex(idx)

        self._quote_validity.setValue(cq.validity_days)
        self._quote_payment.setText(cq.payment_terms)

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
        self._overhead.setValue(cq.overhead_costs)
        self._discount.setValue(cq.discount_percent)
        self._vat.setValue(cq.vat_percent)
        self._update_result(cq)

    def _update_result(self, cq: CustomerQuote):
        rows = [
            ("Material (netto)", f"{cq.material_total:,.2f}"),
            (f"Material-Aufschlag ({cq.material_markup_percent}%)",
             f"{cq.material_with_markup - cq.material_total:,.2f}"),
            ("Material (brutto)", f"{cq.material_with_markup:,.2f}"),
            ("", ""),
            (f"Montage ({cq.labor_mounting_hours}h x CHF {cq.hourly_rate_mounting})",
             f"{cq.labor_mounting_hours * cq.hourly_rate_mounting:,.2f}"),
            (f"Programmierung ({cq.labor_programming_hours}h x CHF {cq.hourly_rate_programming})",
             f"{cq.labor_programming_hours * cq.hourly_rate_programming:,.2f}"),
            (f"Inbetriebnahme ({cq.labor_commissioning_hours}h x CHF {cq.hourly_rate_commissioning})",
             f"{cq.labor_commissioning_hours * cq.hourly_rate_commissioning:,.2f}"),
            ("Arbeitszeit total", f"{cq.labor_total:,.2f}"),
            ("", ""),
            ("Nebenkosten", f"{cq.overhead_costs:,.2f}"),
            ("Zwischensumme", f"{cq.subtotal:,.2f}"),
            (f"Rabatt ({cq.discount_percent}%)", f"-{cq.discount_amount:,.2f}"),
            ("Nettobetrag", f"{cq.net_total:,.2f}"),
            (f"MwSt. ({cq.vat_percent}%)", f"{cq.vat_amount:,.2f}"),
            ("GESAMTBETRAG", f"{cq.grand_total:,.2f}"),
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

        self._grand_total_label.setText(f"Gesamtbetrag: CHF {cq.grand_total:,.2f}")

    def _add_quote(self):
        if not self._project:
            return
        next_num = len(self._project.customer_quotes) + 1
        cq = CustomerQuote(
            quote_number=f"OF-{date.today().year}-{next_num:03d}",
            date_created=date.today().isoformat(),
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
        cq.customer_address = self._quote_address.text()
        cq.status = self._quote_status.currentText()
        cq.validity_days = self._quote_validity.value()
        cq.payment_terms = self._quote_payment.text()
        self._refresh_quotes()

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
            cq.items.clear()
            pos = 1
            for entry in ml.entries:
                if not entry.manufacturer:
                    continue
                name = (
                    f"{entry.product_name or entry.device_type} "
                    f"[{entry.manufacturer} {entry.order_number}]".strip()
                )
                cq.items.append(QuotationItem(
                    position=pos,
                    manufacturer=entry.manufacturer,
                    order_number=entry.order_number,
                    product_name=name,
                    quantity=entry.quantity,
                    unit="Stk.",
                    unit_price=entry.unit_price,
                    total_price=entry.total_price,
                ))
                pos += 1
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
                self, "Keine Offerte gewaehlt",
                "Bitte zuerst eine Offerte auswaehlen oder anlegen.",
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
                "1. Offertanfragen-Verwaltung oeffnen\n"
                "2. Preise des Lieferanten in der Spalte 'Angebotspreis' eintragen\n"
                "3. Schaltflaeche 'Zuschlag erteilen…' klicken",
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
            self, "Materialkosten aus Lieferantenofferten uebernehmen",
            f"Es werden {len(awarded)} zugeschlagene Offertanfrage(n) uebernommen:\n\n"
            f"  Lieferanten: {', '.join(supplier_names)}\n"
            f"  Positionen gesamt: {n_items}\n"
            f"  Materialwert (Einkauf): CHF {total:,.2f}\n\n"
            "Sollen auch die Einzelpositionen uebernommen werden?\n"
            "(Bestehende Positionen in der Offerte werden ersetzt.)",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        )
        if reply == QMessageBox.Cancel:
            return

        cq.material_total = total
        self._material_total.setValue(total)

        if reply == QMessageBox.Yes:
            cq.items.clear()
            pos = 1
            for qr in awarded:
                supplier_name = self._get_supplier_name(qr.supplier_id)
                for item in qr.items:
                    cq.items.append(QuotationItem(
                        position=pos,
                        manufacturer=item.manufacturer,
                        order_number=item.order_number,
                        product_name=item.product_name,
                        quantity=item.quantity,
                        unit=item.unit,
                        unit_price=item.unit_price,
                        total_price=item.unit_price * item.quantity,
                        notes=f"Lieferant: {supplier_name}" if supplier_name else "",
                    ))
                    pos += 1
            self._refresh_items(cq)

        self._update_result(cq)
        self._refresh_quotes()

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
            ["Material (netto)", f"{cq.material_total:,.2f}"],
            [f"Material-Aufschlag ({cq.material_markup_percent}%)",
             f"{cq.material_with_markup - cq.material_total:,.2f}"],
            ["Material (brutto)", f"{cq.material_with_markup:,.2f}"],
            ["", ""],
            [f"Montage ({cq.labor_mounting_hours}h × CHF {cq.hourly_rate_mounting})",
             f"{cq.labor_mounting_hours * cq.hourly_rate_mounting:,.2f}"],
            [f"Programmierung ({cq.labor_programming_hours}h × CHF {cq.hourly_rate_programming})",
             f"{cq.labor_programming_hours * cq.hourly_rate_programming:,.2f}"],
            [f"Inbetriebnahme ({cq.labor_commissioning_hours}h × CHF {cq.hourly_rate_commissioning})",
             f"{cq.labor_commissioning_hours * cq.hourly_rate_commissioning:,.2f}"],
            ["Arbeitszeit total", f"{cq.labor_total:,.2f}"],
            ["", ""],
            ["Nebenkosten", f"{cq.overhead_costs:,.2f}"],
            ["Zwischensumme", f"{cq.subtotal:,.2f}"],
            [f"Rabatt ({cq.discount_percent}%)", f"-{cq.discount_amount:,.2f}"],
            ["Nettobetrag", f"{cq.net_total:,.2f}"],
            [f"MwSt. ({cq.vat_percent}%)", f"{cq.vat_amount:,.2f}"],
            ["GESAMTBETRAG (CHF)", f"{cq.grand_total:,.2f}"],
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
                self, "Keine Offerte gewaehlt",
                "Bitte zuerst eine Offerte auswaehlen.",
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
                "Fuer die PDF-Erstellung wird PyMuPDF (fitz) benoetigt.\n"
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
        import fitz  # PyMuPDF

        # ── Firmendaten ermitteln ──
        company_name = ""
        company_address = ""
        company_phone = ""
        company_email = ""
        user_name = ""
        if self._project and hasattr(self._project, "project_info"):
            pi = self._project.project_info
            company_name = getattr(pi, "company_name", "")
        try:
            from ...services.project_service import ProjectService
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
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        LM = 70       # left margin
        RM = 525      # right margin (595 - 70)
        y = 60        # aktueller y-Cursor
        LINE = 14     # Zeilenhöhe normal
        GRAY_HEADER = (0.22, 0.40, 0.60)   # Blau für Tabellenköpfe (RGB 0..1)
        WHITE = (1.0, 1.0, 1.0)
        BLACK = (0.0, 0.0, 0.0)
        LIGHT_GRAY = (0.93, 0.93, 0.93)

        def text(px, py, txt, size=10, bold=False, color=BLACK, align="left"):
            fname = "hebo" if bold else "helv"
            page.insert_text(
                fitz.Point(px, py), txt,
                fontname=fname, fontsize=size, color=color,
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
                page = doc.new_page(width=595, height=842)
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

        # ── Anrede & Einleitung ──
        text(LM, y, "Sehr geehrte Damen und Herren,", size=10)
        y += LINE + 4
        intro = (
            "gerne unterbreiten wir Ihnen folgende Offerte für die "
            "KNX-Gebäudeautomation des oben genannten Projekts."
        )
        text(LM, y, intro, size=10)
        y += LINE + 12

        # ── Hilfsfunktion: Tabelle zeichnen ──
        def draw_table(cur_y, headers, rows, col_widths, fontsize=9):
            """Zeichnet eine Tabelle und gibt das neue y zurück."""
            row_h = fontsize + 5
            total_w = sum(col_widths)
            xs = [LM]
            for w in col_widths[:-1]:
                xs.append(xs[-1] + w)
            xs.append(LM + total_w)

            # Kopfzeile
            filled_rect(LM, cur_y - row_h + 3, LM + total_w, cur_y + 3, GRAY_HEADER)
            for i, hdr in enumerate(headers):
                text(xs[i] + 3, cur_y, hdr, size=fontsize, bold=True, color=WHITE)
            cur_y += row_h
            hline(cur_y, LM, LM + total_w, width=0.8, color=(0.0, 0.0, 0.0))

            for r_idx, row in enumerate(rows):
                cur_y = new_page_if_needed(cur_y, row_h + 2)
                if r_idx % 2 == 1:
                    filled_rect(LM, cur_y - row_h + 3, LM + total_w, cur_y + 3, LIGHT_GRAY)
                for c_idx, cell in enumerate(row):
                    is_bold = getattr(cell, "_bold", False)
                    cell_str = str(cell)
                    text(xs[c_idx] + 3, cur_y, cell_str, size=fontsize, bold=is_bold)
                cur_y += row_h
            hline(cur_y - row_h + row_h, LM, LM + total_w, width=0.5)
            return cur_y + 4

        # ── Einzelpositionen ──
        text(LM, y, "Offert-Positionen", size=10, bold=True)
        y += LINE + 2
        y = new_page_if_needed(y, 40)

        pos_headers = ["Pos.", "Produkt / Leistung", "Menge", "Einh.", "EP (CHF)", "GP (CHF)"]
        col_pos = [30, 220, 35, 30, 55, 55]
        pos_rows = []
        for item in cq.items:
            ep = f"{item.unit_price:,.2f}" if item.unit_price else "-"
            gp = f"{item.total_price:,.2f}" if item.total_price else "-"
            pos_rows.append([str(item.position), item.product_name or "-",
                              str(item.quantity), item.unit or "Stk.", ep, gp])
        if pos_rows:
            y = draw_table(y, pos_headers, pos_rows, col_pos)
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
            return f"CHF {val:,.2f}"

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
        if cq.overhead_costs:
            cost_rows.append(["Nebenkosten", _chf(cq.overhead_costs)])
        cost_rows.append(["Zwischensumme", _chf(cq.subtotal)])
        if cq.discount_percent:
            cost_rows.append([
                f"Rabatt ({cq.discount_percent:.1f} %)",
                f"- CHF {cq.discount_amount:,.2f}",
            ])
        cost_rows.append(["Nettobetrag", _chf(cq.net_total)])
        cost_rows.append([f"MwSt. {cq.vat_percent:.1f} %", _chf(cq.vat_amount)])
        # Gesamtbetrag als Sonderzeile – wird separat gezeichnet
        bold_rows = {"Zwischensumme", "Nettobetrag"}
        y = draw_table(y, ["Position", "Betrag"], cost_rows, [310, 115])

        # Gesamtbetrag-Box
        y = new_page_if_needed(y, 30)
        filled_rect(LM, y - 14, RM, y + 6, (0.22, 0.40, 0.60))
        text(LM + 4, y, "GESAMTBETRAG (inkl. MwSt.)", size=10, bold=True, color=WHITE)
        text(RM - 118, y, f"CHF {cq.grand_total:,.2f}", size=10, bold=True, color=WHITE)
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

        if not filepath.endswith(".pdf"):
            filepath += ".pdf"
        doc.save(filepath)
        doc.close()
