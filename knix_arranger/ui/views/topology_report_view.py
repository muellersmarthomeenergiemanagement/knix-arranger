"""
Topologie-Report-Ansichten (FA-1009 bis FA-1011)
"""
from __future__ import annotations
from collections import defaultdict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QTabWidget, QComboBox, QLineEdit,
    QRadioButton, QButtonGroup, QFrame, QStackedWidget, QPushButton,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from ...models.project import KnxProject
from ...models.topology import Topology
from ...services.belegungsplan_service import _split_button_channel
from ..column_utils import fit_columns


class TopologyReportView(QWidget):
    """Erweiterte Topologie-Ansichten: Geräte, KO, Kreuzreferenz."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None

        layout = QVBoxLayout(self)

        title = QLabel("Topologie-Report")
        title.setObjectName("title")
        layout.addWidget(title)

        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._create_device_tab(), "Geräte-Detail (FA-1009)")
        self._tabs.addTab(self._create_ko_tab(), "Kommunikationsobjekte (FA-1010)")
        self._tabs.addTab(self._create_crossref_tab(), "Kreuzreferenz (FA-1011)")
        self._tabs.addTab(self._create_bedienelement_tab(), "Bedienelemente (FA-1404)")
        layout.addWidget(self._tabs)

    # ── Hinweis-Banner (kein ETS-Import) ──

    @staticmethod
    def _create_no_data_widget(msg: str) -> QWidget:
        """Zeigt einen Hinweis-Banner wenn keine KO-Daten vorhanden sind."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)

        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet(
            "QFrame { background:#FFF8E1; border:1px solid #F9A825; border-radius:6px; padding:12px; }"
        )
        inner = QVBoxLayout(frame)

        icon = QLabel("ℹ️")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size:28px;")
        inner.addWidget(icon)

        text = QLabel(msg)
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        text.setStyleSheet("color:#5D4037; font-size:13px;")
        inner.addWidget(text)

        layout.addStretch()
        layout.addWidget(frame)
        layout.addStretch()
        return w

    # ── Geräte-Detail-Tab (FA-1009) ──

    def _create_device_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Linie:"))
        self._line_filter = QComboBox()
        self._line_filter.currentIndexChanged.connect(self._on_line_changed)
        filter_layout.addWidget(self._line_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self._device_table = QTableWidget()
        self._device_table.setColumnCount(6)
        self._device_table.setHorizontalHeaderLabels([
            "Phys. Adresse", "Hersteller", "Produkt",
            "Applikation", "Einbauort", "Typ",
        ])
        self._device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._device_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._device_table.horizontalHeader().setStretchLastSection(True)
        self._device_table.setAlternatingRowColors(True)
        layout.addWidget(self._device_table)

        return widget

    # ── Kommunikationsobjekte-Tab (FA-1010) ──

    def _create_ko_tab(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self._ko_stack = QStackedWidget()

        # Seite 0 – Hinweis (kein ETS-Import)
        self._ko_stack.addWidget(self._create_no_data_widget(
            "Keine Kommunikationsobjekte vorhanden.\n\n"
            "Diese Ansicht wird befüllt, wenn ein ETS-Topologie-Report importiert wurde\n"
            "(Datei → Importieren → ETS6 Topologie-Report XLSX oder .knxproj)."
        ))

        # Seite 1 – Inhalt
        content = QWidget()
        layout = QVBoxLayout(content)

        # Linienfilter → Device-Dropdown
        line_row = QHBoxLayout()
        line_row.addWidget(QLabel("Linie:"))
        self._ko_line_filter = QComboBox()
        self._ko_line_filter.currentIndexChanged.connect(self._on_ko_line_changed)
        line_row.addWidget(self._ko_line_filter)
        line_row.addSpacing(16)
        line_row.addWidget(QLabel("Gerät:"))
        self._device_filter = QComboBox()
        self._device_filter.currentIndexChanged.connect(self._on_device_changed)
        line_row.addWidget(self._device_filter, stretch=1)
        layout.addLayout(line_row)

        # Suchfeld
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Suche:"))
        self._ko_search = QLineEdit()
        self._ko_search.setPlaceholderText("KO-Name oder Funktion filtern …")
        self._ko_search.textChanged.connect(self._on_ko_search_changed)
        search_row.addWidget(self._ko_search)
        layout.addLayout(search_row)

        self._ko_table = QTableWidget()
        self._ko_table.setColumnCount(6)
        self._ko_table.setHorizontalHeaderLabels([
            "Nr.", "Name", "Funktion", "Datentyp", "Flags", "Verbundene GAs",
        ])
        self._ko_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._ko_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._ko_table.horizontalHeader().setStretchLastSection(True)
        self._ko_table.setAlternatingRowColors(True)
        self._ko_table.cellDoubleClicked.connect(self._on_ko_cell_double_clicked)
        layout.addWidget(self._ko_table)

        layout.addWidget(QLabel(
            "Grau = Kommunikationsobjekt ohne verbundene Gruppenadresse. "
            "Doppelklick auf 'Verbundene GAs'-Zelle → Kreuzreferenz."
        ))

        self._ko_stack.addWidget(content)
        outer_layout.addWidget(self._ko_stack)
        return outer

    # ── Bedienelemente-Tab (FA-1404) ──

    def _create_bedienelement_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel(
            "Bedienelemente pro Linie mit GA-Funktionszuordnungen (Taste / Kanal → GA)."
        ))

        self._be_fallback_info = QLabel(
            "ℹ️  Orange Zeilen: Sensorfunktionen ohne vollständige GA-Zuordnung "
            "(Wizard Schritt 9 noch nicht ausgeführt oder XLSX-Import ohne passende GA-Bezeichnungen)."
        )
        self._be_fallback_info.setWordWrap(True)
        self._be_fallback_info.setStyleSheet(
            "color: #7B3B00; background: #FFF3E0; "
            "border: 1px solid #FFCC80; border-radius: 4px; padding: 4px 8px;"
        )
        self._be_fallback_info.setVisible(False)
        layout.addWidget(self._be_fallback_info)

        self._be_table = QTableWidget()
        self._be_table.setColumnCount(6)
        self._be_table.setHorizontalHeaderLabels([
            "Raum", "Gerätetyp", "Taste", "Kanal", "Funktion", "GA",
        ])
        self._be_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._be_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._be_table.horizontalHeader().setStretchLastSection(True)
        self._be_table.setAlternatingRowColors(True)
        layout.addWidget(self._be_table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_export_belegungsplan = QPushButton("Als ETS-Belegungsplan exportieren (.xlsx)")
        self._btn_export_belegungsplan.setToolTip(
            "Exportiert einen strukturierten Belegungsplan mit allen GA-Zuordnungen\n"
            "als Vorlage für die ETS-Programmierung."
        )
        self._btn_export_belegungsplan.clicked.connect(self._export_belegungsplan)
        btn_row.addWidget(self._btn_export_belegungsplan)
        layout.addLayout(btn_row)

        return widget

    # ── Kreuzreferenz-Tab (FA-1011) ──

    def _create_crossref_tab(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self._crossref_stack = QStackedWidget()

        # Seite 0 – Hinweis (kein ETS-Import)
        self._crossref_stack.addWidget(self._create_no_data_widget(
            "Keine Kreuzreferenz-Daten vorhanden.\n\n"
            "Diese Ansicht wird befüllt, wenn ein ETS-Topologie-Report importiert wurde\n"
            "(Datei → Importieren → ETS6 Topologie-Report XLSX oder .knxproj)."
        ))

        # Seite 1 – Inhalt
        content = QWidget()
        layout = QVBoxLayout(content)

        # Richtungs-Umschalter
        dir_row = QHBoxLayout()
        self._crossref_btn_group = QButtonGroup(content)
        self._radio_ga_to_dev = QRadioButton("GA → Geräte")
        self._radio_dev_to_ga = QRadioButton("Gerät → GAs")
        self._radio_ga_to_dev.setChecked(True)
        self._crossref_btn_group.addButton(self._radio_ga_to_dev, 0)
        self._crossref_btn_group.addButton(self._radio_dev_to_ga, 1)
        self._crossref_btn_group.idClicked.connect(self._on_crossref_direction_changed)
        dir_row.addWidget(self._radio_ga_to_dev)
        dir_row.addWidget(self._radio_dev_to_ga)
        dir_row.addSpacing(24)
        dir_row.addWidget(QLabel("Suche:"))
        self._crossref_search = QLineEdit()
        self._crossref_search.setPlaceholderText("GA-Adresse oder Gerätename filtern …")
        self._crossref_search.textChanged.connect(self._refresh_crossref)
        dir_row.addWidget(self._crossref_search, stretch=1)
        layout.addLayout(dir_row)

        self._crossref_tree = QTreeWidget()
        self._crossref_tree.itemExpanded.connect(lambda _: fit_columns(self._crossref_tree))
        self._crossref_tree.setHeaderLabels([
            "GA / Gerät", "Objekt", "Funktion", "Datentyp",
        ])
        self._crossref_tree.setAlternatingRowColors(True)
        self._crossref_tree.itemDoubleClicked.connect(self._on_crossref_double_clicked)
        layout.addWidget(self._crossref_tree)

        layout.addWidget(QLabel(
            "Doppelklick auf ein Gerät → wechselt zum KO-Tab mit diesem Gerät selektiert."
        ))

        self._crossref_stack.addWidget(content)
        outer_layout.addWidget(self._crossref_stack)
        return outer

    # ── Public ──

    def set_project(self, project: KnxProject):
        self._project = project
        self._refresh_all()

    def _refresh_all(self):
        if not self._project:
            self._info.setText("")
            self._ko_stack.setCurrentIndex(0)
            self._crossref_stack.setCurrentIndex(0)
            return

        topology = self._project.topology
        total_devices = sum(
            len(line.devices)
            for area in topology.areas
            for line in area.lines
        )
        has_cos = any(
            device.communication_objects
            for area in topology.areas
            for line in area.lines
            for device in line.devices
        )
        self._info.setText(
            f"{len(topology.areas)} Bereiche, {total_devices} Geräte"
            + ("" if has_cos else " – noch kein ETS-Report importiert")
        )

        # Stacks: Hinweis (0) oder Inhalt (1)
        self._ko_stack.setCurrentIndex(1 if has_cos else 0)
        self._crossref_stack.setCurrentIndex(1 if has_cos else 0)

        self._refresh_line_filter()
        if has_cos:
            self._refresh_ko_line_filter()
            self._refresh_crossref()
        self._refresh_bedienelemente()

    # ── Geräte-Detail ──

    def _refresh_line_filter(self):
        self._line_filter.blockSignals(True)
        self._line_filter.clear()
        self._line_filter.addItem("Alle Linien", None)
        if self._project:
            for area in self._project.topology.areas:
                for line in area.lines:
                    label = f"Bereich {area.area_number} / Linie {line.line_number} ({line.name})"
                    self._line_filter.addItem(label, (area.area_number, line.line_number))
        self._line_filter.blockSignals(False)
        self._on_line_changed()

    def _on_line_changed(self):
        if not self._project:
            self._device_table.setRowCount(0)
            return

        filter_key = self._line_filter.currentData()
        devices = []
        for area in self._project.topology.areas:
            for line in area.lines:
                if filter_key is None or (area.area_number, line.line_number) == filter_key:
                    for device in line.devices:
                        devices.append(device)

        self._device_table.setRowCount(len(devices))
        for i, d in enumerate(devices):
            self._device_table.setItem(i, 0, QTableWidgetItem(d.physical_address))
            self._device_table.setItem(i, 1, QTableWidgetItem(d.manufacturer))
            self._device_table.setItem(i, 2, QTableWidgetItem(d.product))
            self._device_table.setItem(i, 3, QTableWidgetItem(d.application_program))
            self._device_table.setItem(i, 4, QTableWidgetItem(d.installation_location))
            self._device_table.setItem(i, 5, QTableWidgetItem(d.device_type))
        fit_columns(self._device_table)

    # ── Kommunikationsobjekte (FA-1010) ──

    def _refresh_ko_line_filter(self):
        self._ko_line_filter.blockSignals(True)
        self._ko_line_filter.clear()
        self._ko_line_filter.addItem("Alle Linien", None)
        if self._project:
            for area in self._project.topology.areas:
                for line in area.lines:
                    label = f"Bereich {area.area_number} / Linie {line.line_number} ({line.name})"
                    self._ko_line_filter.addItem(label, (area.area_number, line.line_number))
        self._ko_line_filter.blockSignals(False)
        self._on_ko_line_changed()

    def _on_ko_line_changed(self):
        """Gerät-Dropdown nach gewählter Linie befüllen."""
        self._device_filter.blockSignals(True)
        self._device_filter.clear()
        self._all_devices = []
        if self._project:
            filter_key = self._ko_line_filter.currentData()
            for area in self._project.topology.areas:
                for line in area.lines:
                    if filter_key is not None and (area.area_number, line.line_number) != filter_key:
                        continue
                    for device in line.devices:
                        label = f"{device.physical_address} – {device.product or device.device_type}"
                        self._device_filter.addItem(label, len(self._all_devices))
                        self._all_devices.append(device)
        self._device_filter.blockSignals(False)
        self._on_device_changed()

    def _on_device_changed(self):
        idx = self._device_filter.currentData()
        self._populate_ko_table(idx)

    def _on_ko_search_changed(self):
        idx = self._device_filter.currentData()
        self._populate_ko_table(idx)

    def _populate_ko_table(self, device_idx):
        if device_idx is None or not hasattr(self, "_all_devices") or device_idx >= len(self._all_devices):
            self._ko_table.setRowCount(0)
            return

        device = self._all_devices[device_idx]
        search = self._ko_search.text().lower()
        cos = [
            co for co in device.communication_objects
            if not search or search in co.name.lower() or search in co.object_function.lower()
        ]

        grey = QColor("#888888")
        self._ko_table.setRowCount(len(cos))
        for i, co in enumerate(cos):
            has_ga = bool(co.connected_gas)
            items = [
                QTableWidgetItem(str(co.object_number)),
                QTableWidgetItem(co.name),
                QTableWidgetItem(co.object_function),
                QTableWidgetItem(co.data_type),
                QTableWidgetItem(co.flags),
                QTableWidgetItem(", ".join(co.connected_gas)),
            ]
            for item in items:
                if not has_ga:
                    item.setForeground(grey)
                self._ko_table.setItem(i, items.index(item), item)
        fit_columns(self._ko_table)

    def _on_ko_cell_double_clicked(self, row: int, col: int):
        """Doppelklick auf GA-Spalte → wechselt zu Kreuzreferenz-Tab mit GA-Suche."""
        if col != 5:
            return
        item = self._ko_table.item(row, col)
        if not item or not item.text():
            return
        # Ersten GA-Wert als Suchbegriff setzen
        first_ga = item.text().split(",")[0].strip()
        self._tabs.setCurrentIndex(2)  # Kreuzreferenz-Tab
        self._radio_ga_to_dev.setChecked(True)
        self._crossref_search.setText(first_ga)

    # ── Kreuzreferenz (FA-1011) ──

    def _on_crossref_direction_changed(self, _id: int):
        self._refresh_crossref()

    def _refresh_crossref(self):
        self._crossref_tree.clear()
        if not self._project:
            return

        if self._radio_ga_to_dev.isChecked():
            self._fill_crossref_ga_to_dev()
        else:
            self._fill_crossref_dev_to_ga()

        fit_columns(self._crossref_tree)

    def _fill_crossref_ga_to_dev(self):
        """GA → Geräte: Jede GA als Wurzel, verbundene Geräte/KOs als Kinder."""
        search = self._crossref_search.text().lower()

        ga_map: dict[str, list[tuple[str, str, str, str, str]]] = {}
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    device_label = f"{device.physical_address} ({device.product or device.device_type})"
                    for co in device.communication_objects:
                        for ga in co.connected_gas:
                            if ga not in ga_map:
                                ga_map[ga] = []
                            ga_map[ga].append((
                                device_label,
                                device.physical_address,
                                f"KO {co.object_number}: {co.name}",
                                co.object_function,
                                co.data_type,
                            ))

        for ga_addr in sorted(ga_map.keys()):
            if search and search not in ga_addr.lower():
                continue
            entries = ga_map[ga_addr]
            ga_item = QTreeWidgetItem(self._crossref_tree, [
                ga_addr, f"{len(entries)} Verknüpfungen", "", "",
            ])
            ga_item.setData(0, Qt.UserRole, ("ga", ga_addr))
            for device_label, phys_addr, ko_label, func, dtype in entries:
                child = QTreeWidgetItem(ga_item, [device_label, ko_label, func, dtype])
                child.setData(0, Qt.UserRole, ("device", phys_addr))

    def _fill_crossref_dev_to_ga(self):
        """Gerät → GAs: Jedes Gerät als Wurzel, verbundene GAs als Kinder."""
        search = self._crossref_search.text().lower()

        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    device_label = f"{device.physical_address} – {device.product or device.device_type}"
                    if search and search not in device_label.lower():
                        continue
                    # Nur Geräte mit mindestens einer verbundenen GA anzeigen
                    linked_cos = [co for co in device.communication_objects if co.connected_gas]
                    if not linked_cos:
                        continue
                    dev_item = QTreeWidgetItem(self._crossref_tree, [
                        device_label,
                        f"{sum(len(co.connected_gas) for co in linked_cos)} GAs",
                        "", "",
                    ])
                    dev_item.setData(0, Qt.UserRole, ("device", device.physical_address))
                    for co in linked_cos:
                        for ga in co.connected_gas:
                            child = QTreeWidgetItem(dev_item, [
                                ga,
                                f"KO {co.object_number}: {co.name}",
                                co.object_function,
                                co.data_type,
                            ])
                            child.setData(0, Qt.UserRole, ("ga", ga))

    def _on_crossref_double_clicked(self, item: QTreeWidgetItem, _col: int):
        """Doppelklick auf Gerät → KO-Tab; Doppelklick auf GA → GA-Ansicht."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, value = data
        if kind == "device":
            # Zum KO-Tab wechseln und Gerät selektieren
            self._tabs.setCurrentIndex(1)
            for i in range(self._device_filter.count()):
                if value in self._device_filter.itemText(i):
                    self._device_filter.setCurrentIndex(i)
                    break
        elif kind == "ga":
            # In GA-Richtung wechseln und suchen
            self._radio_ga_to_dev.setChecked(True)
            self._crossref_search.setText(value)

    # ── Bedienelemente ──

    def _refresh_bedienelemente(self):
        self._be_table.setRowCount(0)
        if not self._project:
            self._be_fallback_info.setVisible(False)
            return

        # Stockwerk-Code-Lookup: floor.id → short_code (z.B. "OG")
        floor_code_by_id: dict[str, str] = {
            fl.id: fl.short_code for fl in self._project.all_floors
        }

        # GA-Lookup für XLSX-Importe: (gewerk_code, "FLOOR.NR") → [designation, ...]
        # Deckt Fälle ab, wo room_number aus GA-Bezeichnung als "OG.05" gespeichert ist.
        ga_by_gewerk_room: dict[tuple, list[str]] = defaultdict(list)
        for ga in self._project.group_addresses.all_addresses():
            if ga.gewerk_code and ga.room_number:
                ga_by_gewerk_room[(ga.gewerk_code, ga.room_number)].append(
                    ga.designation
                )

        room_by_id = {r.id: r for r in self._project.all_rooms}
        # Tuple: (room_cell, be_cell, taste, kanal, func, ga, is_fallback)
        rows: list[tuple] = []
        for area in self._project.topology.areas:
            for line in area.lines:
                for rid in line.assigned_room_ids:
                    room = room_by_id.get(rid)
                    if not room:
                        continue
                    for be in room.bedienelemente:
                        pn = f" [{be.participant_number}]" if be.participant_number else ""
                        room_cell = f"{room.number} {room.name}"
                        be_cell = f"{be.element_type}{pn}"
                        if be.function_assignments:
                            for fa in be.function_assignments:
                                taste, kanal = _split_button_channel(fa.button_channel)
                                rows.append((
                                    room_cell, be_cell,
                                    taste, kanal, fa.description, fa.function_ga,
                                    False,
                                ))
                        elif be.funktionen:
                            # Fallback: SensorFunktionen anzeigen wenn function_assignments fehlen
                            fc = floor_code_by_id.get(
                                getattr(room, "floor_id", ""), ""
                            )
                            room_key = (
                                f"{fc}.{room.number}" if fc else room.number
                            )
                            for idx, sf in enumerate(be.funktionen, 1):
                                if sf.ga_designation:
                                    rows.append((
                                        room_cell, be_cell,
                                        f"F{idx}", "",
                                        sf.label or sf.ga_designation,
                                        sf.ga_designation,
                                        True,
                                    ))
                                elif sf.gewerk_code:
                                    matching = ga_by_gewerk_room.get(
                                        (sf.gewerk_code, room_key), []
                                    )
                                    gas_str = " · ".join(matching) if matching else "–"
                                    gw = self._project.gewerk_catalog.get(sf.gewerk_code)
                                    fn_label = gw.name if gw else sf.gewerk_code
                                    rows.append((
                                        room_cell, be_cell,
                                        f"F{idx}", f"Elem {sf.element_number}",
                                        fn_label, gas_str,
                                        True,
                                    ))
                        else:
                            rows.append((
                                room_cell, be_cell, "–", "", "–", "–", False,
                            ))

        rows.sort(key=lambda r: r[0])  # aufsteigend nach Raum

        has_fallback = any(r[6] for r in rows)
        self._be_fallback_info.setVisible(has_fallback)

        orange = QColor("#FFF3E0")
        self._be_table.setRowCount(len(rows))
        for i, (room_name, be_type, taste, kanal, func, ga, is_fallback) in enumerate(rows):
            items = [
                QTableWidgetItem(room_name),
                QTableWidgetItem(be_type),
                QTableWidgetItem(taste),
                QTableWidgetItem(kanal),
                QTableWidgetItem(func),
                QTableWidgetItem(ga),
            ]
            for col, item in enumerate(items):
                if is_fallback:
                    item.setBackground(orange)
                self._be_table.setItem(i, col, item)
        fit_columns(self._be_table)

    # ── ETS-Belegungsplan Export ──

    def _export_belegungsplan(self):
        if not self._project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "ETS-Belegungsplan exportieren",
            f"{self._project.name or 'Belegungsplan'}_ETS.xlsx",
            "Excel-Dateien (*.xlsx)",
        )
        if not path:
            return
        try:
            from ...services.belegungsplan_service import BelegungsplanService
            from ...services.belegungsplan_export_service import BelegungsplanExportService
            data = BelegungsplanService().generate(self._project)
            BelegungsplanExportService().export_xlsx(data, path)
            QMessageBox.information(
                self, "Export erfolgreich",
                f"ETS-Belegungsplan exportiert:\n{len(data.sensor_rows)} Zeilen\n{path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export-Fehler", str(e))
