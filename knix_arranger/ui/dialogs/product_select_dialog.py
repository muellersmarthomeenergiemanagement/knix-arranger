"""
Produkt-Auswahl-Dialog (FA-2303, FA-2304)

Erlaubt die Suche und Auswahl von KNX-Geräten aus dem lokalen Katalog
sowie den Import weiterer Geräte via KNXPROD-Dateien.
"""
from __future__ import annotations
import logging
import os
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QGroupBox, QSpinBox, QFormLayout, QProgressDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from ...services.product_search_service import ProductSearchService, ProductSuggestion
from ...services.knxprod_catalog_service import KnxprodCatalogService
from ...services.recent_products import load_recent, add_recent
from ...models.material_list import MaterialEntry, MATERIAL_CATEGORIES
from ...models.topology import Topology, Line

logger = logging.getLogger("knix_arranger.product_select_dialog")


def _default_products_folder() -> str:
    """Liefert den Standardordner für gesammelte KNXPROD-Dateien
    (<Arbeitsverzeichnis>/Produkte KNX, siehe WorkspaceSetupDialog), falls
    ein Arbeitsverzeichnis konfiguriert ist und der Ordner existiert."""
    from pathlib import Path
    import json
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    settings_path = base / "KNiXArranger" / "app_settings.json"
    if not settings_path.exists():
        return ""
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except Exception:
        return ""
    workspace_root = settings.get("workspace_root_path", "")
    if not workspace_root:
        return ""
    candidate = os.path.join(workspace_root, "Produkte KNX")
    return candidate if os.path.isdir(candidate) else ""

# Mapping: interne catalog-Kategorie → Anzeigename
_CAT_DISPLAY = {
    "actor": "Aktor",
    "sensor": "Sensor",
    "infrastructure": "Infrastruktur",
}
_CAT_FILTER_OPTIONS = ["Alle", "Aktor", "Sensor", "Infrastruktur"]
_CAT_FILTER_MAP = {
    "Alle": "",
    "Aktor": "actor",
    "Sensor": "sensor",
    "Infrastruktur": "infrastructure",
}

# Mapping: catalog-Kategorie + device_type → MaterialEntry.category
_DEVICE_TYPE_TO_ML_CAT = {
    "Linienkoppler": "Linienkoppler",
    "Bereichskoppler": "Bereichskoppler",
    "IP-Router": "IP-Router",
    "Netzteil": "Netzteil",
    "DALI-Gateway": "DALI-Gateway",
}


class ProductSelectDialog(QDialog):
    """
    Dialog zur Produktauswahl aus dem lokalen KNX-Katalog (FA-2303).

    Gibt bei Bestätigung eine fertige ``MaterialEntry``-Instanz zurück,
    die direkt zur Materialliste hinzugefügt werden kann.
    """

    def __init__(
        self,
        preferred_manufacturers: list[str] | None = None,
        initial_category_filter: str = "",   # "actor", "sensor", "infrastructure", ""
        topology: Topology | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Produkt auswählen")
        self.setMinimumSize(820, 560)

        self._search_service = ProductSearchService()
        self._preferred = preferred_manufacturers or []
        self._all_results: list[ProductSuggestion] = []
        self._selected: ProductSuggestion | None = None
        self._topology = topology
        self._selected_line: Line | None = None

        self._build_ui(initial_category_filter)
        self._populate_recent_table()
        self._refresh_results()

    # ------------------------------------------------------------------ UI

    def _build_ui(self, initial_category_filter: str):
        layout = QVBoxLayout(self)

        # --- Zuletzt verwendet ---
        self._recent_group = QGroupBox("Zuletzt verwendet")
        recent_layout = QVBoxLayout()
        self._recent_table = QTableWidget(0, 6)
        self._recent_table.setHorizontalHeaderLabels([
            "Kategorie", "Typ", "Hersteller", "Bestellnummer", "Produktname", "Kanäle",
        ])
        self._recent_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._recent_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._recent_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._recent_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._recent_table.setMaximumHeight(140)
        self._recent_table.doubleClicked.connect(self._on_recent_double_click)
        recent_layout.addWidget(self._recent_table)
        self._recent_group.setLayout(recent_layout)
        self._recent_group.setVisible(False)
        layout.addWidget(self._recent_group)

        # --- Filter-Zeile ---
        filter_group = QGroupBox("Filter")
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Suche:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Produktname, Bestellnummer, Hersteller…")
        self._search_edit.textChanged.connect(self._refresh_results)
        filter_layout.addWidget(self._search_edit, 2)

        filter_layout.addWidget(QLabel("Kategorie:"))
        self._cat_combo = QComboBox()
        self._cat_combo.addItems(_CAT_FILTER_OPTIONS)
        # Vorauswahl setzen
        pre_display = {v: k for k, v in _CAT_FILTER_MAP.items()}.get(
            initial_category_filter, "Alle"
        )
        self._cat_combo.setCurrentText(pre_display)
        self._cat_combo.currentIndexChanged.connect(self._refresh_results)
        filter_layout.addWidget(self._cat_combo)

        filter_layout.addWidget(QLabel("Hersteller:"))
        self._mfr_combo = QComboBox()
        self._mfr_combo.addItem("Alle")
        for m in self._search_service.known_manufacturers():
            self._mfr_combo.addItem(m)
        self._mfr_combo.currentIndexChanged.connect(self._refresh_results)
        filter_layout.addWidget(self._mfr_combo)

        btn_knxprod = QPushButton("KNXPROD importieren…")
        btn_knxprod.setToolTip(
            "Herstellerdatei (.knxprod) importieren und Produkte in den Katalog aufnehmen"
        )
        btn_knxprod.clicked.connect(self._import_knxprod)
        filter_layout.addWidget(btn_knxprod)

        btn_knxprod_folder = QPushButton("Ordner importieren…")
        btn_knxprod_folder.setToolTip(
            "Alle .knxprod-Dateien in einem Ordner (inkl. Unterordner) importieren.\n"
            "Bereits vorhandene Produkte (gleicher Hersteller + Bestellnummer) werden "
            "aktualisiert – so lässt sich der Katalog nach einem Parser-Update auffrischen."
        )
        btn_knxprod_folder.clicked.connect(self._import_knxprod_folder)
        filter_layout.addWidget(btn_knxprod_folder)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # --- Ergebnis-Tabelle ---
        self._result_label = QLabel("0 Produkte gefunden")
        self._result_label.setObjectName("subtitle")
        layout.addWidget(self._result_label)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Kategorie", "Typ", "Hersteller", "Bestellnummer", "Produktname", "Kanäle",
        ])
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        # --- Menge ---
        qty_layout = QHBoxLayout()
        qty_layout.addWidget(QLabel("Menge:"))
        self._qty_spin = QSpinBox()
        self._qty_spin.setMinimum(1)
        self._qty_spin.setMaximum(999)
        self._qty_spin.setValue(1)
        qty_layout.addWidget(self._qty_spin)
        qty_layout.addStretch()
        layout.addLayout(qty_layout)

        # --- Linienauswahl (optional, nur wenn Topologie vorhanden) ---
        if self._topology and self._topology.areas:
            line_layout = QHBoxLayout()
            line_layout.addWidget(QLabel("Linie:"))
            self._line_combo = QComboBox()
            self._line_combo.addItem("(keine Zuweisung)", None)
            for area in self._topology.areas:
                for line in area.lines:
                    label = f"{area.area_number}.{line.line_number} – {line.name}"
                    self._line_combo.addItem(label, line)
            self._line_combo.currentIndexChanged.connect(self._on_line_changed)
            line_layout.addWidget(self._line_combo)
            line_layout.addStretch()
            layout.addLayout(line_layout)
        else:
            self._line_combo = None

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_ok = QPushButton("Übernehmen")
        self._btn_ok.setEnabled(False)
        self._btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_ok)

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._recent_table.selectionModel().selectionChanged.connect(
            self._on_recent_selection_changed
        )

    # ------------------------------------------------------------------ Zuletzt verwendet

    def _populate_recent_table(self):
        """Befüllt die 'Zuletzt verwendet'-Tabelle aus der gespeicherten Liste."""
        recent = load_recent()
        self._recent_table.setSortingEnabled(False)
        self._recent_table.setRowCount(0)
        _highlight = QColor("#fff9e6")  # zartes Gelb als Unterschied zur Haupttabelle
        bold = QFont()
        bold.setBold(True)

        for row, entry in enumerate(recent):
            prod = ProductSuggestion(
                manufacturer=entry.get("manufacturer", ""),
                order_number=entry.get("order_number", ""),
                product_name=entry.get("product_name", ""),
                channels=entry.get("channels", 0),
                category=entry.get("category", ""),
                actor_type=entry.get("actor_type", ""),
                sensor_type=entry.get("sensor_type", ""),
                device_type=entry.get("device_type", ""),
            )
            self._recent_table.insertRow(row)
            cat_text = _CAT_DISPLAY.get(prod.category, prod.category)
            items = [
                QTableWidgetItem(cat_text),
                QTableWidgetItem(prod.display_type()),
                QTableWidgetItem(prod.manufacturer),
                QTableWidgetItem(prod.order_number),
                QTableWidgetItem(prod.product_name),
                QTableWidgetItem(str(prod.channels) if prod.channels else "–"),
            ]
            for col, item in enumerate(items):
                item.setData(Qt.UserRole, prod)
                item.setBackground(_highlight)
                self._recent_table.setItem(row, col, item)
            if prod.manufacturer in self._preferred:
                for item in items:
                    item.setFont(bold)

        visible = self._recent_table.rowCount() > 0
        self._recent_group.setVisible(visible)

    def _on_recent_selection_changed(self):
        rows = self._recent_table.selectionModel().selectedRows()
        if not rows:
            return
        prod: ProductSuggestion = self._recent_table.item(rows[0].row(), 0).data(Qt.UserRole)
        if prod:
            self._selected = prod
            self._btn_ok.setEnabled(True)
            # Selektion in Haupttabelle aufheben
            self._table.blockSignals(True)
            self._table.clearSelection()
            self._table.blockSignals(False)

    def _on_recent_double_click(self):
        if self._selected:
            self.accept()

    def accept(self):
        """Speichert die Auswahl als 'zuletzt verwendet' und schliesst den Dialog."""
        if self._selected:
            prod = self._selected
            add_recent({
                "order_number": prod.order_number,
                "manufacturer": prod.manufacturer,
                "product_name": prod.product_name,
                "channels": prod.channels,
                "category": prod.category,
                "actor_type": prod.actor_type,
                "sensor_type": prod.sensor_type,
                "device_type": prod.device_type,
            })
        super().accept()

    # ------------------------------------------------------------------ Suche

    def _refresh_results(self):
        query = self._search_edit.text().strip()
        cat_display = self._cat_combo.currentText()
        cat_filter = _CAT_FILTER_MAP.get(cat_display, "")
        mfr_filter = self._mfr_combo.currentText()
        if mfr_filter == "Alle":
            mfr_filter = ""

        all_results = self._search_service.search_all(
            query=query,
            category_filter=cat_filter,
            preferred_manufacturers=self._preferred if self._preferred else None,
        )

        if mfr_filter:
            all_results = [r for r in all_results if r.manufacturer == mfr_filter]

        self._all_results = all_results
        self._populate_table(all_results)

    def _populate_table(self, results: list[ProductSuggestion]):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        bold = QFont()
        bold.setBold(True)

        for row, prod in enumerate(results):
            self._table.insertRow(row)
            cat_text = _CAT_DISPLAY.get(prod.category, prod.category)
            device_type = prod.display_type()

            items = [
                QTableWidgetItem(cat_text),
                QTableWidgetItem(device_type),
                QTableWidgetItem(prod.manufacturer),
                QTableWidgetItem(prod.order_number),
                QTableWidgetItem(prod.product_name),
                QTableWidgetItem(str(prod.channels) if prod.channels else "–"),
            ]
            for col, item in enumerate(items):
                item.setData(Qt.UserRole, row)
                self._table.setItem(row, col, item)

            # Bevorzugte Hersteller fett
            if prod.manufacturer in self._preferred:
                for item in items:
                    item.setFont(bold)

        self._table.setSortingEnabled(True)
        n = len(results)
        self._result_label.setText(
            f"{n} Produkt{'e' if n != 1 else ''} gefunden"
        )
        self._btn_ok.setEnabled(False)
        self._selected = None

    # ------------------------------------------------------------------ Auswahl

    def _on_selection_changed(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._btn_ok.setEnabled(False)
            self._selected = None
            return
        # Selektion in Zuletzt-verwendet-Tabelle aufheben
        self._recent_table.blockSignals(True)
        self._recent_table.clearSelection()
        self._recent_table.blockSignals(False)

        # Originalindex via UserRole
        orig_row = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        # Sortierung: orig_row stimmt nicht mehr nach Sortierung → besser über Bestellnummer
        order_num = self._table.item(rows[0].row(), 3).text()
        mfr = self._table.item(rows[0].row(), 2).text()

        self._selected = next(
            (r for r in self._all_results
             if r.order_number == order_num and r.manufacturer == mfr),
            None,
        )
        self._btn_ok.setEnabled(self._selected is not None)

    def _on_double_click(self):
        if self._selected:
            self.accept()

    def _on_line_changed(self, index: int):
        if self._line_combo:
            self._selected_line = self._line_combo.currentData()

    def get_selected_line(self) -> Line | None:
        """Gibt die gewählte Linie zurück (None wenn keine Zuweisung)."""
        return self._selected_line

    # ------------------------------------------------------------------ KNXPROD

    def _import_knxprod(self):
        filepaths, _ = QFileDialog.getOpenFileNames(
            self, "KNXPROD-Dateien importieren (Mehrfachauswahl möglich)", "",
            "KNX Produktdatenbankdateien (*.knxprod);;Alle Dateien (*.*)",
        )
        if not filepaths:
            return

        svc = KnxprodCatalogService()
        all_products: list[ProductSuggestion] = []
        errors: list[tuple[str, str]] = []
        empty: list[str] = []
        for filepath in filepaths:
            name = os.path.basename(filepath)
            try:
                products = svc.import_file(filepath)
            except ValueError as e:
                errors.append((name, str(e)))
                continue
            if not products:
                empty.append(name)
                continue
            all_products.extend(products)

        if not all_products:
            problems = [f"• {n}: {e}" for n, e in errors] + [f"• {n}: keine Produktdaten gefunden" for n in empty]
            QMessageBox.critical(
                self, "Import-Fehler",
                f"Keine der {len(filepaths)} ausgewählten Datei(en) konnte importiert werden:\n\n"
                + "\n".join(problems),
            )
            return

        # In den Katalog aufnehmen -- ein Schreibvorgang für alle Produkte,
        # persistiert dauerhaft (%APPDATA%), nicht nur für diese Dialog-Instanz
        self._search_service.add_products([p.to_catalog_dict() for p in all_products])

        # Hersteller-Dropdown aktualisieren
        current_mfrs = {
            self._mfr_combo.itemText(i)
            for i in range(self._mfr_combo.count())
        }
        for prod in all_products:
            if prod.manufacturer not in current_mfrs:
                self._mfr_combo.addItem(prod.manufacturer)
                current_mfrs.add(prod.manufacturer)

        self._refresh_results()

        ok_count = len(filepaths) - len(errors) - len(empty)
        summary = (
            f"{len(all_products)} Produkte aus {ok_count} von {len(filepaths)} Datei(en) "
            f"importiert und dem Katalog hinzugefügt."
        )
        if errors or empty:
            problems = [f"• {n}: {e}" for n, e in errors] + [f"• {n}: keine Produktdaten gefunden" for n in empty]
            summary += "\n\nÜbersprungen:\n" + "\n".join(problems)
        QMessageBox.information(self, "Import erfolgreich", summary)

    def _import_knxprod_folder(self):
        """
        Importiert alle .knxprod-Dateien eines Ordners (inkl. Unterordner) in
        einem Rutsch. Bereits vorhandene Produkte (gleicher Hersteller +
        Bestellnummer) werden dabei überschrieben (siehe ProductSearchService._upsert)
        -- so lässt sich der Katalog nach einer Parser-Korrektur einfach auffrischen,
        indem derselbe Ordner erneut importiert wird.
        """
        folder = QFileDialog.getExistingDirectory(
            self, "Ordner mit KNXPROD-Dateien wählen (inkl. Unterordner)",
            _default_products_folder(),
        )
        if not folder:
            return

        filepaths = []
        for root, _dirs, files in os.walk(folder):
            for fn in files:
                if fn.lower().endswith(".knxprod"):
                    filepaths.append(os.path.join(root, fn))
        filepaths.sort()

        if not filepaths:
            QMessageBox.information(
                self, "Keine Dateien gefunden",
                f"Im Ordner \"{folder}\" wurden keine .knxprod-Dateien gefunden.",
            )
            return

        progress = QProgressDialog(
            "Importiere KNXPROD-Dateien…", "Abbrechen", 0, len(filepaths), self,
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        svc = KnxprodCatalogService()
        all_products = []
        errors: list[tuple[str, str]] = []
        empty: list[str] = []
        processed = 0
        for filepath in filepaths:
            name = os.path.relpath(filepath, folder)
            progress.setLabelText(f"Importiere: {name}")
            progress.setValue(processed)
            QApplication.processEvents()
            if progress.wasCanceled():
                break
            try:
                products = svc.import_file(filepath)
            except ValueError as e:
                errors.append((name, str(e)))
            else:
                if products:
                    all_products.extend(products)
                else:
                    empty.append(name)
            processed += 1
        progress.setValue(len(filepaths))

        if not all_products:
            problems = [f"• {n}: {e}" for n, e in errors] + [f"• {n}: keine Produktdaten gefunden" for n in empty]
            QMessageBox.critical(
                self, "Import-Fehler",
                f"Keine der {processed} verarbeiteten Datei(en) konnte importiert werden:\n\n"
                + "\n".join(problems),
            )
            return

        # In den Katalog aufnehmen -- ein Schreibvorgang für alle Produkte,
        # persistiert dauerhaft (%APPDATA%), nicht nur für diese Dialog-Instanz
        self._search_service.add_products([p.to_catalog_dict() for p in all_products])

        current_mfrs = {
            self._mfr_combo.itemText(i)
            for i in range(self._mfr_combo.count())
        }
        for prod in all_products:
            if prod.manufacturer not in current_mfrs:
                self._mfr_combo.addItem(prod.manufacturer)
                current_mfrs.add(prod.manufacturer)

        self._refresh_results()

        ok_count = processed - len(errors) - len(empty)
        summary = (
            f"{len(all_products)} Produkte aus {ok_count} von {processed} verarbeiteten "
            f"Datei(en) importiert bzw. aktualisiert."
        )
        if processed < len(filepaths):
            summary += f"\n\nAbgebrochen nach {processed} von {len(filepaths)} gefundenen Datei(en)."
        if errors or empty:
            problems = [f"• {n}: {e}" for n, e in errors] + [f"• {n}: keine Produktdaten gefunden" for n in empty]
            summary += "\n\nÜbersprungen:\n" + "\n".join(problems)
        QMessageBox.information(self, "Import erfolgreich", summary)

    # ------------------------------------------------------------------ Ergebnis

    @property
    def selected_product(self) -> ProductSuggestion | None:
        return self._selected

    def get_material_entry(self) -> MaterialEntry | None:
        """
        Gibt die ausgewählte Produktauswahl als MaterialEntry zurück.
        Kann nach accept() abgerufen werden.
        """
        if not self._selected:
            return None

        prod = self._selected
        qty = self._qty_spin.value()

        # MaterialEntry-Kategorie aus Produkt ableiten
        if prod.category == "actor":
            ml_cat = "Aktor"
        elif prod.category == "sensor":
            ml_cat = "Sensor"
        else:
            ml_cat = _DEVICE_TYPE_TO_ML_CAT.get(prod.device_type, "Sonstiges")

        entry = MaterialEntry(
            quantity=qty,
            category=ml_cat,
            device_type=prod.display_type(),
            manufacturer=prod.manufacturer,
            order_number=prod.order_number,
            product_name=prod.product_name,
            unit_price=0.0,
            source="manual",
            assigned_channels=prod.channels,
        )

        if self._selected_line and self._topology:
            area_num = ""
            for area in self._topology.areas:
                if self._selected_line in area.lines:
                    area_num = str(area.area_number)
                    break
            entry.line_id = self._selected_line.id
            entry.line_name = (
                f"{area_num}.{self._selected_line.line_number}"
                f" {self._selected_line.name}".strip()
            )

        return entry
