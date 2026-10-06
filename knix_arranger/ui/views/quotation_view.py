"""
Offertanfragen-Verwaltung (FA-1601 bis FA-1625)
"""
from __future__ import annotations
import os
import tempfile
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QSpinBox,
    QLineEdit, QGroupBox, QFormLayout, QAbstractItemView,
    QMessageBox, QDoubleSpinBox, QTabWidget, QTextEdit, QFileDialog, QDialog,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from ...models.project import KnxProject
from ...models.quotation import Supplier, QuotationRequest, QuotationItem
from ...services.quotation_compare import chf
from ..column_utils import fit_columns

# Spalten der Positionstabelle (Offerte des Lieferanten, FA-1622)
_COL_PRICE    = 5
_COL_DISCOUNT = 6
_COL_TOTAL    = 7
_COL_DELIVERY = 8
_COL_NOTES    = 9
_ITEM_COLS    = 10

_CHEAPEST_BG = "#C8E6C9"


class _ComparisonDialog(QDialog):
    """Preisvergleich der Offerten (FA-1623) mit PDF-Export (FA-1624)."""

    def __init__(self, project, comparison, company_profile_fn, parent=None):
        super().__init__(parent)
        self._project = project
        self._comparison = comparison
        self._company_profile_fn = company_profile_fn
        self.setWindowTitle("Preisvergleich")
        self.setMinimumSize(860, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Nettobeträge je Position in CHF (Einzelpreis abzüglich Rabatt, mal Menge). "
            "Grün: günstigster Anbieter je Position und gesamt."))

        n = len(comparison.suppliers)
        table = QTableWidget(len(comparison.rows) + 1, 2 + n)
        table.setHorizontalHeaderLabels(["Position", "Menge"] + comparison.suppliers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        right = Qt.AlignRight | Qt.AlignVCenter
        for r, row in enumerate(comparison.rows):
            table.setItem(r, 0, QTableWidgetItem(row.label))
            qty = QTableWidgetItem(str(row.quantity))
            qty.setTextAlignment(right)
            table.setItem(r, 1, qty)
            for i, value in enumerate(row.totals):
                cell = QTableWidgetItem(chf(value))
                cell.setTextAlignment(right)
                if row.delivery[i]:
                    cell.setToolTip(f"Lieferfrist: {row.delivery[i]}")
                if row.cheapest == i:
                    cell.setBackground(QBrush(QColor(_CHEAPEST_BG)))
                table.setItem(r, 2 + i, cell)
        last = len(comparison.rows)
        total_label = QTableWidgetItem("Total")
        font = total_label.font()
        font.setBold(True)
        total_label.setFont(font)
        table.setItem(last, 0, total_label)
        for i, total in enumerate(comparison.totals):
            text = chf(total)
            if comparison.missing[i]:
                text += f"  ({comparison.missing[i]} ohne Preis)"
            cell = QTableWidgetItem(text)
            cell.setFont(font)
            cell.setTextAlignment(right)
            if comparison.cheapest_total == i:
                cell.setBackground(QBrush(QColor(_CHEAPEST_BG)))
            table.setItem(last, 2 + i, cell)
        fit_columns(table)
        layout.addWidget(table)

        buttons = QHBoxLayout()
        buttons.addStretch()
        pdf_btn = QPushButton("Als PDF…")
        pdf_btn.clicked.connect(self._export_pdf)
        buttons.addWidget(pdf_btn)
        close_btn = QPushButton("Schliessen")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _export_pdf(self) -> None:
        from ...services.quotation_compare import write_comparison_pdf
        folder = self._project.folder_path if self._project else None
        start = os.path.join(folder, "Berichte", "Offertanfragen") if folder else ""
        if start:
            os.makedirs(start, exist_ok=True)
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Preisvergleich als PDF speichern",
            os.path.join(start, f"Preisvergleich_{self._project.name}.pdf".replace(" ", "_")),
            "PDF-Datei (*.pdf)")
        if not filepath:
            return
        try:
            write_comparison_pdf(self._project, self._comparison,
                                 self._company_profile_fn(), filepath)
            os.startfile(filepath)
        except Exception as exc:
            QMessageBox.critical(self, "Export fehlgeschlagen", f"Fehler beim Export:\n{exc}")


class QuotationView(QWidget):
    """Offertanfragen-Verwaltung: Lieferanten, Anfragen, Positionen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None

        layout = QVBoxLayout(self)

        title = QLabel("Offertanfragen und Beschaffung")
        title.setObjectName("title")
        layout.addWidget(title)

        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        # Tabs: Lieferanten | Offertanfragen
        self._tabs = QTabWidget()
        self._tabs.addTab(self._create_suppliers_tab(), "Lieferanten")
        self._tabs.addTab(self._create_requests_tab(), "Offertanfragen")
        layout.addWidget(self._tabs)

    # ── Lieferanten-Tab ──

    def _create_suppliers_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        content = QHBoxLayout()

        # Tabelle
        left = QVBoxLayout()
        self._supplier_table = QTableWidget()
        self._supplier_table.setColumnCount(5)
        self._supplier_table.setHorizontalHeaderLabels([
            "Firma", "Kontakt", "E-Mail", "Telefon", "Kategorie",
        ])
        self._supplier_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._supplier_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._supplier_table.horizontalHeader().setStretchLastSection(True)
        self._supplier_table.setAlternatingRowColors(True)
        self._supplier_table.currentCellChanged.connect(self._on_supplier_selected)
        left.addWidget(self._supplier_table)

        btn_layout = QHBoxLayout()
        self._btn_add_supplier = QPushButton("+ Neuer Lieferant")
        self._btn_add_supplier.clicked.connect(self._add_supplier)
        self._btn_remove_supplier = QPushButton("Entfernen")
        self._btn_remove_supplier.setObjectName("danger")
        self._btn_remove_supplier.clicked.connect(self._remove_supplier)
        btn_layout.addWidget(self._btn_add_supplier)
        btn_layout.addWidget(self._btn_remove_supplier)
        btn_layout.addStretch()
        left.addLayout(btn_layout)

        content.addLayout(left, 2)

        # Detail-Panel
        right = QVBoxLayout()
        self._supplier_group = QGroupBox("Lieferanten-Details")
        form = QFormLayout()

        self._sup_company = QLineEdit()
        form.addRow("Firma:", self._sup_company)

        self._sup_contact = QLineEdit()
        form.addRow("Kontakt:", self._sup_contact)

        self._sup_email = QLineEdit()
        form.addRow("E-Mail:", self._sup_email)

        self._sup_phone = QLineEdit()
        form.addRow("Telefon:", self._sup_phone)

        self._sup_address = QLineEdit()
        form.addRow("Adresse:", self._sup_address)

        self._sup_website = QLineEdit()
        form.addRow("Website:", self._sup_website)

        self._sup_customer_nr = QLineEdit()
        form.addRow("Kundennr.:", self._sup_customer_nr)

        self._sup_category = QComboBox()
        self._sup_category.addItems([
            "Hersteller", "Großhändler", "Fachhandel", "Online-Shop",
        ])
        form.addRow("Kategorie:", self._sup_category)

        self._sup_brands = QLineEdit()
        self._sup_brands.setPlaceholderText("z.B. ABB, MDT, Theben")
        form.addRow("Marken:", self._sup_brands)

        self._sup_notes = QLineEdit()
        form.addRow("Notizen:", self._sup_notes)

        self._btn_apply_supplier = QPushButton("Übernehmen")
        self._btn_apply_supplier.clicked.connect(self._apply_supplier)
        form.addRow("", self._btn_apply_supplier)

        self._supplier_group.setLayout(form)
        right.addWidget(self._supplier_group)
        right.addStretch()
        content.addLayout(right, 1)

        layout.addLayout(content)
        return widget

    # ── Offertanfragen-Tab ──

    def _create_requests_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        content = QHBoxLayout()

        # Anfragen-Tabelle
        left = QVBoxLayout()
        self._request_table = QTableWidget()
        self._request_table.setColumnCount(6)
        self._request_table.setHorizontalHeaderLabels([
            "Nr.", "Lieferant", "Datum", "Status", "Positionen", "Sammelanfrage",
        ])
        self._request_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._request_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._request_table.horizontalHeader().setStretchLastSection(True)
        self._request_table.setAlternatingRowColors(True)
        self._request_table.currentCellChanged.connect(self._on_request_selected)
        left.addWidget(self._request_table)

        btn_layout = QHBoxLayout()
        self._btn_add_request = QPushButton("+ Neue Anfrage")
        self._btn_add_request.clicked.connect(self._add_request)
        self._btn_remove_request = QPushButton("Entfernen")
        self._btn_remove_request.setObjectName("danger")
        self._btn_remove_request.clicked.connect(self._remove_request)
        self._btn_generate_requests = QPushButton("Aus Materialliste generieren…")
        self._btn_generate_requests.setToolTip(
            "Offertanfragen automatisch aus der Materialliste erzeugen –\n"
            "eine Anfrage pro Hersteller"
        )
        self._btn_generate_requests.clicked.connect(self._generate_from_material_list)
        self._btn_export_request = QPushButton("Als Excel exportieren…")
        self._btn_export_request.setToolTip(
            "Ausgewählte Offertanfrage als .xlsx exportieren"
        )
        self._btn_export_request.clicked.connect(self._export_request_excel)
        btn_layout.addWidget(self._btn_add_request)
        btn_layout.addWidget(self._btn_remove_request)
        btn_layout.addWidget(self._btn_generate_requests)
        btn_layout.addWidget(self._btn_export_request)
        self._btn_pdf_request = QPushButton("Als PDF…")
        self._btn_pdf_request.setToolTip("Ausgewählte Offertanfrage als PDF speichern")
        self._btn_pdf_request.clicked.connect(self._export_request_pdf)
        btn_layout.addWidget(self._btn_pdf_request)
        self._btn_mail_request = QPushButton("Per E-Mail…")
        self._btn_mail_request.setToolTip(
            "E-Mail-Entwurf an den Lieferanten mit der Offertanfrage als PDF-Anhang\n"
            "im Standard-Mailprogramm öffnen")
        self._btn_mail_request.clicked.connect(self._email_request)
        btn_layout.addWidget(self._btn_mail_request)
        btn_layout.addStretch()
        left.addLayout(btn_layout)

        content.addLayout(left, 2)

        # Detail-Panel
        right = QVBoxLayout()

        # Anfrage-Details
        self._request_group = QGroupBox("Anfrage-Details")
        req_form = QFormLayout()

        self._req_number = QLineEdit()
        self._req_number.setReadOnly(True)
        req_form.addRow("Anfrage-Nr.:", self._req_number)

        self._req_supplier = QComboBox()
        req_form.addRow("Lieferant:", self._req_supplier)

        self._req_date = QLineEdit()
        self._req_date.setReadOnly(True)
        req_form.addRow("Erstellt:", self._req_date)

        self._req_delivery = QLineEdit()
        self._req_delivery.setPlaceholderText("TT.MM.JJJJ")
        req_form.addRow("Lieferdatum:", self._req_delivery)

        self._req_status = QComboBox()
        self._req_status.addItems([
            "Entwurf", "Versendet", "Erhalten", "Zugeschlagen", "Abgelehnt",
        ])
        req_form.addRow("Status:", self._req_status)

        self._btn_apply_request = QPushButton("Übernehmen")
        self._btn_apply_request.clicked.connect(self._apply_request)
        req_form.addRow("", self._btn_apply_request)

        self._request_group.setLayout(req_form)
        right.addWidget(self._request_group)
        right.addStretch()

        content.addLayout(right, 1)

        # Obere Hälfte: Anfragenliste + Detailformular (fixe Höhe)
        layout.addLayout(content, 0)

        # Untere Hälfte: Positionstabelle über volle Breite
        self._items_group = QGroupBox("Positionen")
        items_layout = QVBoxLayout()

        self._items_table = QTableWidget()
        self._items_table.setColumnCount(_ITEM_COLS)
        self._items_table.setHorizontalHeaderLabels([
            "Pos.", "Hersteller", "Best.-Nr.", "Produkt", "Menge",
            "Einzelpreis (CHF)", "Rabatt %", "Netto gesamt", "Lieferfrist",
            "Bemerkung Lieferant",
        ])
        self._items_table.setToolTip(
            "Offerte des Lieferanten erfassen (FA-1622): Einzelpreis, Rabatt, "
            "Lieferfrist und Bemerkung per Doppelklick.")
        self._items_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self._items_table.horizontalHeader().setStretchLastSection(True)
        self._items_table.itemChanged.connect(self._on_item_changed)
        items_layout.addWidget(self._items_table)

        # Werkzeugleiste unterhalb der Tabelle
        bottom_layout = QHBoxLayout()

        # Position hinzufügen
        self._item_manufacturer = QLineEdit()
        self._item_manufacturer.setPlaceholderText("Hersteller")
        bottom_layout.addWidget(self._item_manufacturer)

        self._item_order_nr = QLineEdit()
        self._item_order_nr.setPlaceholderText("Best.-Nr.")
        bottom_layout.addWidget(self._item_order_nr)

        self._item_product = QLineEdit()
        self._item_product.setPlaceholderText("Produkt")
        bottom_layout.addWidget(self._item_product, 2)

        self._item_qty = QSpinBox()
        self._item_qty.setRange(1, 999)
        bottom_layout.addWidget(self._item_qty)

        # Padding-Override: siehe customer_quote_view.py.
        self._btn_add_item = QPushButton("+")
        self._btn_add_item.setFixedWidth(30)
        self._btn_add_item.setStyleSheet("padding: 2px;")
        self._btn_add_item.clicked.connect(self._add_item)
        bottom_layout.addWidget(self._btn_add_item)

        self._btn_remove_item = QPushButton("-")
        self._btn_remove_item.setFixedWidth(30)
        self._btn_remove_item.setObjectName("danger")
        self._btn_remove_item.setStyleSheet("padding: 2px;")
        self._btn_remove_item.clicked.connect(self._remove_item)
        bottom_layout.addWidget(self._btn_remove_item)

        bottom_layout.addStretch()

        self._btn_more_suppliers = QPushButton("An weitere Lieferanten…")
        self._btn_more_suppliers.setToolTip(
            "Sammelanfrage: dieselben Positionen zusätzlich bei weiteren\n"
            "Lieferanten anfragen, für den Preisvergleich (FA-1615)")
        self._btn_more_suppliers.clicked.connect(self._send_to_more_suppliers)
        bottom_layout.addWidget(self._btn_more_suppliers)

        self._btn_compare = QPushButton("Preisvergleich…")
        self._btn_compare.setToolTip(
            "Offerten der Sammelanfrage nebeneinander, günstigster Anbieter je\n"
            "Position und gesamt hervorgehoben; als PDF speicherbar (FA-1623, FA-1624)")
        self._btn_compare.clicked.connect(self._show_comparison)
        bottom_layout.addWidget(self._btn_compare)

        self._btn_award = QPushButton("Zuschlag erteilen…")
        self._btn_award.setToolTip(
            "Setzt den Status auf 'Zugeschlagen' und schreibt die\n"
            "eingetragenen Preise in die Materialliste zurück."
        )
        self._btn_award.clicked.connect(self._award_contract)
        bottom_layout.addWidget(self._btn_award)

        items_layout.addLayout(bottom_layout)
        self._items_group.setLayout(items_layout)
        layout.addWidget(self._items_group, 1)

        return widget

    # ── Public ──

    def set_project(self, project: KnxProject):
        self._project = project
        self._refresh_suppliers()
        self._refresh_requests()
        self._update_supplier_combos()

    # ── Lieferanten-Logik ──

    def _refresh_suppliers(self):
        if not self._project:
            self._supplier_table.setRowCount(0)
            return

        suppliers = self._project.suppliers
        self._supplier_table.setRowCount(len(suppliers))
        for i, s in enumerate(suppliers):
            self._supplier_table.setItem(i, 0, QTableWidgetItem(s.company_name))
            self._supplier_table.setItem(i, 1, QTableWidgetItem(s.contact_person))
            self._supplier_table.setItem(i, 2, QTableWidgetItem(s.email))
            self._supplier_table.setItem(i, 3, QTableWidgetItem(s.phone))
            self._supplier_table.setItem(i, 4, QTableWidgetItem(s.category))
        fit_columns(self._supplier_table)
        self._info.setText(
            f"{len(suppliers)} Lieferanten, "
            f"{len(self._project.quotation_requests)} Offertanfragen"
        )

    def _on_supplier_selected(self, row, col, prev_row, prev_col):
        if not self._project or row < 0 or row >= len(self._project.suppliers):
            return
        s = self._project.suppliers[row]
        self._sup_company.setText(s.company_name)
        self._sup_contact.setText(s.contact_person)
        self._sup_email.setText(s.email)
        self._sup_phone.setText(s.phone)
        self._sup_address.setText(s.address)
        self._sup_website.setText(s.website)
        self._sup_customer_nr.setText(s.customer_number)
        idx = self._sup_category.findText(s.category)
        if idx >= 0:
            self._sup_category.setCurrentIndex(idx)
        self._sup_brands.setText(", ".join(s.brands))
        self._sup_notes.setText(s.notes)

    def _add_supplier(self):
        if not self._project:
            return
        s = Supplier(company_name=f"Neuer Lieferant {len(self._project.suppliers) + 1}")
        self._project.suppliers.append(s)
        self._refresh_suppliers()
        self._update_supplier_combos()
        self._supplier_table.selectRow(len(self._project.suppliers) - 1)

    def _remove_supplier(self):
        if not self._project:
            return
        row = self._supplier_table.currentRow()
        if row < 0 or row >= len(self._project.suppliers):
            return
        s = self._project.suppliers[row]
        reply = QMessageBox.question(
            self, "Lieferant entfernen",
            f"Lieferant '{s.company_name}' wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._project.suppliers.pop(row)
            self._refresh_suppliers()
            self._update_supplier_combos()

    def _apply_supplier(self):
        if not self._project:
            return
        row = self._supplier_table.currentRow()
        if row < 0 or row >= len(self._project.suppliers):
            return
        s = self._project.suppliers[row]
        s.company_name = self._sup_company.text()
        s.contact_person = self._sup_contact.text()
        s.email = self._sup_email.text()
        s.phone = self._sup_phone.text()
        s.address = self._sup_address.text()
        s.website = self._sup_website.text()
        s.customer_number = self._sup_customer_nr.text()
        s.category = self._sup_category.currentText()
        s.brands = [b.strip() for b in self._sup_brands.text().split(",") if b.strip()]
        s.notes = self._sup_notes.text()
        self._refresh_suppliers()
        self._update_supplier_combos()

    # ── Offertanfragen-Logik ──

    def _update_supplier_combos(self):
        self._req_supplier.clear()
        self._req_supplier.addItem("-- Lieferant wählen --", "")
        if self._project:
            for s in self._project.suppliers:
                self._req_supplier.addItem(s.company_name, s.id)

    def _refresh_requests(self):
        if not self._project:
            self._request_table.setRowCount(0)
            return

        requests = self._project.quotation_requests
        # Sammelanfrage: erste Anfrage der Gruppe als Bezeichnung
        group_label = {}
        for qr in requests:
            if qr.group_id and qr.group_id not in group_label:
                group_label[qr.group_id] = qr.request_number
        self._request_table.setRowCount(len(requests))
        for i, qr in enumerate(requests):
            supplier_name = self._get_supplier_name(qr.supplier_id)
            status = qr.status + (f" ({qr.date_sent})" if qr.status == "Versendet"
                                  and qr.date_sent else "")
            self._request_table.setItem(i, 0, QTableWidgetItem(qr.request_number))
            self._request_table.setItem(i, 1, QTableWidgetItem(supplier_name))
            self._request_table.setItem(i, 2, QTableWidgetItem(qr.date_created))
            self._request_table.setItem(i, 3, QTableWidgetItem(status))
            self._request_table.setItem(i, 4, QTableWidgetItem(str(len(qr.items))))
            self._request_table.setItem(i, 5, QTableWidgetItem(
                group_label.get(qr.group_id, "") if qr.group_id else ""))
        fit_columns(self._request_table)

    def _get_supplier_name(self, supplier_id: str) -> str:
        if not self._project:
            return ""
        for s in self._project.suppliers:
            if s.id == supplier_id:
                return s.company_name
        return "(unbekannt)"

    def _on_request_selected(self, row, col, prev_row, prev_col):
        if not self._project or row < 0 or row >= len(self._project.quotation_requests):
            return
        qr = self._project.quotation_requests[row]
        self._req_number.setText(qr.request_number)
        self._req_date.setText(qr.date_created)
        self._req_delivery.setText(qr.delivery_date_requested)

        sup_idx = self._req_supplier.findData(qr.supplier_id)
        if sup_idx >= 0:
            self._req_supplier.setCurrentIndex(sup_idx)

        status_idx = self._req_status.findText(qr.status)
        if status_idx >= 0:
            self._req_status.setCurrentIndex(status_idx)

        self._refresh_items(qr)

    def _refresh_items(self, qr: QuotationRequest):
        self._items_table.blockSignals(True)
        self._items_table.setRowCount(len(qr.items))
        for i, item in enumerate(qr.items):
            def _ro(text: str) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                return it

            self._items_table.setItem(i, 0, _ro(str(item.position)))
            self._items_table.setItem(i, 1, _ro(item.manufacturer))
            self._items_table.setItem(i, 2, _ro(item.order_number))
            self._items_table.setItem(i, 3, _ro(item.product_name))
            self._items_table.setItem(i, 4, _ro(str(item.quantity)))

            # Offerte des Lieferanten: editierbar (FA-1622)
            price_text = f"{item.unit_price:.2f}" if item.unit_price else ""
            self._items_table.setItem(i, _COL_PRICE, QTableWidgetItem(price_text))
            discount = f"{item.discount_percent:g}" if item.discount_percent else ""
            self._items_table.setItem(i, _COL_DISCOUNT, QTableWidgetItem(discount))
            total = _ro(chf(item.net_unit_price * item.quantity) if item.unit_price else "")
            total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._items_table.setItem(i, _COL_TOTAL, total)
            self._items_table.setItem(i, _COL_DELIVERY, QTableWidgetItem(item.delivery_time))
            self._items_table.setItem(i, _COL_NOTES, QTableWidgetItem(item.notes))

        fit_columns(self._items_table)
        self._items_table.blockSignals(False)

    def _add_request(self):
        if not self._project:
            return
        next_num = len(self._project.quotation_requests) + 1
        qr = QuotationRequest(
            request_number=f"OA-{date.today().year}-{next_num:03d}",
            date_created=date.today().isoformat(),
        )
        self._project.quotation_requests.append(qr)
        self._refresh_requests()
        self._request_table.selectRow(len(self._project.quotation_requests) - 1)

    def _remove_request(self):
        if not self._project:
            return
        row = self._request_table.currentRow()
        if row < 0 or row >= len(self._project.quotation_requests):
            return
        qr = self._project.quotation_requests[row]
        reply = QMessageBox.question(
            self, "Anfrage entfernen",
            f"Offertanfrage '{qr.request_number}' wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._project.quotation_requests.pop(row)
            self._refresh_requests()
            self._items_table.setRowCount(0)

    def _apply_request(self):
        if not self._project:
            return
        row = self._request_table.currentRow()
        if row < 0 or row >= len(self._project.quotation_requests):
            return
        qr = self._project.quotation_requests[row]
        qr.supplier_id = self._req_supplier.currentData() or ""
        qr.delivery_date_requested = self._req_delivery.text()
        qr.status = self._req_status.currentText()
        # Versanddatum festhalten (FA-1621)
        if qr.status == "Versendet" and not qr.date_sent:
            qr.date_sent = date.today().isoformat()
        self._refresh_requests()

    def _get_selected_request(self) -> QuotationRequest | None:
        if not self._project:
            return None
        row = self._request_table.currentRow()
        if row < 0 or row >= len(self._project.quotation_requests):
            return None
        return self._project.quotation_requests[row]

    def _add_item(self):
        qr = self._get_selected_request()
        if not qr:
            return
        manufacturer = self._item_manufacturer.text().strip()
        order_nr = self._item_order_nr.text().strip()
        product = self._item_product.text().strip()
        qty = self._item_qty.value()
        if not product:
            return

        next_pos = len(qr.items) + 1
        qr.items.append(QuotationItem(
            position=next_pos,
            manufacturer=manufacturer,
            order_number=order_nr,
            product_name=product,
            quantity=qty,
        ))
        self._refresh_items(qr)
        self._refresh_requests()

        self._item_manufacturer.clear()
        self._item_order_nr.clear()
        self._item_product.clear()
        self._item_qty.setValue(1)

    def _remove_item(self):
        qr = self._get_selected_request()
        if not qr:
            return
        row = self._items_table.currentRow()
        if 0 <= row < len(qr.items):
            qr.items.pop(row)
            self._refresh_items(qr)
            self._refresh_requests()

    def _on_item_changed(self, table_item) -> None:
        """Speichert editierte Preis- oder Bemerkungsfelder ins Modell zurueck."""
        qr = self._get_selected_request()
        if not qr:
            return
        row = table_item.row()
        col = table_item.column()
        if row < 0 or row >= len(qr.items):
            return

        item = qr.items[row]
        if col in (_COL_PRICE, _COL_DISCOUNT):
            text = table_item.text().replace("'", "").replace(",", ".").replace("%", "").strip()
            try:
                value = float(text) if text else 0.0
                if col == _COL_DISCOUNT and not 0 <= value <= 100:
                    raise ValueError
            except ValueError:
                # Ungültige Eingabe nicht still verwerfen: Anzeige würde sonst
                # vom Modell abweichen (Zelle zeigt den ungültigen Text, das
                # Modell behält den alten Preis, ohne dass der Nutzer das merkt).
                what = "Preis" if col == _COL_PRICE else "Rabatt (0–100 %)"
                QMessageBox.warning(
                    self, f"Ungültiger {what.split(' ')[0]}",
                    f"'{table_item.text()}' ist kein gültiger {what}.\n"
                    "Der vorherige Wert bleibt erhalten."
                )
                old = item.unit_price if col == _COL_PRICE else item.discount_percent
                self._items_table.blockSignals(True)
                table_item.setText(f"{old:.2f}" if col == _COL_PRICE else f"{old:g}")
                self._items_table.blockSignals(False)
                return
            if col == _COL_PRICE:
                item.unit_price = value
            else:
                item.discount_percent = value
            item.update_total()
            # Offerte eingetragen: Anfrage gilt als erhalten (FA-1621)
            if item.unit_price and qr.status in ("Entwurf", "Versendet"):
                qr.status = "Erhalten"
            # Neu aufbauen erst nach diesem Signal -- die sendende Zelle würde
            # sonst mitten im Aufruf gelöscht
            QTimer.singleShot(0, lambda: self._after_offer_changed(qr))
        elif col == _COL_DELIVERY:
            item.delivery_time = table_item.text().strip()
        elif col == _COL_NOTES:
            item.notes = table_item.text()

    # ── Sammelanfrage und Preisvergleich (FA-1615, FA-1623, FA-1624) ──

    def _send_to_more_suppliers(self) -> None:
        from PySide6.QtWidgets import QDialog, QListWidget, QListWidgetItem, QDialogButtonBox
        from ...services.quotation_compare import send_to_more_suppliers
        qr = self._selected_request_or_hint()
        if not qr:
            return
        candidates = [s for s in self._project.suppliers if s.id != qr.supplier_id]
        if not candidates:
            QMessageBox.information(
                self, "Keine weiteren Lieferanten",
                "Bitte zuerst im Register «Lieferanten» weitere Lieferanten erfassen.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Sammelanfrage")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"Positionen von {qr.request_number} zusätzlich anfragen bei:"))
        listing = QListWidget()
        for s in candidates:
            item = QListWidgetItem(s.company_name or "(ohne Name)")
            item.setData(Qt.UserRole, s.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            listing.addItem(item)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = [listing.item(i).data(Qt.UserRole) for i in range(listing.count())
                  if listing.item(i).checkState() == Qt.Checked]
        created = send_to_more_suppliers(self._project, qr, chosen)
        self._refresh_requests()
        if created:
            QMessageBox.information(
                self, "Sammelanfrage erstellt",
                f"{len(created)} weitere Offertanfrage(n) erstellt: "
                + ", ".join(r.request_number for r in created)
                + ".\nVersand je Anfrage mit «Per E-Mail…» oder «Als PDF…».")

    def _show_comparison(self) -> None:
        from ...services.quotation_compare import build_comparison, comparison_set
        qr = self._selected_request_or_hint()
        if not qr:
            return
        requests = comparison_set(self._project, qr)
        if len(requests) < 2:
            QMessageBox.information(
                self, "Preisvergleich",
                "Für einen Vergleich braucht es mindestens zwei Offerten mit Preisen – "
                "z.B. eine Sammelanfrage («An weitere Lieferanten…») mit erfassten "
                "Offerten.")
            return
        _ComparisonDialog(self._project, build_comparison(self._project, requests),
                          self._company_profile, self).exec()

    def _after_offer_changed(self, qr: QuotationRequest) -> None:
        """Netto gesamt und Status nach einer Preis- oder Rabatteingabe."""
        row = self._request_table.currentRow()
        self._refresh_requests()
        if row >= 0:
            self._request_table.setCurrentCell(row, 0)
        idx = self._req_status.findText(qr.status)
        if idx >= 0:
            self._req_status.setCurrentIndex(idx)
        self._refresh_items(qr)

    def _award_contract(self) -> None:
        """
        Erteilt der ausgewaehlten Offertanfrage den Zuschlag (FA-1625):
        Setzt Status auf 'Zugeschlagen' und schreibt Lieferantenpreise
        in die Materialliste zurueck.
        """
        qr = self._get_selected_request()
        if not qr:
            return

        items_with_price = [it for it in qr.items if it.unit_price > 0]
        if not items_with_price:
            QMessageBox.warning(
                self, "Keine Preise eingetragen",
                "Bitte zuerst die Lieferantenpreise in der Spalte\n"
                "'Angebotspreis' eintragen (Doppelklick auf die Zelle).",
            )
            return

        from ...services.quotation_compare import award
        total = sum(it.net_unit_price * it.quantity for it in items_with_price)
        others = [r for r in self._project.quotation_requests
                  if qr.group_id and r is not qr and r.group_id == qr.group_id]
        reply = QMessageBox.question(
            self, "Zuschlag erteilen",
            f"Offertanfrage '{qr.request_number}' den Zuschlag erteilen?\n\n"
            f"  Positionen mit Preis: {len(items_with_price)}\n"
            f"  Materialwert netto (Einkauf): CHF {chf(total)}\n\n"
            "Die Nettopreise (nach Rabatt) werden in die Materialliste übernommen."
            + (f"\nDie {len(others)} übrigen Anfrage(n) der Sammelanfrage werden "
               "auf «Abgelehnt» gesetzt." if others else ""),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        updated, rejected = award(self._project, qr)
        idx = self._req_status.findText(qr.status)
        if idx >= 0:
            self._req_status.setCurrentIndex(idx)
        self._refresh_requests()
        QMessageBox.information(
            self, "Zuschlag erteilt",
            f"Offertanfrage '{qr.request_number}' wurde auf 'Zugeschlagen' gesetzt.\n"
            f"{updated} Einkaufspreis(e) in die Materialliste übernommen."
            + (f"\n{rejected} Anfrage(n) auf «Abgelehnt» gesetzt." if rejected else ""),
        )

    def _generate_from_material_list(self) -> None:
        """
        Erzeugt automatisch Offertanfragen aus der Materialliste (FA-1611, FA-1615).
        Oeffnet zunaechst einen Dialog, in dem der Benutzer festlegt, welcher
        Lieferant fuer welchen Hersteller angefragt wird. Mehrere Hersteller
        koennen dabei einem einzigen Lieferanten zugewiesen werden.
        """
        if not self._project:
            return

        from collections import defaultdict
        from PySide6.QtWidgets import QDialog
        from ..dialogs.rfq_grouping_dialog import RfqGroupingDialog

        ml = self._project.material_list
        assigned = [e for e in ml.entries if e.manufacturer]
        if not assigned:
            QMessageBox.information(
                self, "Materialliste leer",
                "Es sind noch keine Produkte in der Materialliste zugewiesen.\n"
                "Bitte zuerst in der Materialliste Produkte zuweisen.",
            )
            return

        # Hersteller-Vorkommen zaehlen und Eintraege gruppieren
        manufacturer_counts: dict[str, int] = defaultdict(int)
        by_manufacturer: dict[str, list] = defaultdict(list)
        for entry in assigned:
            manufacturer_counts[entry.manufacturer] += entry.quantity
            by_manufacturer[entry.manufacturer].append(entry)

        # Zuweisungs-Dialog oeffnen
        dlg = RfqGroupingDialog(
            dict(manufacturer_counts),
            self._project.suppliers,
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        grouping = dlg.grouping  # {manufacturer: supplier_id oder ""}

        # Marken-Zuordnung optional in Lieferanten-Stammdaten speichern
        if dlg.save_brands:
            self._persist_brand_assignments(grouping)

        # Eintraege nach Gruppe zusammenfassen
        # group_key = supplier_id (wenn Lieferant) oder "__own__{manufacturer}"
        groups: dict[str, tuple[str, list]] = {}
        for mfr, entries in by_manufacturer.items():
            sup_id = grouping.get(mfr, "")
            group_key = sup_id if sup_id else f"__own__{mfr}"
            if group_key not in groups:
                groups[group_key] = (sup_id, [])
            groups[group_key][1].extend(entries)

        created = 0
        for group_key, (sup_id, entries) in groups.items():
            next_num = len(self._project.quotation_requests) + 1
            qr = QuotationRequest(
                request_number=f"OA-{date.today().year}-{next_num:03d}",
                date_created=date.today().isoformat(),
                supplier_id=sup_id,
            )
            for pos, entry in enumerate(entries, 1):
                qr.items.append(QuotationItem(
                    position=pos,
                    manufacturer=entry.manufacturer,
                    order_number=entry.order_number,
                    product_name=entry.product_name or entry.device_type,
                    quantity=entry.quantity,
                    unit="Stk.",
                ))
            self._project.quotation_requests.append(qr)
            created += 1

        self._refresh_requests()
        if created:
            QMessageBox.information(
                self, "Offertanfragen generiert",
                f"{created} neue Offertanfrage(n) aus der Materialliste erstellt.",
            )
        else:
            QMessageBox.information(
                self, "Keine neuen Anfragen",
                "Für alle gewählten Lieferanten/Hersteller existieren bereits Offertanfragen.",
            )

    def _persist_brand_assignments(self, grouping: dict[str, str]) -> None:
        """Schreibt Hersteller-Zuordnung zurueck in Supplier.brands (FA-1603)."""
        if not self._project:
            return
        for mfr, sup_id in grouping.items():
            if not sup_id:
                continue
            sup = next((s for s in self._project.suppliers if s.id == sup_id), None)
            if sup and mfr not in sup.brands:
                sup.brands.append(mfr)

    # ── PDF und E-Mail (FA-1614 a, c) ──

    def _selected_request_or_hint(self) -> QuotationRequest | None:
        qr = self._get_selected_request()
        if not qr:
            QMessageBox.information(
                self, "Keine Anfrage gewählt",
                "Bitte zuerst eine Offertanfrage auswählen.",
            )
        return qr

    def _supplier(self, supplier_id: str) -> Supplier | None:
        if not self._project:
            return None
        return next((s for s in self._project.suppliers if s.id == supplier_id), None)

    def _requests_folder(self) -> str:
        """Ablage im Projektordner (Berichte/Offertanfragen), sonst Temp-Ordner."""
        folder = self._project.folder_path if self._project else None
        if folder:
            return os.path.join(folder, "Berichte", "Offertanfragen")
        return os.path.join(tempfile.gettempdir(), "KNiX_Offertanfragen")

    @staticmethod
    def _company_profile():
        from ...services.project_service import ProjectService
        try:
            return ProjectService().load_company_profile()
        except Exception:
            return None

    def _export_request_pdf(self) -> None:
        from ...services.quotation_request_service import (
            request_filename, write_request_pdf,
        )
        qr = self._selected_request_or_hint()
        if not qr:
            return
        supplier = self._supplier(qr.supplier_id)
        folder = self._requests_folder()
        os.makedirs(folder, exist_ok=True)
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Offertanfrage als PDF speichern",
            os.path.join(folder, request_filename(qr, supplier, "pdf")),
            "PDF-Datei (*.pdf)",
        )
        if not filepath:
            return
        try:
            write_request_pdf(self._project, qr, supplier, self._company_profile(), filepath)
            os.startfile(filepath)
        except Exception as exc:
            QMessageBox.critical(self, "Export fehlgeschlagen", f"Fehler beim Export:\n{exc}")

    def _email_request(self) -> None:
        from ...services.quotation_request_service import write_request_email
        qr = self._selected_request_or_hint()
        if not qr:
            return
        supplier = self._supplier(qr.supplier_id)
        if not supplier or not supplier.email:
            reply = QMessageBox.question(
                self, "Keine E-Mail-Adresse",
                "Für diesen Lieferanten ist keine E-Mail-Adresse erfasst.\n"
                "Entwurf trotzdem ohne Empfänger erstellen?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        try:
            eml_path = write_request_email(
                self._project, qr, supplier, self._company_profile(), self._requests_folder())
            os.startfile(eml_path)
        except Exception as exc:
            QMessageBox.critical(
                self, "E-Mail nicht erstellt",
                f"Der E-Mail-Entwurf konnte nicht erstellt oder geöffnet werden:\n{exc}\n\n"
                "Die Offertanfrage lässt sich mit «Als PDF…» speichern und von Hand senden.")
            return
        if qr.status == "Entwurf":
            reply = QMessageBox.question(
                self, "Als versendet markieren?",
                "Der E-Mail-Entwurf wurde im Mailprogramm geöffnet.\n"
                "Offertanfrage nach dem Senden als «Versendet» markieren?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                qr.status = "Versendet"
                qr.date_sent = date.today().isoformat()
                self._refresh_requests()

    def _export_request_excel(self) -> None:
        """Exportiert die ausgewählte Offertanfrage als .xlsx (FA-1614)."""
        qr = self._get_selected_request()
        if not qr:
            QMessageBox.information(
                self, "Keine Anfrage gewählt",
                "Bitte zuerst eine Offertanfrage auswählen.",
            )
            return

        supplier_name = self._get_supplier_name(qr.supplier_id)
        project_name = self._project.name if self._project else "KNX-Projekt"
        default_name = (
            f"Offertanfrage_{qr.request_number}_{supplier_name}.xlsx"
            .replace(" ", "_").replace("/", "-")
        )

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Offertanfrage exportieren",
            default_name,
            "Excel-Datei (*.xlsx)",
        )
        if not filepath:
            return

        try:
            self._write_request_xlsx(qr, supplier_name, project_name, filepath)
            QMessageBox.information(
                self, "Export erfolgreich",
                f"Offertanfrage wurde exportiert:\n{filepath}",
            )
        except ImportError as exc:
            QMessageBox.warning(self, "openpyxl fehlt", str(exc))
        except Exception as exc:
            QMessageBox.critical(
                self, "Export fehlgeschlagen", f"Fehler beim Export:\n{exc}"
            )

    def _write_request_xlsx(self, qr: QuotationRequest, supplier_name: str,
                            project_name: str, filepath: str) -> None:
        """Erstellt die Offertanfrage-Excel-Datei."""
        from ...utils.excel_generator import ExcelGenerator

        company = ""
        if self._project and hasattr(self._project, "project_info"):
            company = getattr(self._project.project_info, "company_name", "")

        gen = ExcelGenerator(
            title=f"Offertanfrage {qr.request_number}",
            company=company,
            project_name=project_name,
        )

        # ── Blatt 1: Anfrage-Kopf ──
        gen.add_header()
        gen.add_empty_row()
        gen.add_heading("Anfrage-Details", level=2)
        gen.add_table(
            headers=["Feld", "Wert"],
            rows=[
                ["Anfrage-Nr.", qr.request_number],
                ["Erstellt am", qr.date_created],
                ["Lieferant", supplier_name],
                ["Gewünschter Liefertermin", qr.delivery_date_requested],
                ["Status", qr.status],
                ["Projekt", project_name],
            ],
            col_widths=[28, 40],
        )

        # ── Blatt 2: Positionsliste ──
        gen.add_sheet("Positionen")
        gen.add_header()
        gen.add_heading("Anfrage-Positionen", level=1)
        gen.add_empty_row()

        pos_rows = [
            [
                item.position,
                item.manufacturer,
                item.order_number,
                item.product_name,
                item.quantity,
                item.unit,
                "",   # Angebotspreis (vom Lieferanten auszufüllen)
                "",   # Rabatt %
                "",   # Lieferfrist
                "",   # Bemerkung Lieferant
            ]
            for item in qr.items
        ]
        gen.add_table(
            headers=[
                "Pos.", "Hersteller", "Bestellnummer", "Produktbezeichnung",
                "Menge", "Einheit", "Angebotspreis (CHF)", "Rabatt %",
                "Lieferfrist", "Bemerkung Lieferant",
            ],
            rows=pos_rows,
            col_widths=[6, 18, 18, 40, 8, 10, 22, 10, 14, 30],
        )

        gen.add_empty_row()
        gen.add_paragraph(
            "Bitte füllen Sie die Spalten 'Angebotspreis', 'Rabatt', 'Lieferfrist' "
            "und 'Bemerkung' aus und senden Sie dieses Dokument zurück."
        )

        if not filepath.endswith(".xlsx"):
            filepath += ".xlsx"
        gen.save(filepath)
