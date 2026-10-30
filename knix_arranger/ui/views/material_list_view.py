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
    QFileDialog, QMenu, QDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from ..dialogs.product_select_dialog import ProductSelectDialog
import math
from ...models.material_list import MaterialList, MaterialEntry, MATERIAL_CATEGORIES, parse_channel_count, split_device_type
from ...models.topology import Device
from ...models.device import GEWERK_TO_SENSOR_TYPE, GEWERK_TO_ACTOR_TYPE
from ...services.product_search_service import ProductSuggestion
from ...services.topology_engine import TopologyEngine
from ...services.material_list_export_service import MaterialListExportService
from ...services.device_gewerk_service import describe_device_gewerke
from ..icons import icon
from ..styles import KNX_BLUE
from .. import license_gate  # NFA-066: Exporte im Lesemodus gesperrt

logger = logging.getLogger("knix_arranger.material_list_view")


# Mapping Gerätetyp → Materiallisten-Kategorie
_DEVICE_CATEGORY = {
    "actor":        "Aktor",
    "sensor":       "Sensor",
    "gateway":      "Gateway / Schnittstellen",   # FA-1308
    "power_supply": "Netzteil",
    "other":        "Sonstiges",
}

# Spalten-Indizes
_COL_QTY       = 0
_COL_CAT       = 1
_COL_TYPE      = 2
_COL_GEWERK    = 3   # Gewerk / Raum, für das Aktor bzw. Gateway geplant ist
_COL_MFR       = 4
_COL_ORDER     = 5
_COL_PRODNAME  = 6
_COL_CHANNELS  = 7   # Kanal-Validierung: "zugewiesen / benötigt"
_COL_GA        = 8   # GA-Bedarf aus KNXPROD-ComObjects (Min–Max je Gerät)
_COL_LOCATION  = 9
_COL_ADDR      = 10
_COL_LINE      = 11
_COL_SOURCE    = 12
_NUM_COLS      = 13


def _copy_product(source: Device, target: Device) -> None:
    """Produkt eines aufgeteilten Aktors auf ein neues Gerät übernehmen
    (Hersteller, Bestellnummer, ETS-Kennungen, KOs ohne Verknüpfungen)."""
    import copy
    if not source.order_number:
        return
    for name in ("manufacturer", "manufacturer_id", "product_ref_id", "hw2prog_id",
                 "secure_supported", "bus_current", "order_number", "product_name",
                 "application_program"):
        setattr(target, name, getattr(source, name))
    target.datasheets = list(source.datasheets)
    target.communication_objects = copy.deepcopy(source.communication_objects)
    for co in target.communication_objects:
        co.connected_gas = []


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
        # Cache für die Gewerk-Spalte: phys. Adresse / device.id → (Device, Line)
        self._device_by_addr: dict[str, tuple] = {}
        self._device_by_id: dict[str, tuple] = {}
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Titel
        title = QLabel("Materialliste")
        title.setObjectName("title")
        layout.addWidget(title)

        info = QLabel(
            "Alle KNX-Geräte des Projekts. Positionen aus dem Wizard werden automatisch "
            "übernommen; weitere Geräte können manuell hinzugefügt werden."
        )
        info.setWordWrap(True)
        info.setObjectName("subtitle")
        layout.addWidget(info)

        # --- Toolbar: Hauptaktionen als Buttons, alles Weitere im Menü
        # "Weitere", Filter rechts -- passt einzeilig ab 1280 px Breite ---
        toolbar = QHBoxLayout()

        self._btn_add = QPushButton("+ Gerät hinzufügen…")
        self._btn_add.setToolTip("Produkt aus Katalog wählen und zur Materialliste hinzufügen")
        self._btn_add.clicked.connect(self._add_product)
        toolbar.addWidget(self._btn_add)

        self._btn_assign = QPushButton("Produkt zuweisen…")
        self._btn_assign.setEnabled(False)
        self._btn_assign.setToolTip(
            "Dem ausgewählten Platzhalter ein konkretes Produkt aus dem Katalog zuweisen"
        )
        self._btn_assign.clicked.connect(self._assign_selected)
        toolbar.addWidget(self._btn_assign)

        more_menu = QMenu(self)
        more_menu.setToolTipsVisible(True)
        self._btn_batch = more_menu.addAction("Typ-Batch zuweisen…", self._batch_assign_by_type)
        self._btn_batch.setToolTip(
            "Allen Platzhaltern desselben Gerätetyps auf einmal ein Produkt zuweisen"
        )
        self._btn_split = more_menu.addAction("Aufteilen", self._split_entry)
        self._btn_split.setEnabled(False)
        self._btn_split.setToolTip(
            "Gruppierten Eintrag in einzelne Zeilen aufteilen.\n"
            "• Mehrere Geräte: Trennung nach physikalischer Adresse\n"
            "• Einzelner Aktor: Kanalweise aufteilen (z.B. 16-fach → 2× 8-fach)"
        )
        self._btn_ga = more_menu.addAction("GA-Bedarf festlegen…", self._set_ga_override)
        self._btn_ga.setEnabled(False)
        self._btn_channels = more_menu.addAction("Kanäle und KOs zuordnen…",
                                                 self._assign_channels_selected)
        self._btn_channels.setEnabled(False)
        self._btn_replace_dup = more_menu.addAction("Produkte mit KOs übernehmen…",
                                                    self._replace_duplicate_products)
        self._btn_replace_dup.setToolTip(
            "Produkte ohne KOs, die der Katalog auch aus der KNXPROD mit KOs kennt\n"
            "(doppelte Einträge, z.B. ABB VAA/S6.230.2.1), durch den Eintrag mit KOs ersetzen")
        self._btn_ko_batch = more_menu.addAction("KOs aller Geräte zuordnen…",
                                                 self._assign_all_kos)
        self._btn_ko_batch.setToolTip(
            "Alle Aktoren, Taster und Sensoren mit KOs aus dem Produkt, die noch\n"
            "keine Zuordnung haben, auf einmal zuordnen (gemerkte Zuordnung gleicher\n"
            "Produkte vor Vorschlag) – danach nur die unsicheren Fälle prüfen")
        self._btn_ko_names = more_menu.addAction("KO-Namen aus ETS-Projekt übernehmen…",
                                                 self._learn_ko_names)
        self._btn_ko_names.setToolTip(
            "Aus einem importierten ETS-Projekt die echten KO-Texte, Flags und DPTs\n"
            "je Produkt lernen (z.B. «Taste 1, links» statt «Object 1») und bei allen\n"
            "Geräten desselben Produkts einsetzen – auch bei künftigen Zuweisungen")
        self._btn_channels.setToolTip(
            "Aktoren: Stromkreise den Kanälen zuordnen (Benennung des Herstellers,\n"
            "z.B. Kanal C) und je GA den KO wählen – nicht benötigte KOs bleiben frei.\n"
            "Taster und Sensoren: je Gerät jeder GA ihren KO zuordnen"
        )
        self._btn_ga.setToolTip(
            "GA-Bedarf je Gerät von Hand festlegen, z.B. für frei belegbare\n"
            "Gateways, deren KNXPROD nur generische Objektplätze enthält"
        )
        more_menu.addSeparator()
        self._btn_sync = more_menu.addAction("Aus Topologie aktualisieren", self._on_sync_clicked)
        self._btn_sync.setToolTip(
            "Materialliste aus dem aktuellen Stand der Topologie (Linienteilnehmer) neu aufbauen"
        )
        self._btn_export_xlsx = more_menu.addAction("Als Excel exportieren…", self._export_excel)
        self._btn_export_xlsx.setToolTip("Materialliste als formatierte .xlsx-Datei exportieren")
        more_menu.addSeparator()
        self._btn_remove = more_menu.addAction("Position entfernen", self._remove_selected)
        self._btn_remove.setEnabled(False)

        btn_more = QPushButton("Weitere")
        btn_more.setObjectName("secondary")
        btn_more.setIcon(icon("dots", KNX_BLUE))
        btn_more.setMenu(more_menu)
        toolbar.addWidget(btn_more)

        toolbar.addStretch()

        # Kategorie-Filter
        toolbar.addWidget(QLabel("Kategorie:"))
        self._filter_combo = QComboBox()
        self._filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._filter_combo.addItem("Alle Kategorien")
        for cat in MATERIAL_CATEGORIES:
            self._filter_combo.addItem(cat)
        self._filter_combo.currentIndexChanged.connect(self._rebuild_table)
        toolbar.addWidget(self._filter_combo)

        # Typ-Filter (Spalte «Typ», z.B. «Jalousieaktor 8-fach»)
        toolbar.addWidget(QLabel("Typ:"))
        self._type_filter_combo = QComboBox()
        self._type_filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._type_filter_combo.addItem("Alle Typen", None)
        self._type_filter_combo.currentIndexChanged.connect(self._rebuild_table)
        toolbar.addWidget(self._type_filter_combo)

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
        legend.setStyleSheet("font-size: 12px; color: #666;")
        layout.addWidget(legend)

        # --- Tabelle ---
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            "Anz.", "Kategorie", "Typ", "Gewerk / Raum", "Hersteller",
            "Bestellnummer", "Produktname", "Kanäle", "GA-Bedarf",
            "Einbauort", "Phys. Adresse", "Linie", "Quelle",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(_COL_QTY,      QHeaderView.Fixed)
        hh.setSectionResizeMode(_COL_CAT,      QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_TYPE,     QHeaderView.Interactive)
        hh.setSectionResizeMode(_COL_GEWERK,   QHeaderView.Interactive)
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
        self._table.setColumnWidth(_COL_GEWERK,   200)
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
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
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

        # Produktabhängige Werte (Kanäle, GA-Bedarf inkl. manuellem Wert),
        # die die Topologie selbst nicht kennt, für dasselbe Produkt über
        # den Neuaufbau hinweg erhalten -- sonst gingen sie bei jedem
        # Öffnen des Projekts verloren.
        product_values: dict[tuple[str, str], dict] = {}
        for old in self._material_list.entries:
            if old.source == "wizard_auto" and old.order_number:
                product_values.setdefault((old.manufacturer, old.order_number), {
                    "assigned_channels": old.assigned_channels,
                    "ga_min": old.ga_min,
                    "ga_max": old.ga_max,
                    "ga_override": old.ga_override,
                    "secure_supported": old.secure_supported,
                })

        self._material_list.clear_auto_entries()

        # Gruppen aufbauen: key → [(device, line_label, line_id)]
        # Zugewiesene Geräte (order_number gesetzt): global nach Bestellnummer
        # Platzhalter (kein order_number): pro Linie, damit unterschiedliche
        # Produkte je Linie zugewiesen werden können.
        from collections import OrderedDict
        groups: OrderedDict = OrderedDict()

        # Speisegerät der Bereichslinie 0.0 (nicht in line.devices)
        if topology.backbone_power_supply is not None:
            dev = topology.backbone_power_supply
            key = (("Netzteil", dev.product, dev.manufacturer, dev.order_number, "")
                   if dev.order_number else ("Netzteil", dev.product, "", "", "backbone"))
            groups.setdefault(key, []).append((dev, "0.0  Bereichslinie", "backbone"))

        for area in topology.areas:
            # Speisegerät Hauptlinie gesondert erfassen (nicht in line.devices)
            if area.backbone_power_supply is not None:
                dev = area.backbone_power_supply
                category = "Netzteil"
                area_label = f"{area.area_number}.0  Hauptlinie {area.name}".strip()
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
            if order_number:
                for attr, value in product_values.get((manufacturer, order_number), {}).items():
                    setattr(entry, attr, value)
            self._material_list.entries.append(entry)

    def _rebuild_addr_cache(self) -> None:
        """Baut den physikalische-Adresse→line.id Cache einmalig auf
        (sowie die Geräte-Caches für die Gewerk-Spalte)."""
        self._addr_to_line = {}
        self._device_by_addr = {}
        self._device_by_id = {}
        if not self._project:
            return
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    self._device_by_id[device.id] = (device, line)
                    if device.physical_address:
                        self._addr_to_line[device.physical_address] = line.id
                        self._device_by_addr[device.physical_address] = (device, line)

    def _entry_gewerk_info(self, entries: list[MaterialEntry]) -> tuple[str, str]:
        """(Kurztext, Tooltip) zur Gewerk-/Raumzuordnung der Geräte hinter
        den Einträgen -- z.B. "WP Waermepumpe – U01 Technik"."""
        if not self._project:
            return "", ""
        devices = []
        for entry in entries:
            found = [
                self._device_by_addr[a] for a in entry.physical_addresses
                if a in self._device_by_addr
            ]
            if not found and entry.device_id in self._device_by_id:
                found = [self._device_by_id[entry.device_id]]
            devices.extend(found)
        if not devices:
            return "", ""
        room_by_id = {r.id: r for r in self._project.all_rooms}
        return describe_device_gewerke(
            devices, room_by_id, self._project.gewerk_catalog
        )

    def _product_dialog_title(self, entries: list[MaterialEntry],
                              device_type: str) -> str:
        """Titel des Produktauswahl-Dialogs inkl. Gewerk, damit beim Wählen
        klar ist, wofür das Gerät geplant ist."""
        gewerk_text, _ = self._entry_gewerk_info(entries)
        title = f"Produkt für {device_type} auswählen" if device_type else "Produkt auswählen"
        return f"{title} ({gewerk_text})" if gewerk_text else title

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

        filepath, _ = license_gate.get_save_file_name(
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

    def _populate_type_filter(self, entries: list) -> None:
        """Typen der (nach Kategorie gefilterten) Einträge; die Auswahl bleibt,
        solange es den Typ noch gibt."""
        types = sorted({e.device_type for e in entries if e.device_type}, key=str.lower)
        current = self._type_filter_combo.currentData()
        if [self._type_filter_combo.itemData(i)
                for i in range(1, self._type_filter_combo.count())] == types:
            return
        self._type_filter_combo.blockSignals(True)
        self._type_filter_combo.clear()
        self._type_filter_combo.addItem("Alle Typen", None)
        for device_type in types:
            self._type_filter_combo.addItem(device_type, device_type)
        index = self._type_filter_combo.findData(current) if current else 0
        self._type_filter_combo.setCurrentIndex(max(index, 0))
        self._type_filter_combo.blockSignals(False)

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
        self._populate_type_filter(entries)
        type_filter = self._type_filter_combo.currentData()
        if type_filter:
            entries = [e for e in entries if e.device_type == type_filter]
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
        duplicates = {entry.id: variant for entry, variant in self.duplicate_replacements()}

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
            ga_manual = entry.ga_override is not None
            if ga_manual:
                ga_text = f"{entry.ga_override} (manuell)"
                ga_tooltip = (
                    f"GA-Bedarf von Hand festgelegt: {entry.ga_override} je Gerät, "
                    f"Gesamt: {entry.quantity}× = {entry.ga_override * entry.quantity} GAs"
                )
                if entry.ga_min or entry.ga_max:
                    ga_tooltip += f"\nAus KNXPROD: {entry.ga_min}–{entry.ga_max}"
            elif entry.ga_min > 0 or entry.ga_max > 0:
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
            if ga_manual:
                ga_font = ga_item.font()
                ga_font.setItalic(True)
                ga_item.setFont(ga_font)

            gewerk_text, gewerk_tooltip = self._entry_gewerk_info([entry])
            gewerk_item = QTableWidgetItem(gewerk_text)

            items = [
                qty_item,
                QTableWidgetItem(entry.category),
                QTableWidgetItem(entry.device_type),
                gewerk_item,
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

            # Doppelter Katalogeintrag ohne KOs (FA-622)
            variant = duplicates.get(entry.id)
            if variant is not None:
                name_item = items[_COL_PRODNAME]
                name_item.setText(f"{name_item.text()}  ⚠ ohne KOs")
                name_item.setForeground(QColor("#BF360C"))
                name_item.setToolTip(
                    f"Dieses Produkt hat keine KOs. Vermutlich dasselbe Gerät: "
                    f"{variant.order_number} – {variant.product_name} ({variant.co_count} KOs).\n"
                    f"Weitere › «Produkte mit KOs übernehmen…»")

            # Vollständige Raumliste als Tooltip der Gewerk-Spalte (ersetzt
            # in dieser Zelle den Status-Tooltip der Zeile)
            if gewerk_tooltip:
                gewerk_item.setToolTip(gewerk_tooltip)

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
        self._btn_ga.setEnabled(bool(rows))
        self._btn_channels.setEnabled(bool(self._channel_devices(self._selected_entry())))

    def _set_ga_override(self) -> None:
        """GA-Bedarf je Gerät für die ausgewählte Position von Hand festlegen.
        Leere Eingabe stellt den Wert aus der KNXPROD-Datei wieder her."""
        rows = self._table.selectionModel().selectedRows()
        if not rows or not self._material_list:
            return
        entry_id = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        entry = next((e for e in self._material_list.entries if e.id == entry_id), None)
        if entry is None:
            return

        current = "" if entry.ga_override is None else str(entry.ga_override)
        hint = (f"Aus KNXPROD: {entry.ga_min}–{entry.ga_max}\n"
                if entry.ga_min or entry.ga_max else "")
        text, ok = QInputDialog.getText(
            self, "GA-Bedarf festlegen",
            f"{entry.product_name or entry.device_type}\n{hint}\n"
            "GA-Bedarf je Gerät (leer = Wert aus KNXPROD):",
            text=current,
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            entry.ga_override = None
        else:
            try:
                value = int(text)
                if value < 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(
                    self, "Ungültige Eingabe",
                    f"'{text}' ist keine gültige Anzahl.\nDer bisherige Wert bleibt erhalten.",
                )
                return
            entry.ga_override = value

        self._rebuild_table()
        self.list_changed.emit()

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
                ga_min=entry.ga_min,
                ga_max=entry.ga_max,
                ga_override=entry.ga_override,
                secure_supported=entry.secure_supported,
            )
            self._material_list.entries.insert(idx, individual)
            idx += 1

        self._rebuild_table()
        self.list_changed.emit()

    def _split_actor_by_channels(self, entry: MaterialEntry,
                                 n: int | None = None) -> list[MaterialEntry]:
        """
        Teilt einen einzelnen Aktor-Platzhalter kanalweise auf.

        Beispiel: "Schaltaktor 16-fach" → 2× "Schaltaktor 8-fach"
        Die Topologie wird entsprechend aktualisiert und physikalische
        Adressen werden neu vergeben -- auch in den übrigen Einträgen der
        Materialliste. Hat das Gerät schon ein Produkt (Projekt_23 1.1.10:
        «Heizungsaktor 12-fach» = ABB VAA/S6, 6 Kanäle), erhalten es die
        neuen Geräte ebenfalls. n: Anzahl Einheiten (sonst Rückfrage).
        Gibt die neuen Einträge zurück ([] = abgebrochen).
        """
        required = entry.required_channels
        if n is not None:
            return self._split_actor(entry, n)

        n, ok = QInputDialog.getInt(
            self,
            "Aktor kanalweise aufteilen",
            f"«{entry.device_type}» hat {required} Kanäle.\n"
            f"In wie viele gleich große Einheiten aufteilen?",
            2, 2, required, 1,
        )
        if not ok:
            return []
        return self._split_actor(entry, n)

    @staticmethod
    def _units_needed(entry: MaterialEntry, prod) -> int:
        """Geräte, die ein Aktor-Platzhalter mit diesem Produkt braucht; 0 =
        kein Aufteilen (kein Defizit, kein Aktor oder schon mehrere Geräte).
        Mehr Stück in der Materialliste ergäben kein zweites Gerät in der
        Topologie -- die Kreise lägen auf Kanälen, die es nicht gibt.
        Gateways werden nicht aufgeteilt: ihre Konfiguration (DALI-Gruppen)
        hängt am Gerät."""
        units = -(-entry.required_channels // prod.channels) if prod.channels else 0
        if (entry.channel_deficit > 0 and units > 1 and entry.category == "Aktor"
                and entry.quantity == 1 and len(entry.physical_addresses) <= 1):
            return units
        return 0

    def _split_actor(self, entry: MaterialEntry, n: int) -> list[MaterialEntry]:
        """Aufteilen in n Einheiten (siehe _split_actor_by_channels)."""
        required = entry.required_channels
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
            return []

        # Die Adressen verschieben sich: übrige Einträge über das Gerät nachführen
        device_by_address = {
            dev.physical_address: dev for area in self._project.topology.areas
            for line in area.lines for dev in line.devices if dev.physical_address}

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
            _copy_product(target_device, new_dev)
            target_line.devices.insert(insert_at + i, new_dev)
            new_devices.append(new_dev)

        target_line.update_device_count()

        # Physikalische Adressen für die gesamte Topologie neu vergeben
        engine = TopologyEngine(self._project.config.topology_mode)
        engine.assign_physical_addresses(
            self._project.topology,
            small_project=(self._project.topology.topology_mode == "TP-64"),
        )

        for other in self._material_list.entries:
            if other is not entry:
                other.physical_addresses = [
                    device_by_address[pa].physical_address if pa in device_by_address else pa
                    for pa in other.physical_addresses]

        # Materiallisten-Eintrag ersetzen
        idx = self._material_list.entries.index(entry)
        self._material_list.entries.pop(idx)

        new_entries: list[MaterialEntry] = []
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
                secure_supported=entry.secure_supported,
                ga_min=entry.ga_min,
                ga_max=entry.ga_max,
            )
            self._material_list.entries.insert(idx + i, new_entry)
            new_entries.append(new_entry)

        self._populate_line_filter()
        self._rebuild_table()
        self.list_changed.emit()
        self.topology_changed.emit()   # Topologie-Views benachrichtigen
        return new_entries

    def duplicate_replacements(self) -> list[tuple[MaterialEntry, ProductSuggestion]]:
        """(Eintrag, Produkt mit KOs) für Einträge, deren Produkt keine KOs hat,
        der Katalog dasselbe Gerät aber mit KOs kennt (FA-622)."""
        from ...services.product_sync import shared_catalog
        catalog = shared_catalog()
        if catalog is None or not self._material_list:
            return []
        result = []
        for entry in self._material_list.entries:
            if not entry.order_number:
                continue
            variant = catalog.variant_with_com_objects(ProductSuggestion(
                manufacturer=entry.manufacturer, order_number=entry.order_number,
                product_name=entry.product_name))
            if variant is not None:
                result.append((entry, variant))
        return result

    def _replace_duplicate_products(self) -> None:
        """Doppelte Produkte ohne KOs durch den Eintrag mit KOs ersetzen."""
        pairs = self.duplicate_replacements()
        if not pairs:
            QMessageBox.information(self, "Produkte mit KOs übernehmen",
                                    "Keine Produkte ohne KOs mit doppeltem Katalogeintrag.")
            return
        lines = "\n".join(
            f"• {', '.join(entry.physical_addresses) or entry.device_type}: "
            f"{entry.order_number} → {variant.order_number} ({variant.co_count} KOs)"
            for entry, variant in pairs)
        answer = QMessageBox.question(
            self, "Produkte mit KOs übernehmen",
            f"Diese Produkte haben keine KOs; der Katalog kennt vermutlich dasselbe "
            f"Gerät aus der KNXPROD mit KOs:\n\n{lines}\n\nErsetzen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        self.apply_replacements(pairs)

    def apply_replacements(self, pairs: list[tuple[MaterialEntry, ProductSuggestion]]) -> None:
        for entry, variant in pairs:
            entry.manufacturer = variant.manufacturer
            entry.order_number = variant.order_number
            entry.product_name = variant.product_name
            entry.assigned_channels = variant.channels or entry.assigned_channels
            entry.secure_supported = variant.secure_supported
            entry.ga_min, entry.ga_max = variant.ga_min, variant.ga_max
            if self._project:
                self._update_device_product(entry, variant)
        self._rebuild_table()
        self.list_changed.emit()

    def _prefer_variant_with_kos(self, prod: ProductSuggestion) -> ProductSuggestion:
        """Produkt ohne KOs gewählt, der Katalog kennt das Gerät aber auch aus
        der KNXPROD (ABB VAA/S6.230.2.1 = 2CDG 110 116 R0011, 82 KOs): den
        Eintrag mit KOs anbieten -- ohne KOs keine Kanal-/KO-Zuordnung."""
        from ...services.product_sync import shared_catalog
        catalog = shared_catalog()
        variant = catalog.variant_with_com_objects(prod) if catalog else None
        if variant is None:
            return prod
        answer = QMessageBox.question(
            self, "Produkt mit KOs",
            f"«{prod.order_number} – {prod.product_name}» hat im Katalog keine KOs.\n"
            f"Dasselbe Gerät gibt es aus der KNXPROD mit {variant.co_count} KOs:\n\n"
            f"{variant.order_number} – {variant.product_name}\n\n"
            f"Diesen Eintrag verwenden (empfohlen, sonst keine Kanal-/KO-Zuordnung)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        return variant if answer == QMessageBox.Yes else prod

    def _suggested_search_text(self, entry: MaterialEntry) -> str:
        """Best-Effort-Vorschlag für die Produktsuche: Bestellnummer eines in
        Schritt 5 (Gewerke) bereits für denselben Raum/dasselbe Gewerk
        verknüpften Produkts (GewerkAssignment.linked_product), falls
        eindeutig zuordenbar. Liefert "" wenn nichts Passendes gefunden wird
        (Aufrufer fällt dann auf den generischen Gerätetyp zurück)."""
        if not self._project or not entry.device_id:
            return ""

        device = next(
            (dev for area in self._project.topology.areas
             for line in area.lines for dev in line.devices
             if dev.id == entry.device_id),
            None,
        )
        if device is None or not device.room_id:
            return ""

        room = next(
            (r for r in self._project.all_rooms if r.id == device.room_id), None,
        )
        if room is None:
            return ""

        # Sensor mit eigenem Produkt für sein Element (z.B. Wassermelder =
        # Element 2 von Gewerk A): das Produkt dieses Elements vorschlagen
        if entry.category == "Sensor":
            from ...services.button_move import bedienelement_of_device
            _room, be = bedienelement_of_device(self._project, device)
            by_code = {a.gewerk_code: a for a in room.gewerk_assignments}
            for sf in (be.funktionen if be is not None else []):
                assignment = by_code.get(sf.gewerk_code)
                lp = (assignment.product_for_element(sf.element_number)
                      if assignment and sf.element_number else None)
                if lp and lp.get("order_number"):
                    return lp["order_number"]

        type_map = GEWERK_TO_SENSOR_TYPE if entry.category == "Sensor" else GEWERK_TO_ACTOR_TYPE
        for assignment in room.gewerk_assignments:
            if assignment.gewerk_code not in type_map:
                continue
            lp = assignment.linked_product
            if lp and lp.get("order_number"):
                return lp["order_number"]

        return ""

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
            initial_device_type=entry.device_type,
            for_assignment=True,
        )
        dialog.setWindowTitle(self._product_dialog_title([entry], entry.device_type))
        # Suche vorbelegen: falls in Schritt 5 für dasselbe Gewerk bereits ein
        # Produkt verknüpft wurde (GA-Generierung), dessen Bestellnummer als
        # praezisen Vorschlag nutzen - sonst den generischen Gerätetyp.
        # Mit Typ-Vorauswahl im Typenbaum kein zusätzlicher Typ-Suchtext
        dialog._search_edit.setText(
            self._suggested_search_text(entry)
            or ("" if dialog.has_type_preselection() else entry.device_type)
        )

        if not dialog.exec():
            return

        prod = dialog.selected_product
        if not prod:
            return
        prod = self._prefer_variant_with_kos(prod)

        # MaterialEntry aktualisieren
        entry.manufacturer = prod.manufacturer
        entry.order_number = prod.order_number
        entry.product_name = prod.product_name
        entry.assigned_channels = prod.channels
        entry.secure_supported = prod.secure_supported
        entry.ga_min = prod.ga_min
        entry.ga_max = prod.ga_max
        entry.ga_override = None  # gehörte zum bisherigen Produkt

        # Kanaldefizit bei einem einzelnen Aktor: auf mehrere Geräte aufteilen
        # (Projekt_23 1.1.10: «Heizungsaktor 12-fach» = 2× ABB VAA/S6, 6 Kanäle)
        # -- mehr Stück in der Materialliste ergäben kein zweites Gerät in der
        # Topologie, die Kreise 7–12 lägen auf Kanälen, die es nicht gibt
        # Automatisch, ohne Rückfrage: die Anzahl Geräte folgt aus dem Bedarf
        units = self._units_needed(entry, prod)
        if units > 1:
            new_entries = self._split_actor(entry, units)
            if not new_entries:
                return
            devices = [d for new_entry in new_entries
                       for d in self._update_device_product(new_entry, prod)]
            self._rebuild_table()
            self.list_changed.emit()
            QMessageBox.information(
                self, "Auf mehrere Geräte aufgeteilt",
                f"«{prod.product_name or prod.order_number}» hat {prod.channels} Kanäle, "
                f"«{entry.device_type}» braucht {entry.required_channels}: {units} Geräte "
                f"eingefügt, physikalische Adressen der Linie neu vergeben.")
            self._offer_channel_assignment(new_entries[0], devices)
            return
        # Kanaldefizit prüfen und Benutzer warnen
        # channel_deficit berücksichtigt bereits quantity × assigned_channels
        elif entry.channel_deficit > 0:
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
        devices = self._update_device_product(entry, prod) if self._project else []

        self._rebuild_table()
        self.list_changed.emit()
        self._offer_device_product(devices)
        self._auto_assign_kos(entry, devices)

    # ── Kanäle und KOs (actor_channels) ──

    def _channel_devices(self, entry: MaterialEntry | None) -> list:
        """Aktoren/Gateways bzw. Taster/Sensoren der Topologie hinter einem
        Eintrag (Sensoren nur mit KOs aus dem Produkt)."""
        if entry is None or not self._project:
            return []
        addrs = set(entry.physical_addresses)
        return [d for area in self._project.topology.areas for line in area.lines
                for d in line.devices
                if (d.device_type in ("actor", "gateway")
                    or (d.device_type == "sensor" and d.communication_objects))
                and (d.physical_address in addrs
                     or (entry.device_id and d.id == entry.device_id))]

    def _selected_entry(self) -> MaterialEntry | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows or not self._material_list:
            return None
        entry_id = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((e for e in self._material_list.entries if e.id == entry_id), None)

    def _assign_channels_selected(self) -> None:
        self._assign_channels(self._channel_devices(self._selected_entry()))

    # Sprünge in andere Ansichten (ViewJumps), von MainWindow gesetzt (FA-1011e)
    jumps = None

    def _entry_of(self, device):
        return next((e for e in (self._material_list.entries if self._material_list else [])
                     if (e.device_id and e.device_id == device.id)
                     or (device.physical_address
                         and device.physical_address in e.physical_addresses)), None)

    def select_device(self, device) -> bool:
        """Position eines Geräts anwählen (Sprung aus der Topologie, FA-1011e);
        Filter, die sie ausblenden, werden zurückgesetzt."""
        entry = self._entry_of(device)
        if entry is None:
            return False
        if not self._select_entry(entry):
            for combo in (self._filter_combo, self._type_filter_combo, self._line_filter_combo):
                combo.setCurrentIndex(0)
            return self._select_entry(entry)
        return True

    def _entry_devices(self, entry) -> list:
        """Geräte einer Position in der Topologie."""
        if not self._project:
            return []
        return [d for area in self._project.topology.areas for line in area.lines
                for d in line.devices
                if (entry.device_id and d.id == entry.device_id)
                or (d.physical_address and d.physical_address in entry.physical_addresses)]

    def _show_context_menu(self, pos) -> None:
        """Rechtsklick auf eine Position: Geräte in der Topologie (FA-1011e)."""
        if self.jumps is None:
            return
        row = self._table.rowAt(pos.y())
        item = self._table.item(row, 0) if row >= 0 else None
        entry = next((e for e in (self._material_list.entries if self._material_list else [])
                      if item is not None and e.id == item.data(Qt.UserRole)), None)
        if entry is None:
            return
        from ..jump_menu import add_jump_menu
        menu = QMenu(self)
        add_jump_menu(menu, "In Topologie zeigen",
                      lambda: [(d, f"{d.physical_address or '–'} {d.product or d.device_type}")
                               for d in self._entry_devices(entry)],
                      lambda d: self.jumps.device(d), "kein Gerät in der Topologie")
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def open_ko_assignment(self, physical_address: str, focus: tuple = ()) -> bool:
        """«Kanäle und KOs zuordnen» für ein Gerät öffnen (Sprung aus der
        Validierung, FA-634); focus = (Stromkreis bzw. ga_key, Funktion,
        vorgeschlagener KO) markiert die Zeile und setzt den Vorschlag.
        False, wenn das Gerät nicht (mehr) da ist."""
        if not self._project:
            return False
        device = next((d for area in self._project.topology.areas for line in area.lines
                       for d in line.devices if d.physical_address == physical_address), None)
        if device is None or not device.communication_objects:
            return False
        entry = next((e for e in (self._material_list.entries if self._material_list else [])
                      if physical_address in e.physical_addresses
                      or (e.device_id and e.device_id == device.id)), None)
        if entry is not None:
            self._select_entry(entry)
        self._assign_channels([device], focus=(device.id, *focus) if focus else None)
        return True

    def _select_entry(self, entry) -> bool:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == entry.id:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return True
        return False

    def _assign_channels(self, devices: list, focus: tuple | None = None) -> None:
        """focus = (Geräte-id, Stromkreis bzw. ga_key, Funktion, KO-Vorschlag)."""
        from ..dialogs.actor_channel_dialog import ActorChannelDialog
        if not devices:
            return
        sensors = [d for d in devices if d.device_type == "sensor"]
        if sensors:
            from ..dialogs.sensor_ko_dialog import SensorKoDialog
            dlg = SensorKoDialog(self._project, sensors, parent=self, focus=focus)
            if dlg.exec() == QDialog.Accepted:
                dlg.apply()
                self.list_changed.emit()
            return
        self._release_sensor_products(devices)
        dlg = ActorChannelDialog(self._project, devices, parent=self, focus=focus)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.apply():
            # Weggelassene Funktionen: GAs neu erzeugen (Plätze bleiben Reserve)
            from ...services.address_generator import regenerate_addresses
            regenerate_addresses(self._project)
            bus = getattr(self, "_bus", None)
            if bus:
                bus.emit_functions_changed()
        self.list_changed.emit()

    def _learn_ko_names(self) -> None:
        """KO-Texte je Produkt aus einem importierten ETS-Projekt lernen und
        bei allen Geräten dieses Projekts einsetzen (FA-1411d)."""
        if not self._project:
            return
        from PySide6.QtWidgets import QFileDialog
        from ...services import ko_names
        from ...services.project_service import ProjectService
        path, _f = QFileDialog.getOpenFileName(
            self, "ETS-Projekt mit KO-Namen wählen", "",
            "KNiX-Projekt (*.knxarr);;Alle Dateien (*)")
        if not path:
            return
        try:
            source = ProjectService().load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, "KO-Namen", f"Projekt konnte nicht gelesen werden:\n{exc}")
            return
        learned = ko_names.learn_from_project(source)
        bus = getattr(self, "_bus", None)
        if bus:
            bus.begin_change("KO-Namen aus ETS-Projekt übernommen")
        replaced = ko_names.apply_to_project(self._project)
        self._rebuild_table()
        self.list_changed.emit()
        QMessageBox.information(
            self, "KO-Namen",
            f"{sum(learned.values())} KO-Texte von {len(learned)} Produkt(en) gelernt "
            f"und gemerkt.\n{replaced} KO(s) in diesem Projekt erhielten ihren echten "
            f"Namen.\n\nDanach «KOs aller Geräte zuordnen», damit die Zuordnung die "
            f"neuen Namen nutzt.")

    def _assign_all_kos(self) -> None:
        """Sammelvorschlag: KOs aller Geräte ohne Zuordnung (FA-3009)."""
        from ...services.ko_batch import apply_plan, plan_all
        from ..dialogs.ko_batch_dialog import KoBatchDialog
        if not self._project:
            return
        # Neu eingelesene Herstellerdateien: Objektfunktion und Grösse der KOs
        from ...services.product_sync import refresh_device_com_objects
        refresh_device_com_objects(self._project)
        batch = plan_all(self._project)
        if not batch.plans and not batch.kept:
            QMessageBox.information(
                self, "KOs aller Geräte zuordnen",
                "Kein Gerät mit KOs aus dem Produkt gefunden – zuerst Produkte mit "
                "KNXPROD-Daten zuweisen.")
            return
        dlg = KoBatchDialog(self._project, batch, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        if apply_plan(self._project, batch, omit=dlg.omit):
            # Weggelassene Funktionen: GAs neu erzeugen (Plätze bleiben Reserve)
            from ...services.address_generator import regenerate_addresses
            regenerate_addresses(self._project)
            bus = getattr(self, "_bus", None)
            if bus:
                bus.emit_functions_changed()
        self.list_changed.emit()

    def _release_sensor_products(self, devices: list) -> None:
        """Bedient der Aktor Elemente, deren GAs dem Produkt eines Sensors
        folgen (z.B. «P1: Bewegung» statt E/A), vor der KO-Zuordnung anbieten,
        sie auf den Standard des Gewerks zurückzusetzen."""
        from ...services.product_sync import (
            release_sensor_products, sensor_products_on_actor_gewerke,
        )
        found = sensor_products_on_actor_gewerke(self._project, devices)
        if not found:
            return
        lines = "\n".join(
            f"• {m.element_text} ({m.room.number} {m.room.name}): "
            f"{m.device.physical_address} {m.device.manufacturer} {m.device.order_number}"
            for m in found)
        answer = QMessageBox.question(
            self, "GAs nach dem Sensor",
            f"Die GAs dieser Elemente folgen dem Produkt ihres Sensors, gehören "
            f"aber dem Aktor:\n\n{lines}\n\nProdukt entfernen und die GAs nach dem "
            f"Standard des Gewerks erzeugen (E/A, RM …)? Der Sensor sendet auf "
            f"die Schalt-GA.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        from ...services.address_generator import regenerate_addresses
        release_sensor_products(found)
        regenerate_addresses(self._project)
        bus = getattr(self, "_bus", None)
        if bus:
            bus.emit_functions_changed()

    def _auto_assign_kos(self, entry, devices: list) -> None:
        """Nach der Produktzuweisung die KOs der Geräte gleich zuordnen wie
        «KOs aller Geräte zuordnen» (gewählte KOs bleiben, Lücken werden
        gefüllt); nur
        unsichere Fälle (kein KO, DPT) als Rückfrage mit Zuordnungsdialog."""
        if not self._project or not devices:
            return
        from ...services.ko_batch import NO_KO, UNNEEDED, apply_plan, plan_all
        from ...services.product_sync import refresh_device_com_objects
        refresh_device_com_objects(self._project)
        batch = plan_all(self._project, only=devices)
        if not batch.plans:
            if entry is not None:
                self._offer_channel_assignment(entry, devices)
            return
        apply_plan(self._project, batch)
        unsure = [i for i in batch.issues if i.problem != UNNEEDED]
        self.list_changed.emit()
        if not unsure:
            return
        lines = "\n".join(
            f"• {i.device.physical_address} {i.where}: {i.function} "
            f"({'kein passendes KO' if i.problem == NO_KO else i.problem})"
            for i in unsure[:8])
        more = f"\n… und {len(unsure) - 8} weitere" if len(unsure) > 8 else ""
        answer = QMessageBox.question(
            self, "KOs zugeordnet",
            f"{batch.links} Verknüpfung(en) zugeordnet. Nicht sicher:\n\n{lines}{more}"
            f"\n\nJetzt im Dialog «Kanäle und KOs zuordnen» prüfen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._assign_channels([i.device for i in unsure
                                   if i.device.device_type in ("actor", "gateway")]
                                  or devices)

    def _offer_channel_assignment(self, entry: MaterialEntry, devices: list) -> None:
        """Nach der Produktzuweisung: hat das Produkt KOs je Kanal, die
        Zuordnung gleich anbieten."""
        from ...services.actor_channels import channel_names
        devices = [d for d in devices if d.device_type in ("actor", "gateway")
                   and channel_names(d)]
        if not devices:
            return
        names = list(channel_names(devices[0]).values())
        answer = QMessageBox.question(
            self, "Kanäle zuordnen",
            f"{entry.product_name or entry.order_number} hat {len(names)} Kanäle "
            f"({names[0]} – {names[-1]}).\nStromkreise und KOs jetzt zuordnen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._assign_channels(devices)

    def _update_device_product(self, entry: MaterialEntry,
                               prod: ProductSuggestion) -> list:
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

        Gibt die aktualisierten Geräte zurück.
        """
        from ...services.product_sync import communication_objects_of

        updated: list = []
        be_by_addr = {
            be.participant_number: be
            for room in self._project.all_rooms
            for be in room.bedienelemente
            if be.participant_number
        }

        def _apply(device: Device) -> None:
            if (device.manufacturer, device.order_number) != (prod.manufacturer,
                                                              prod.order_number):
                # Kanal-/KO-Zuordnung gehörte zum bisherigen Produkt
                device.channel_map, device.co_map = {}, {}
            device.apply_product(prod)
            updated.append(device)
            if prod.com_objects:
                device.communication_objects = communication_objects_of(prod.com_objects)
                # Gemerkte KO-Texte aus ETS-Projekten (FA-1411d)
                from ...services.ko_names import apply_to_device
                apply_to_device(device)
            be = be_by_addr.get(device.physical_address)
            if prod.channels and be:
                be.channels = prod.channels
            if be:
                # Tastenzahl aus den KOs bzw. dem Namen («1-8fach», FA-1411)
                from ...services.product_capabilities import fit_taster_channels
                fit_taster_channels(self._project, be)

        addr_set = set(entry.physical_addresses)
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.physical_address in addr_set:
                        _apply(device)
                    elif entry.device_id and device.id == entry.device_id:
                        _apply(device)
        return updated

    def _offer_device_product(self, devices: list) -> None:
        """Sensor-Produkt auch für die GAs seiner Gewerk-Elemente übernehmen
        (Auswahl der KOs mit eigener GA); danach Aktoren/Sensoren und GAs neu
        berechnen."""
        from ..dialogs.product_sync_dialog import offer_device_product
        if self._project and offer_device_product(self, self._project, devices):
            bus = getattr(self, "_bus", None)
            if bus:
                bus.emit_functions_changed()

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
            initial_device_type=chosen_type,
            for_assignment=True,
        )
        dialog.setWindowTitle(self._product_dialog_title(entries_to_assign, chosen_type))
        if not dialog.has_type_preselection():
            dialog._search_edit.setText(chosen_type)

        if not dialog.exec():
            return

        prod = dialog.selected_product
        if not prod:
            return
        prod = self._prefer_variant_with_kos(prod)

        # Kanaldefizit prüfen (am Typ, da alle Einträge denselben Typ haben);
        # Aktoren werden unten automatisch aufgeteilt
        required = parse_channel_count(chosen_type)
        if required > 0 and 0 < prod.channels < required and any(
                e.category != "Aktor" for e in entries_to_assign):
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

        # Alle Einträge dieses Typs zuweisen; Aktoren mit Kanaldefizit
        # automatisch auf die nötige Anzahl Geräte aufteilen
        devices: list = []
        split = 0
        for entry in list(entries_to_assign):
            entry.manufacturer = prod.manufacturer
            entry.order_number = prod.order_number
            entry.product_name = prod.product_name
            entry.assigned_channels = prod.channels
            entry.secure_supported = prod.secure_supported
            entry.ga_min = prod.ga_min
            entry.ga_max = prod.ga_max
            entry.ga_override = None  # gehörte zum bisherigen Produkt
            units = self._units_needed(entry, prod) if self._project else 0
            if units > 1:
                new_entries = self._split_actor(entry, units)
                if new_entries:
                    split += 1
                    devices += [d for new_entry in new_entries
                                for d in self._update_device_product(new_entry, prod)]
                    continue
            if self._project:
                devices += self._update_device_product(entry, prod)

        QMessageBox.information(
            self,
            "Batch-Zuweisung abgeschlossen",
            f"{len(entries_to_assign)} Platzhalter vom Typ «{chosen_type}»\n"
            f"wurden mit «{prod.product_name or prod.order_number}» belegt."
            + (f"\n\n{split} davon wegen zu weniger Kanäle auf mehrere Geräte "
               "aufgeteilt, physikalische Adressen neu vergeben." if split else ""),
        )
        self._rebuild_table()
        self.list_changed.emit()
        self._offer_device_product(devices)
        self._auto_assign_kos(None, devices)

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
