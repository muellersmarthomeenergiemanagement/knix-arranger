"""
Materiallisten-Ansicht (FA-2302, FA-2305, FA-2306)

Zeigt alle KNX-Geräte des Projekts in einer Tabelle,
erlaubt manuelles Hinzufügen und Löschen von Positionen.
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QAbstractItemView,
    QGroupBox, QComboBox, QSpinBox, QMessageBox, QLineEdit, QInputDialog,
    QFileDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from ..dialogs.product_select_dialog import ProductSelectDialog
import math
from ...models.material_list import MaterialList, MaterialEntry, MATERIAL_CATEGORIES, parse_channel_count, split_device_type
from ...models.topology import Device
from ...services.product_search_service import ProductSuggestion
from ...services.topology_engine import TopologyEngine
from ...services.material_list_export_service import MaterialListExportService

logger = logging.getLogger("knix_arranger.material_list_view")


def _flags_str(co: dict) -> str:
    """Erstellt ETS-artigen Flags-String aus ComObject-Dict."""
    return "".join([
        "K" if co.get("communication_flag", True) else "-",
        "L" if co.get("read_flag", False) else "-",
        "Ü" if co.get("write_flag", False) else "-",
        "S" if co.get("transmit_flag", False) else "-",
        "U" if co.get("update_flag", False) else "-",
    ])

# Mapping Gerätetyp → Materiallisten-Kategorie
_DEVICE_CATEGORY = {
    "actor":        "Aktor",
    "sensor":       "Sensor",
    "power_supply": "Netzteil",
    "other":        "Sonstiges",
}

# Spalten-Indizes
_COL_QTY       = 0
_COL_CAT       = 1
_COL_TYPE      = 2
_COL_MFR       = 3
_COL_ORDER     = 4
_COL_PRODNAME  = 5
_COL_CHANNELS  = 6   # Kanal-Validierung: "zugewiesen / benötigt"
_COL_GA        = 7   # GA-Bedarf aus KNXPROD-ComObjects (Min–Max je Gerät)
_COL_LOCATION  = 8
_COL_ADDR      = 9
_COL_LINE      = 10
_COL_SOURCE    = 11
_NUM_COLS      = 12


class MaterialListView(QWidget):
    """Haupt-Ansicht der Materialliste (FA-2302)."""

    # Signalisiert Änderungen an der Materialliste (z.B. für Dirty-Flag)
    list_changed = Signal()
    # Signalisiert Änderungen an der Topologie (Gerät hinzugefügt/aufgeteilt)
    # → empfangene Views müssen Topologie neu laden
    topology_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._material_list: MaterialList | None = None
        self._preferred_manufacturers: list[str] = []
        self._addr_to_line: dict[str, str] = {}   # Cache: phys. Adresse → line.id
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Titel
        title = QLabel("Materialliste")
        title.setObjectName("sectionTitle")
        bold = QFont()
        bold.setPointSize(14)
        bold.setBold(True)
        title.setFont(bold)
        layout.addWidget(title)

        info = QLabel(
            "Alle KNX-Geräte des Projekts. Positionen aus dem Wizard werden automatisch "
            "übernommen; weitere Geräte können manuell hinzugefügt werden."
        )
        info.setWordWrap(True)
        info.setObjectName("subtitle")
        layout.addWidget(info)

        # --- Toolbar ---
        toolbar = QHBoxLayout()

        self._btn_add = QPushButton("+ Gerät hinzufügen…")
        self._btn_add.setToolTip("Produkt aus Katalog wählen und zur Materialliste hinzufügen")
        self._btn_add.clicked.connect(self._add_product)
        toolbar.addWidget(self._btn_add)

        self._btn_remove = QPushButton("Position entfernen")
        self._btn_remove.setEnabled(False)
        self._btn_remove.clicked.connect(self._remove_selected)
        toolbar.addWidget(self._btn_remove)

        self._btn_assign = QPushButton("Produkt zuweisen…")
        self._btn_assign.setEnabled(False)
        self._btn_assign.setToolTip(
            "Dem ausgewählten Platzhalter ein konkretes Produkt aus dem Katalog zuweisen"
        )
        self._btn_assign.clicked.connect(self._assign_selected)
        toolbar.addWidget(self._btn_assign)

        self._btn_split = QPushButton("Aufteilen")
        self._btn_split.setEnabled(False)
        self._btn_split.setToolTip(
            "Gruppierten Eintrag in einzelne Zeilen aufteilen.\n"
            "• Mehrere Geräte: Trennung nach physikalischer Adresse\n"
            "• Einzelner Aktor: Kanalweise aufteilen (z.B. 16-fach → 2× 8-fach)"
        )
        self._btn_split.clicked.connect(self._split_entry)
        toolbar.addWidget(self._btn_split)

        self._btn_batch = QPushButton("Typ-Batch zuweisen…")
        self._btn_batch.setToolTip(
            "Allen Platzhaltern desselben Gerätetyps auf einmal ein Produkt zuweisen"
        )
        self._btn_batch.clicked.connect(self._batch_assign_by_type)
        toolbar.addWidget(self._btn_batch)

        self._btn_sync = QPushButton("Aus Topologie aktualisieren")
        self._btn_sync.setToolTip(
            "Materialliste aus dem aktuellen Stand der Topologie (Linienteilnehmer) neu aufbauen"
        )
        self._btn_sync.clicked.connect(self._on_sync_clicked)
        toolbar.addWidget(self._btn_sync)

        self._btn_export_xlsx = QPushButton("Als Excel exportieren…")
        self._btn_export_xlsx.setToolTip(
            "Materialliste als formatierte .xlsx-Datei exportieren (FA-2307)"
        )
        self._btn_export_xlsx.clicked.connect(self._export_excel)
        toolbar.addWidget(self._btn_export_xlsx)

        toolbar.addStretch()

        # Kategorie-Filter
        toolbar.addWidget(QLabel("Kategorie:"))
        self._filter_combo = QComboBox()
        self._filter_combo.setMinimumWidth(130)
        self._filter_combo.addItem("Alle Kategorien")
        for cat in MATERIAL_CATEGORIES:
            self._filter_combo.addItem(cat)
        self._filter_combo.currentIndexChanged.connect(self._rebuild_table)
        toolbar.addWidget(self._filter_combo)

        # Linien-Filter
        toolbar.addWidget(QLabel("Linie:"))
        self._line_filter_combo = QComboBox()
        self._line_filter_combo.setMinimumWidth(180)
        self._line_filter_combo.addItem("Alle Linien", None)
        self._line_filter_combo.currentIndexChanged.connect(self._rebuild_table)
        toolbar.addWidget(self._line_filter_combo)

        layout.addLayout(toolbar)

        legend = QLabel(
            "<span style='color:#1B5E20;'>&#9679;</span> Produkt zugewiesen&nbsp;&nbsp;"
            "<span style='color:#BF360C;'>&#9679;</span> Kanaldefizit (zu wenig Kanäle zugewiesen)&nbsp;&nbsp;"
            "<span style='color:#666666;'>&#9679;</span> Wizard-Platzhalter (noch kein Produkt zugewiesen)"
        )
        legend.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(legend)

        # --- Tabelle ---
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            "Anz.", "Kategorie", "Typ", "Hersteller",
            "Bestellnummer", "Produktname", "Kanäle", "GA-Bedarf",
            "Einbauort", "Phys. Adresse", "Linie", "Quelle",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(_COL_QTY,      QHeaderView.Fixed)
        hh.setSectionResizeMode(_COL_CAT,      QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_TYPE,     QHeaderView.Interactive)
        hh.setSectionResizeMode(_COL_MFR,      QHeaderView.Interactive)
        hh.setSectionResizeMode(_COL_ORDER,    QHeaderView.Interactive)
        hh.setSectionResizeMode(_COL_PRODNAME, QHeaderView.Interactive)
        hh.setSectionResizeMode(_COL_CHANNELS, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_GA,       QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_LOCATION, QHeaderView.Interactive)
        hh.setSectionResizeMode(_COL_ADDR,     QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_LINE,     QHeaderView.Interactive)
        hh.setSectionResizeMode(_COL_SOURCE,   QHeaderView.ResizeToContents)
        # Initiale Breiten für manuell anpassbare Spalten
        self._table.setColumnWidth(_COL_QTY,       40)
        self._table.setColumnWidth(_COL_TYPE,     160)
        self._table.setColumnWidth(_COL_MFR,      130)
        self._table.setColumnWidth(_COL_ORDER,    120)
        self._table.setColumnWidth(_COL_PRODNAME, 220)
        self._table.setColumnWidth(_COL_LOCATION, 140)
        self._table.setColumnWidth(_COL_LINE,     175)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.doubleClicked.connect(self._on_double_click_row)
        layout.addWidget(self._table)

        # --- Zusammenfassung ---
        summary_group = QGroupBox("Zusammenfassung")
        sum_layout = QHBoxLayout()

        self._lbl_total_qty = QLabel("Positionen: 0")
        sum_layout.addWidget(self._lbl_total_qty)

        sum_layout.addStretch()

        self._lbl_auto_hint = QLabel("")
        self._lbl_auto_hint.setObjectName("subtitle")
        sum_layout.addWidget(self._lbl_auto_hint)

        summary_group.setLayout(sum_layout)
        layout.addWidget(summary_group)

    # ------------------------------------------------------------------ Daten

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus (für Phase B: manuelle Bearbeitung)."""
        self._bus = bus

    def set_project(self, project) -> None:
        """Setzt das Projekt, synchronisiert die Materialliste aus der Topologie."""
        self._project = project
        self._material_list = project.material_list
        self._preferred_manufacturers = project.config.preferred_manufacturers
        self.sync_from_topology()   # baut wizard_auto-Einträge neu auf
        self._rebuild_addr_cache()  # phys. Adresse → line.id Cache
        self._populate_line_filter()
        self._rebuild_table()

    def set_material_list(self, material_list: MaterialList,
                          preferred_manufacturers: list[str] | None = None):
        """Setzt die Materialliste ohne Projekt-Kontext (Fallback)."""
        self._material_list = material_list
        self._preferred_manufacturers = preferred_manufacturers or []
        self._rebuild_table()

    # ------------------------------------------------------------------ Sync

    def sync_from_topology(self) -> None:
        """
        Baut alle wizard_auto-Einträge neu aus den Linienteilnehmern der
        Topologie auf (FA-2305). Geräte mit gleicher Bestellnummer werden
        global zu einer Zeile zusammengefasst. Platzhalter (kein order_number)
        werden pro Linie gruppiert, damit unterschiedliche Produkte je Linie
        zugewiesen werden können.
        Manuelle Einträge (source='manual') bleiben unverändert.
        """
        if not self._project or not self._material_list:
            return
        topology = self._project.topology
        if not topology.areas:
            return

        self._material_list.clear_auto_entries()

        # Gruppen aufbauen: key → [(device, line_label, line_id)]
        # Zugewiesene Geräte (order_number gesetzt): global nach Bestellnummer
        # Platzhalter (kein order_number): pro Linie, damit unterschiedliche
        # Produkte je Linie zugewiesen werden können.
        from collections import OrderedDict
        groups: OrderedDict = OrderedDict()

        for area in topology.areas:
            # Speisegerät Bereichslinie gesondert erfassen (nicht in line.devices)
            if area.backbone_power_supply is not None:
                dev = area.backbone_power_supply
                category = "Netzteil"
                area_label = f"{area.coupler_address}  Bereichslinie {area.name}".strip()
                if dev.order_number:
                    key = (category, dev.product,
                           dev.manufacturer, dev.order_number, "")
                else:
                    key = (category, dev.product, "", "", area.id)
                groups.setdefault(key, []).append((dev, area_label, area.id))

            for line in area.lines:
                line_label = f"{line.coupler_address}  {line.name}".strip()
                for device in line.devices:
                    category = self._device_category(device)
                    if device.order_number:
                        key = (category, device.product,
                               device.manufacturer, device.order_number, "")
                    else:
                        key = (category, device.product, "", "", line.id)
                    groups.setdefault(key, []).append(
                        (device, line_label, line.id)
                    )

        for (category, device_type, manufacturer, order_number, _), items in groups.items():
            first_dev = items[0][0]

            # Physikalische Adressen sammeln
            addrs = [
                d.physical_address for d, _, _ in items if d.physical_address
            ]

            # Einbauorte: eindeutige Werte, bei >3 komprimieren
            seen_locs: list[str] = []
            for d, _, _ in items:
                if d.installation_location and d.installation_location not in seen_locs:
                    seen_locs.append(d.installation_location)
            if not seen_locs:
                location_str = ""
            elif len(seen_locs) <= 3:
                location_str = ", ".join(seen_locs)
            else:
                location_str = f"{len(seen_locs)} Einbauorte"

            # Linie: befüllen wenn alle Geräte auf derselben Linie liegen
            # (Platzhalter sind jetzt immer einliniig; zugewiesene Geräte
            # können mehrere Linien umfassen)
            line_ids = list(dict.fromkeys(lid for _, _, lid in items))
            line_names = list(dict.fromkeys(ln for _, ln, _ in items))
            line_id = line_ids[0] if len(line_ids) == 1 else ""
            line_name = line_names[0] if len(line_names) == 1 else ""

            entry = MaterialEntry(
                quantity=len(items),
                category=category,
                device_type=device_type,
                manufacturer=manufacturer,
                order_number=order_number,
                product_name=first_dev.product_name,
                installation_location=location_str,
                source="wizard_auto",
                line_id=line_id,
                line_name=line_name,
                physical_addresses=addrs,
                device_id=first_dev.id if len(items) == 1 else "",
                required_channels=parse_channel_count(device_type),
            )
            self._material_list.entries.append(entry)

    def _rebuild_addr_cache(self) -> None:
        """Baut den physikalische-Adresse→line.id Cache einmalig auf."""
        self._addr_to_line = {}
        if not self._project:
            return
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.physical_address:
                        self._addr_to_line[device.physical_address] = line.id

    @staticmethod
    def _device_category(device: Device) -> str:
        if device.device_type == "coupler":
            return (
                "Bereichskoppler"
                if device.product == "Bereichskoppler"
                else "Linienkoppler"
            )
        return _DEVICE_CATEGORY.get(device.device_type, "Sonstiges")

    def _on_sync_clicked(self) -> None:
        self.sync_from_topology()
        self._rebuild_addr_cache()  # phys. Adresse → line.id Cache
        self._populate_line_filter()
        self._rebuild_table()
        self.list_changed.emit()

    def _export_excel(self) -> None:
        """Exportiert die Materialliste als .xlsx (FA-2307)."""
        if not self._material_list:
            return

        project_name = (
            self._project.name if self._project else "KNX-Projekt"
        )
        default_filename = f"Materialliste_{project_name}.xlsx".replace(" ", "_")

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Materialliste exportieren",
            default_filename,
            "Excel-Datei (*.xlsx)",
        )
        if not filepath:
            return

        try:
            service = MaterialListExportService()
            service.export_xlsx(self._material_list, project_name, filepath)
            QMessageBox.information(
                self,
                "Export erfolgreich",
                f"Materialliste wurde exportiert:\n{filepath}",
            )
        except ImportError as exc:
            QMessageBox.warning(self, "openpyxl fehlt", str(exc))
        except Exception as exc:
            QMessageBox.critical(
                self, "Export fehlgeschlagen", f"Fehler beim Export:\n{exc}"
            )

    # ------------------------------------------------------------------ Filter

    def _populate_line_filter(self) -> None:
        """Befüllt den Linien-Filter aus der aktuellen Topologie."""
        self._line_filter_combo.blockSignals(True)
        current_id = self._line_filter_combo.currentData()
        self._line_filter_combo.clear()
        self._line_filter_combo.addItem("Alle Linien", None)

        if self._project and self._project.topology.areas:
            for area in self._project.topology.areas:
                for line in area.lines:
                    label = f"{line.coupler_address}  {line.name}".strip()
                    self._line_filter_combo.addItem(label, line.id)

        # Vorherige Auswahl wiederherstellen
        if current_id:
            for i in range(self._line_filter_combo.count()):
                if self._line_filter_combo.itemData(i) == current_id:
                    self._line_filter_combo.setCurrentIndex(i)
                    break

        self._line_filter_combo.blockSignals(False)

    # ------------------------------------------------------------------ Tabelle

    def _rebuild_table(self):
        if self._material_list is None:
            return

        cat_filter     = self._filter_combo.currentText()
        line_id_filter = self._line_filter_combo.currentData()

        entries = self._material_list.entries
        if cat_filter != "Alle Kategorien":
            entries = [e for e in entries if e.category == cat_filter]
        if line_id_filter:
            entries = [
                e for e in entries
                if e.line_id == line_id_filter
                or any(self._addr_to_line.get(a) == line_id_filter
                       for a in e.physical_addresses)
            ]

        self._table.setSortingEnabled(False)
        self._table.blockSignals(True)
        self._table.setRowCount(0)

        for entry in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)

            qty_item = QTableWidgetItem()
            qty_item.setData(Qt.DisplayRole, entry.quantity)
            qty_item.setData(Qt.UserRole, entry.id)
            qty_item.setTextAlignment(Qt.AlignCenter)

            addr_item = QTableWidgetItem(entry.physical_address_display)

            # Kanäle-Spalte: "zugewiesen / benötigt"
            # Bei qty > 1: Gesamtdeckung anzeigen (qty × assigned / required)
            if entry.required_channels > 0 and entry.assigned_channels > 0:
                total_assigned = entry.quantity * entry.assigned_channels
                if entry.quantity > 1:
                    ch_text = f"{total_assigned} ({entry.quantity}×{entry.assigned_channels}) / {entry.required_channels}"
                else:
                    ch_text = f"{entry.assigned_channels} / {entry.required_channels}"
            elif entry.required_channels > 0:
                ch_text = f"— / {entry.required_channels}"
            elif entry.assigned_channels > 0:
                ch_text = str(entry.assigned_channels)
            else:
                ch_text = ""
            ch_item = QTableWidgetItem(ch_text)
            ch_item.setTextAlignment(Qt.AlignCenter)

            # GA-Bedarf-Spalte: "Min–Max" (nur wenn KNXPROD-Daten vorhanden)
            if entry.ga_min > 0 or entry.ga_max > 0:
                if entry.ga_min == entry.ga_max:
                    ga_text = str(entry.ga_min)
                else:
                    ga_text = f"{entry.ga_min}–{entry.ga_max}"
                ga_tooltip = (
                    f"GA-Bedarf aus KNXPROD-ComObjects:\n"
                    f"Min. {entry.ga_min} (Basis-Objekte)\n"
                    f"Max. {entry.ga_max} (inkl. Status/Feedback)\n"
                    f"je Gerät, Gesamt: {entry.quantity}× = "
                    f"{entry.ga_min * entry.quantity}–"
                    f"{entry.ga_max * entry.quantity} GAs"
                )
            else:
                ga_text = ""
                ga_tooltip = "Keine KNXPROD-Daten. Produkt aus .knxprod-Datei zuweisen."
            ga_item = QTableWidgetItem(ga_text)
            ga_item.setTextAlignment(Qt.AlignCenter)
            ga_item.setToolTip(ga_tooltip)

            items = [
                qty_item,
                QTableWidgetItem(entry.category),
                QTableWidgetItem(entry.device_type),
                QTableWidgetItem(entry.manufacturer),
                QTableWidgetItem(entry.order_number),
                QTableWidgetItem(entry.product_name or entry.device_type),
                ch_item,
                ga_item,
                QTableWidgetItem(entry.installation_location),
                addr_item,
                QTableWidgetItem(entry.line_name),
                QTableWidgetItem(
                    "Wizard" if entry.source == "wizard_auto" else "Manuell"
                ),
            ]

            # Wizard-Einträge einfärben:
            # – Kanaldefizit → orange; korrekt zugewiesen → dunkelgrün; Platzhalter → grau
            if entry.source == "wizard_auto":
                if entry.manufacturer and entry.channel_deficit > 0:
                    color = QColor("#BF360C")   # orange-rot für Kanaldefizit
                    total_assigned = entry.quantity * entry.assigned_channels
                    deficit_tooltip = (
                        f"Kanaldefizit: {entry.channel_deficit} Kanal(e) fehlen\n"
                        f"Benötigt: {entry.required_channels}  |  "
                        f"Zugewiesen: {entry.quantity}×{entry.assigned_channels} = {total_assigned}"
                    )
                    for item in items:
                        item.setForeground(color)
                        item.setToolTip(deficit_tooltip)
                elif entry.manufacturer:
                    color = QColor("#1B5E20")   # dunkelgrün = OK
                    for item in items:
                        item.setForeground(color)
                        item.setToolTip("Produkt zugewiesen, Kanalbedarf gedeckt.")
                else:
                    color = QColor("#666666")   # grau = Platzhalter ohne Zuweisung
                    for item in items:
                        item.setForeground(color)
                        item.setToolTip(
                            "Wizard-Platzhalter: noch kein Produkt zugewiesen.\n"
                            "Doppelklick oder \"Produkt zuweisen\" verwenden."
                        )

            for col, item in enumerate(items):
                # Nur Menge (Spalte 0) bei manuellen Einträgen editierbar
                if col != 0 or entry.source == "wizard_auto":
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(row, col, item)

        self._table.blockSignals(False)
        self._table.setSortingEnabled(True)

        self._update_summary()

    def _update_summary(self):
        if self._material_list is None:
            return

        all_entries = self._material_list.entries
        n = len(all_entries)
        auto_count    = sum(1 for e in all_entries if e.source == "wizard_auto")
        assigned      = sum(1 for e in all_entries if e.source == "wizard_auto" and e.manufacturer)
        deficit_count = sum(1 for e in all_entries if e.source == "wizard_auto" and e.channel_deficit > 0)

        self._lbl_total_qty.setText(f"Geräte gesamt: {n}")
        if auto_count:
            hint = f"davon {auto_count} aus Topologie  |  {assigned} mit Produktzuweisung"
            if deficit_count:
                hint += f"  |  {deficit_count} mit Kanaldefizit (!)"
            self._lbl_auto_hint.setText(hint)
        else:
            self._lbl_auto_hint.setText("")

    # ------------------------------------------------------------------ Aktionen

    def _add_product(self):
        if self._material_list is None:
            return

        topology = self._project.topology if self._project else None

        dialog = ProductSelectDialog(
            preferred_manufacturers=self._preferred_manufacturers,
            topology=topology,
            parent=self,
        )
        if not dialog.exec():
            return

        entry = dialog.get_material_entry()
        if not entry:
            return

        selected_line = dialog.get_selected_line()
        topology_modified = False
        if selected_line and self._project:
            self._insert_devices_into_line(entry, selected_line)
            topology_modified = True

        self._material_list.add(entry)
        self._rebuild_table()
        self.list_changed.emit()
        if topology_modified:
            self.topology_changed.emit()   # Topologie-Views benachrichtigen

    def _insert_devices_into_line(self, entry: MaterialEntry, line) -> None:
        """Fügt Devices in line.devices ein und weist physikalische Adressen zu."""
        device_type_map = {"Aktor": "actor", "Sensor": "sensor"}
        dt = device_type_map.get(entry.category, "other")

        new_devices = []
        for _ in range(entry.quantity):
            dev = Device(
                device_type=dt,
                product=entry.device_type,
                product_name=entry.product_name,
                manufacturer=entry.manufacturer,
                order_number=entry.order_number,
                installation_location=line.uv_location,
            )
            if dt == "actor":
                # Aktoren vor dem ersten Sensor einfügen
                insert_at = next(
                    (i for i, d in enumerate(line.devices) if d.device_type == "sensor"),
                    len(line.devices),
                )
                line.devices.insert(insert_at, dev)
            else:
                line.devices.append(dev)
            new_devices.append(dev)

        line.update_device_count()

        engine = TopologyEngine(self._project.config.topology_mode)
        engine.assign_physical_addresses(
            self._project.topology,
            small_project=(self._project.topology.topology_mode == "TP-64"),
        )

        entry.physical_addresses = [
            d.physical_address for d in new_devices if d.physical_address
        ]

    def _remove_selected(self):
        if self._material_list is None:
            return

        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return

        entry_id = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        if not entry_id:
            return

        # Nur manuelle Einträge können entfernt werden
        entry = next((e for e in self._material_list.entries if e.id == entry_id), None)
        if entry and entry.source == "wizard_auto":
            QMessageBox.information(
                self, "Hinweis",
                "Automatisch ermittelte Einträge können nicht manuell entfernt werden.\n"
                "Verwenden Sie 'Aus Topologie aktualisieren' um die Liste neu aufzubauen.",
            )
            return

        reply = QMessageBox.question(
            self, "Position entfernen",
            "Soll die ausgewählte Position aus der Materialliste entfernt werden?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._material_list.remove(entry_id)
            self._rebuild_table()
            self.list_changed.emit()

    def _on_selection_changed(self):
        rows = self._table.selectionModel().selectedRows()
        self._btn_remove.setEnabled(bool(rows))

        # "Produkt zuweisen" und "Aufteilen" nur für wizard_auto-Zeilen
        is_wizard_auto = False
        can_split = False
        if rows and self._material_list:
            entry_id = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
            entry = next((e for e in self._material_list.entries if e.id == entry_id), None)
            is_wizard_auto = entry is not None and entry.source == "wizard_auto"
            # Adressbasierter Split: mehrere Geräte gruppiert
            can_split_by_addr = (is_wizard_auto
                                 and entry is not None
                                 and len(entry.physical_addresses) > 1)
            # Kanalbasierter Split: einzelner Aktor mit bekannter Kanalzahl
            can_split_by_ch = (is_wizard_auto
                               and entry is not None
                               and entry.category == "Aktor"
                               and entry.required_channels > 0
                               and len(entry.physical_addresses) <= 1)
            can_split = can_split_by_addr or can_split_by_ch
        self._btn_assign.setEnabled(is_wizard_auto)
        self._btn_split.setEnabled(can_split)

    def _on_double_click_row(self, index) -> None:
        """Doppelklick auf wizard_auto-Zeile öffnet direkt die Produktzuweisung."""
        entry_id = self._table.item(index.row(), 0).data(Qt.UserRole)
        if not entry_id or not self._material_list:
            return
        entry = next((e for e in self._material_list.entries if e.id == entry_id), None)
        if entry and entry.source == "wizard_auto":
            self._assign_product_to_entry(entry)

    def _assign_selected(self) -> None:
        """Produktzuweisung für die aktuell selektierte Zeile."""
        rows = self._table.selectionModel().selectedRows()
        if not rows or not self._material_list:
            return
        entry_id = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        entry = next((e for e in self._material_list.entries if e.id == entry_id), None)
        if entry:
            self._assign_product_to_entry(entry)

    def _split_entry(self) -> None:
        """
        Teilt einen wizard_auto-Eintrag auf:
        • Mehrere physikalische Adressen → adressbasierter Split (un-group)
        • Einzelner Aktor mit required_channels → kanalbasierter Split in der Topologie
        """
        rows = self._table.selectionModel().selectedRows()
        if not rows or not self._material_list:
            return

        entry_id = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        entry = next((e for e in self._material_list.entries if e.id == entry_id), None)
        if not entry or entry.source != "wizard_auto":
            return

        # Kanalbasierter Split für einzelnen Aktor
        if (entry.category == "Aktor"
                and entry.required_channels > 0
                and len(entry.physical_addresses) <= 1):
            self._split_actor_by_channels(entry)
            return

        if len(entry.physical_addresses) <= 1:
            return

        # Geräte aus der Topologie per Adresse nachschlagen
        addr_to_device: dict[str, Device] = {}
        if self._project:
            for area in self._project.topology.areas:
                for line in area.lines:
                    for device in line.devices:
                        if device.physical_address:
                            addr_to_device[device.physical_address] = device

        # Einfügeposition merken, damit Reihenfolge erhalten bleibt
        idx = self._material_list.entries.index(entry)
        self._material_list.entries.pop(idx)

        for addr in entry.physical_addresses:
            dev = addr_to_device.get(addr)
            individual = MaterialEntry(
                quantity=1,
                category=entry.category,
                device_type=entry.device_type,
                manufacturer=entry.manufacturer,
                order_number=entry.order_number,
                product_name=entry.product_name,
                unit_price=entry.unit_price,
                source="wizard_auto",
                note=entry.note,
                installation_location=dev.installation_location if dev else entry.installation_location,
                line_id=entry.line_id,
                line_name=entry.line_name,
                physical_addresses=[addr],
                device_id=dev.id if dev else "",
                required_channels=entry.required_channels,
                assigned_channels=entry.assigned_channels,
            )
            self._material_list.entries.insert(idx, individual)
            idx += 1

        self._rebuild_table()
        self.list_changed.emit()

    def _split_actor_by_channels(self, entry: MaterialEntry) -> None:
        """
        Teilt einen einzelnen Aktor-Platzhalter kanalweise auf.

        Beispiel: "Schaltaktor 16-fach" → 2× "Schaltaktor 8-fach"
        Die Topologie wird entsprechend aktualisiert und physikalische
        Adressen werden neu vergeben.
        """
        required = entry.required_channels

        n, ok = QInputDialog.getInt(
            self,
            "Aktor kanalweise aufteilen",
            f"«{entry.device_type}» hat {required} Kanäle.\n"
            f"In wie viele gleich große Einheiten aufteilen?",
            2, 2, required, 1,
        )
        if not ok:
            return

        channels_per_unit = math.ceil(required / n)
        new_device_type = split_device_type(entry.device_type, channels_per_unit)

        # Gerät in der Topologie suchen (device_id oder physikalische Adresse)
        target_line = None
        target_device = None
        if self._project:
            for area in self._project.topology.areas:
                for line in area.lines:
                    for device in line.devices:
                        id_match   = entry.device_id and device.id == entry.device_id
                        addr_match = (entry.physical_addresses
                                      and device.physical_address == entry.physical_addresses[0])
                        if id_match or addr_match:
                            target_line   = line
                            target_device = device
                            break
                    if target_line:
                        break
                if target_line:
                    break

        if not target_line or not target_device:
            QMessageBox.warning(
                self, "Gerät nicht gefunden",
                "Das Gerät konnte in der Topologie nicht gefunden werden.\n"
                "Bitte die Topologie neu synchronisieren.",
            )
            return

        # Originales Gerät entfernen; Einfügeposition merken (Aktoren vor Sensoren)
        insert_at = target_line.devices.index(target_device)
        target_line.devices.remove(target_device)

        # N neue Geräte an derselben Stelle einfügen
        # manually_split=True schützt diese Devices vor Wizard-Überschreibung
        new_devices = []
        for i in range(n):
            new_dev = Device(
                device_type="actor",
                product=new_device_type,
                installation_location=target_device.installation_location,
                manually_split=True,
            )
            target_line.devices.insert(insert_at + i, new_dev)
            new_devices.append(new_dev)

        target_line.update_device_count()

        # Physikalische Adressen für die gesamte Topologie neu vergeben
        engine = TopologyEngine(self._project.config.topology_mode)
        engine.assign_physical_addresses(
            self._project.topology,
            small_project=(self._project.topology.topology_mode == "TP-64"),
        )

        # Materiallisten-Eintrag ersetzen
        idx = self._material_list.entries.index(entry)
        self._material_list.entries.pop(idx)

        for i, dev in enumerate(new_devices):
            new_entry = MaterialEntry(
                quantity=1,
                category=entry.category,
                device_type=new_device_type,
                manufacturer=entry.manufacturer,
                order_number=entry.order_number,
                product_name=entry.product_name,
                unit_price=entry.unit_price,
                source="wizard_auto",
                note=entry.note,
                installation_location=target_device.installation_location,
                line_id=entry.line_id,
                line_name=entry.line_name,
                physical_addresses=[dev.physical_address] if dev.physical_address else [],
                device_id=dev.id,
                required_channels=channels_per_unit,
                assigned_channels=entry.assigned_channels,
            )
            self._material_list.entries.insert(idx + i, new_entry)

        self._populate_line_filter()
        self._rebuild_table()
        self.list_changed.emit()
        self.topology_changed.emit()   # Topologie-Views benachrichtigen

    def _assign_product_to_entry(self, entry: MaterialEntry) -> None:
        """
        Öffnet den Produktauswahl-Dialog für einen Platzhalter und
        schreibt das gewählte Produkt in MaterialEntry und Device zurück.
        """
        # Kategorie-Filter passend zum Eintragstyp vorbelegen
        _cat_map = {"Aktor": "actor", "Sensor": "sensor"}
        _infra = {"Linienkoppler", "Bereichskoppler", "IP-Router", "Netzteil", "DALI-Gateway"}
        if entry.category in _infra:
            initial_cat = "infrastructure"
        else:
            initial_cat = _cat_map.get(entry.category, "")

        topology = self._project.topology if self._project else None
        dialog = ProductSelectDialog(
            preferred_manufacturers=self._preferred_manufacturers,
            initial_category_filter=initial_cat,
            topology=topology,
            parent=self,
        )
        # Suche mit dem Gerätetyp vorbelegen, damit passende Produkte sofort erscheinen
        dialog._search_edit.setText(entry.device_type)

        if not dialog.exec():
            return

        prod = dialog.selected_product
        if not prod:
            return

        # MaterialEntry aktualisieren
        entry.manufacturer = prod.manufacturer
        entry.order_number = prod.order_number
        entry.product_name = prod.product_name
        entry.assigned_channels = prod.channels
        entry.ga_min = prod.ga_min
        entry.ga_max = prod.ga_max

        # Kanaldefizit prüfen und Benutzer warnen
        # channel_deficit berücksichtigt bereits quantity × assigned_channels
        if entry.channel_deficit > 0:
            total_assigned = entry.quantity * prod.channels
            reply = QMessageBox.warning(
                self,
                "Kanaldefizit erkannt",
                f"Das gewählte Produkt «{prod.product_name or prod.order_number}» "
                f"hat {prod.channels} Kanal(e) pro Gerät.\n"
                f"Der Platzhalter «{entry.device_type}» benötigt "
                f"{entry.required_channels} Kanal(e).\n\n"
                f"Zugewiesene Kanäle gesamt: {entry.quantity}×{prod.channels} = {total_assigned}\n"
                f"Fehlende Kanäle gesamt:    {entry.channel_deficit}\n\n"
                f"Tipp: Erhöhen Sie die Anzahl Geräte, um den Bedarf zu decken "
                f"(z.B. {-(-entry.required_channels // prod.channels)}× für volle Deckung).\n\n"
                f"Trotzdem zuweisen?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                # Zuweisung rückgängig machen
                entry.manufacturer = ""
                entry.order_number = ""
                entry.product_name = ""
                entry.assigned_channels = 0
                return

        # Rückkopplung ins Device der Topologie
        if self._project:
            self._update_device_product(entry, prod)

        self._rebuild_table()
        self.list_changed.emit()

    def _update_device_product(self, entry: MaterialEntry,
                               prod: ProductSuggestion) -> None:
        """
        Schreibt Produktdaten in alle Device-Objekte der Topologie zurück,
        die zu diesem Materiallisten-Eintrag gehören (per physical_addresses).
        Schreibt auch ComObjects aus KNXPROD zurück (für DatasheetView).

        Aktualisiert zudem die Kanalzahl verknüpfter Bedienelemente auf die
        effektive Kanalzahl des zugewiesenen Produkts: die geplante (bedarfs-
        basierte) Kanalzahl ist oft kleiner als die des tatsächlich verbauten
        Geräts (z.B. 8-fach-Taster statt berechneter 7 Kanäle) – das Bauherr-
        Formular bietet dank be.channels dann die zusätzlichen Tasten als
        wählbare Slots an.
        """
        from ...models.topology import CommunicationObject

        be_by_addr = {
            be.participant_number: be
            for room in self._project.all_rooms
            for be in room.bedienelemente
            if be.participant_number
        }

        def _apply(device: Device) -> None:
            device.manufacturer = prod.manufacturer
            device.order_number = prod.order_number
            device.product_name = prod.product_name
            if prod.com_objects:
                device.communication_objects = [
                    CommunicationObject(
                        object_number=co.get("number", 0),
                        name=co.get("name", ""),
                        object_function=co.get("function_text", ""),
                        data_type=co.get("datapoint_type", ""),
                        flags=_flags_str(co),
                    )
                    for co in prod.com_objects
                ]
            if prod.channels:
                be = be_by_addr.get(device.physical_address)
                if be:
                    be.channels = prod.channels

        addr_set = set(entry.physical_addresses)
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.physical_address in addr_set:
                        _apply(device)
                    elif entry.device_id and device.id == entry.device_id:
                        _apply(device)

    def _batch_assign_by_type(self) -> None:
        """
        Weist allen Platzhaltern desselben Gerätetyps auf einmal ein Produkt zu.
        Nur unzugewiesene wizard_auto-Einträge (kein Hersteller) werden berücksichtigt.
        """
        if not self._material_list:
            return

        # Eindeutige Typen der noch offenen Platzhalter sammeln
        open_by_type: dict[str, list[MaterialEntry]] = {}
        for e in self._material_list.entries:
            if e.source == "wizard_auto" and not e.manufacturer:
                open_by_type.setdefault(e.device_type, []).append(e)

        if not open_by_type:
            QMessageBox.information(
                self, "Alle Platzhalter zugewiesen",
                "Es sind keine offenen Platzhalter ohne Produktzuweisung vorhanden.",
            )
            return

        # Typ-Auswahl via einfachem Dialog
        type_list = sorted(open_by_type.keys())
        display_items = [f"{t}  ({len(open_by_type[t])}×)" for t in type_list]

        chosen_display, ok = QInputDialog.getItem(
            self,
            "Typ-Batch: Gerätetyp wählen",
            "Welchem Gerätetyp soll ein Produkt zugewiesen werden?",
            display_items,
            0,
            False,
        )
        if not ok:
            return

        chosen_type = type_list[display_items.index(chosen_display)]
        entries_to_assign = open_by_type[chosen_type]

        # Kategorie für den Produktdialog ableiten (am ersten Eintrag)
        _cat_map = {"Aktor": "actor", "Sensor": "sensor"}
        _infra = {"Linienkoppler", "Bereichskoppler", "IP-Router", "Netzteil", "DALI-Gateway"}
        sample_cat = entries_to_assign[0].category
        if sample_cat in _infra:
            initial_cat = "infrastructure"
        else:
            initial_cat = _cat_map.get(sample_cat, "")

        topology = self._project.topology if self._project else None
        dialog = ProductSelectDialog(
            preferred_manufacturers=self._preferred_manufacturers,
            initial_category_filter=initial_cat,
            topology=topology,
            parent=self,
        )
        dialog._search_edit.setText(chosen_type)

        if not dialog.exec():
            return

        prod = dialog.selected_product
        if not prod:
            return

        # Kanaldefizit prüfen (am Typ, da alle Einträge denselben Typ haben)
        required = parse_channel_count(chosen_type)
        if required > 0 and 0 < prod.channels < required:
            deficit_per_device = required - prod.channels
            total_missing = deficit_per_device * len(entries_to_assign)
            reply = QMessageBox.warning(
                self,
                "Kanaldefizit erkannt",
                f"Das gewählte Produkt «{prod.product_name or prod.order_number}» "
                f"hat {prod.channels} Kanal(e),\n"
                f"der Typ «{chosen_type}» benötigt jedoch {required} Kanal(e).\n\n"
                f"Fehlende Kanäle je Gerät: {deficit_per_device}\n"
                f"Fehlende Kanäle gesamt:   {total_missing} "
                f"(bei {len(entries_to_assign)} Gerät(en))\n\n"
                f"Trotzdem zuweisen?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        # Alle Einträge dieses Typs zuweisen
        for entry in entries_to_assign:
            entry.manufacturer = prod.manufacturer
            entry.order_number = prod.order_number
            entry.product_name = prod.product_name
            entry.assigned_channels = prod.channels
            entry.ga_min = prod.ga_min
            entry.ga_max = prod.ga_max
            if self._project:
                self._update_device_product(entry, prod)

        QMessageBox.information(
            self,
            "Batch-Zuweisung abgeschlossen",
            f"{len(entries_to_assign)} Platzhalter vom Typ «{chosen_type}»\n"
            f"wurden mit «{prod.product_name or prod.order_number}» belegt.",
        )
        self._rebuild_table()
        self.list_changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem):
        """Reagiert auf Mengen-Änderung durch Doppelklick (nur manuelle Einträge)."""
        if item.column() != 0:
            return
        if self._material_list is None:
            return

        entry_id = self._table.item(item.row(), 0).data(Qt.UserRole)
        try:
            new_qty = int(item.text())
        except (ValueError, TypeError):
            # Ungültige Eingabe nicht still verwerfen: ohne Rebuild würde die
            # Zelle den ungültigen Text weiter anzeigen, obwohl das Modell
            # unveraendert bleibt (Anzeige und Modell laufen auseinander).
            QMessageBox.warning(
                self, "Ungültige Menge",
                f"'{item.text()}' ist keine gültige Ganzzahl.\n"
                "Der vorherige Wert bleibt erhalten."
            )
            self._rebuild_table()
            return

        if new_qty < 1:
            new_qty = 1

        for entry in self._material_list.entries:
            if entry.id == entry_id:
                entry.quantity = new_qty
                break

        # Tabelle neu aufbauen: Kanäle-Spalte und Farben hängen von qty ab
        self._rebuild_table()
        self.list_changed.emit()
