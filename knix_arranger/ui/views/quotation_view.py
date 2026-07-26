"""
Offertanfragen-Verwaltung (FA-1601 bis FA-1615)
"""
from __future__ import annotations
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QSpinBox,
    QLineEdit, QGroupBox, QFormLayout, QAbstractItemView,
    QMessageBox, QDoubleSpinBox, QTabWidget, QTextEdit, QFileDialog,
)
from PySide6.QtCore import Qt
from ...models.project import KnxProject
from ...models.quotation import Supplier, QuotationRequest, QuotationItem
from ..column_utils import fit_columns


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
        self._request_table.setColumnCount(5)
        self._request_table.setHorizontalHeaderLabels([
            "Nr.", "Lieferant", "Datum", "Status", "Positionen",
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
            "eine Anfrage pro Hersteller (FA-1611)"
        )
        self._btn_generate_requests.clicked.connect(self._generate_from_material_list)
        self._btn_export_request = QPushButton("Als Excel exportieren…")
        self._btn_export_request.setToolTip(
            "Ausgewählte Offertanfrage als .xlsx exportieren (FA-1614)"
        )
        self._btn_export_request.clicked.connect(self._export_request_excel)
        btn_layout.addWidget(self._btn_add_request)
        btn_layout.addWidget(self._btn_remove_request)
        btn_layout.addWidget(self._btn_generate_requests)
        btn_layout.addWidget(self._btn_export_request)
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
        self._items_table.setColumnCount(7)
        self._items_table.setHorizontalHeaderLabels([
            "Pos.", "Hersteller", "Best.-Nr.", "Produkt", "Menge",
            "Angebotspreis (CHF)", "Bemerkung Lieferant",
        ])
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

        self._btn_add_item = QPushButton("+")
        self._btn_add_item.setFixedWidth(30)
        self._btn_add_item.clicked.connect(self._add_item)
        bottom_layout.addWidget(self._btn_add_item)

        self._btn_remove_item = QPushButton("-")
        self._btn_remove_item.setFixedWidth(30)
        self._btn_remove_item.setObjectName("danger")
        self._btn_remove_item.clicked.connect(self._remove_item)
        bottom_layout.addWidget(self._btn_remove_item)

        bottom_layout.addStretch()

        self._btn_award = QPushButton("Zuschlag erteilen…")
        self._btn_award.setToolTip(
            "Setzt den Status auf 'Zugeschlagen' und schreibt die\n"
            "eingetragenen Preise in die Materialliste zurueck (FA-1625)."
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
        self._request_table.setRowCount(len(requests))
        for i, qr in enumerate(requests):
            supplier_name = self._get_supplier_name(qr.supplier_id)
            self._request_table.setItem(i, 0, QTableWidgetItem(qr.request_number))
            self._request_table.setItem(i, 1, QTableWidgetItem(supplier_name))
            self._request_table.setItem(i, 2, QTableWidgetItem(qr.date_created))
            self._request_table.setItem(i, 3, QTableWidgetItem(qr.status))
            self._request_table.setItem(i, 4, QTableWidgetItem(str(len(qr.items))))
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

            # Angebotspreis: editierbar
            price_text = f"{item.unit_price:,.2f}" if item.unit_price else ""
            self._items_table.setItem(i, 5, QTableWidgetItem(price_text))

            # Bemerkung: editierbar
            self._items_table.setItem(i, 6, QTableWidgetItem(item.notes))

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

        if col == 5:  # Angebotspreis
            text = table_item.text().replace("'", "").replace(",", ".").strip()
            try:
                price = float(text) if text else 0.0
            except ValueError:
                # Ungültige Eingabe nicht still verwerfen: Anzeige würde sonst
                # vom Modell abweichen (Zelle zeigt den ungültigen Text, das
                # Modell behält den alten Preis, ohne dass der Nutzer das merkt).
                QMessageBox.warning(
                    self, "Ungültiger Preis",
                    f"'{table_item.text()}' ist keine gültige Zahl.\n"
                    "Der vorherige Wert bleibt erhalten."
                )
                self._items_table.blockSignals(True)
                table_item.setText(f"{qr.items[row].unit_price:.2f}")
                self._items_table.blockSignals(False)
                return
            qr.items[row].unit_price = price
            qr.items[row].total_price = price * qr.items[row].quantity
        elif col == 6:  # Bemerkung
            qr.items[row].notes = table_item.text()

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

        total = sum(it.unit_price * it.quantity for it in items_with_price)
        reply = QMessageBox.question(
            self, "Zuschlag erteilen",
            f"Offertanfrage '{qr.request_number}' den Zuschlag erteilen?\n\n"
            f"  Positionen mit Preis: {len(items_with_price)}\n"
            f"  Materialwert (Einkauf): CHF {total:,.2f}\n\n"
            "Die eingetragenen Preise werden in die Materialliste uebernommen.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Status setzen
        qr.status = "Zugeschlagen"
        idx = self._req_status.findText("Zugeschlagen")
        if idx >= 0:
            self._req_status.setCurrentIndex(idx)

        # Preise in Materialliste zurueckschreiben (Matching via order_number + manufacturer)
        if self._project:
            for item in qr.items:
                if not item.order_number or not item.unit_price:
                    continue
                for entry in self._project.material_list.entries:
                    if (entry.order_number == item.order_number
                            and entry.manufacturer == item.manufacturer):
                        entry.unit_price = item.unit_price

        self._refresh_requests()
        QMessageBox.information(
            self, "Zuschlag erteilt",
            f"Offertanfrage '{qr.request_number}' wurde auf 'Zugeschlagen' gesetzt.\n"
            f"Einkaufspreise wurden in die Materialliste uebernommen.",
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
                "Fuer alle gewaaehlten Lieferanten/Hersteller existieren bereits Offertanfragen.",
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
                "",   # Bemerkung Lieferant
            ]
            for item in qr.items
        ]
        gen.add_table(
            headers=[
                "Pos.", "Hersteller", "Bestellnummer", "Produktbezeichnung",
                "Menge", "Einheit", "Angebotspreis (CHF)", "Bemerkung Lieferant",
            ],
            rows=pos_rows,
            col_widths=[6, 18, 18, 40, 8, 10, 22, 30],
        )

        gen.add_empty_row()
        gen.add_paragraph(
            "Bitte füllen Sie die Spalten 'Angebotspreis' und 'Bemerkung' aus "
            "und senden Sie dieses Dokument zurück."
        )

        if not filepath.endswith(".xlsx"):
            filepath += ".xlsx"
        gen.save(filepath)
