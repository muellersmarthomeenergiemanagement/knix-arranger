"""
DALI-Konfigurationsansicht (FA-2801).

Zeigt alle DALI-Gateways des Projekts und ermöglicht die Konfiguration
von EVGs, Gruppen, Szenen und KNX-GA-Verknüpfungen pro Gateway.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTableWidget, QTableWidgetItem, QGroupBox, QTabWidget,
    QLineEdit, QSpinBox, QCheckBox, QComboBox, QHeaderView, QAbstractItemView,
    QSplitter, QFormLayout, QMessageBox, QDialog, QDialogButtonBox,
)
from PySide6.QtCore import Qt
from ...models.project import KnxProject
from ...models.dali_config import DaliGateway, DaliDevice, DaliGroup, DaliScene, EMERGENCY_MODES
from ...services.dali_service import DaliService
from ..column_utils import fit_columns

# Spalten EVG-Tabelle
_C_ADDR  = 0
_C_NAME  = 1
_C_TYPE  = 2
_C_ROOM  = 3
_C_GRPS  = 4
_C_EMRG  = 5
_C_EMODE = 6
_C_EVG_COLS = 7

# Spalten Gruppen-Tabelle
_CG_NR     = 0
_CG_NAME   = 1
_CG_DEVS   = 2
_CG_SWITCH = 3
_CG_DIM    = 4
_CG_VALUE  = 5
_CG_COLS   = 6


class DaliConfigView(QWidget):
    """Hauptansicht für DALI-Konfiguration (FA-2801)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._service = DaliService()
        self._current_gw: DaliGateway | None = None

        layout = QVBoxLayout(self)

        title = QLabel("<b>DALI-Konfiguration</b>")
        title.setStyleSheet("font-size: 14px;")
        layout.addWidget(title)

        info = QLabel(
            "Pro DALI-Gateway können bis zu 64 Betriebsgeräte (EVGs) und bis zu "
            "16 Gruppen konfiguriert werden. Die KNX-Gruppenadressen werden automatisch "
            "aus der GA-Struktur verknüpft."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._no_gw_label = QLabel(
            "Keine DALI-Gateways im Projekt gefunden.\n"
            "Fügen Sie in Wizard Schritt 5 das Gewerk 'LDA' (DALI) hinzu "
            "und berechnen Sie die Topologie (Schritt 6)."
        )
        self._no_gw_label.setWordWrap(True)
        self._no_gw_label.setStyleSheet("color: #888; font-style: italic; padding: 16px;")
        layout.addWidget(self._no_gw_label)

        splitter = QSplitter(Qt.Horizontal)

        # ── Links: Gateway-Liste ──────────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("DALI-Gateways:"))
        self._gw_list = QListWidget()
        self._gw_list.currentRowChanged.connect(self._on_gw_selected)
        left_layout.addWidget(self._gw_list)

        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.setToolTip("Gateways aus Topologie neu einlesen")
        self._btn_refresh.clicked.connect(self.refresh)
        left_layout.addWidget(self._btn_refresh)

        self._btn_link_gas = QPushButton("GAs automatisch verknüpfen")
        self._btn_link_gas.setToolTip(
            "Passende KNX-GAs automatisch dem gewählten Gateway zuordnen (FA-2803)"
        )
        self._btn_link_gas.clicked.connect(self._auto_link_gas)
        left_layout.addWidget(self._btn_link_gas)

        splitter.addWidget(left)

        # ── Rechts: Detail-Tabs ───────────────────────────────────────────────
        self._detail = QTabWidget()

        # Tab: Betriebsgeräte (EVGs)
        self._detail.addTab(self._build_evg_tab(), "Betriebsgeräte (EVG)")
        # Tab: Gruppen
        self._detail.addTab(self._build_groups_tab(), "Gruppen")
        # Tab: Szenen
        self._detail.addTab(self._build_scenes_tab(), "Szenen")
        # Tab: KNX-GAs
        self._detail.addTab(self._build_ga_tab(), "KNX-Gruppenadressen")

        splitter.addWidget(self._detail)
        splitter.setSizes([200, 600])
        layout.addWidget(splitter, 1)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def refresh(self):
        """Liest Gateways aus Topologie neu ein und aktualisiert die Anzeige."""
        self._gw_list.clear()
        gateways = self._service.get_dali_gateways_from_topology(self._project)

        # Nur Gateways anzeigen, die aktuell in der Topologie vorhanden sind.
        # Veraltete dali_configs (z.B. aus früheren Imports) werden ignoriert.
        for device in gateways:
            cfg = self._service.get_or_create(
                self._project, device.id,
                name=device.product_name or device.product or "DALI-Gateway"
            )
            phys = device.physical_address or ""
            label = f"{cfg.name}  [{phys}]" if phys else cfg.name
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, cfg)
            self._gw_list.addItem(item)

        has_gw = self._gw_list.count() > 0
        self._no_gw_label.setVisible(not has_gw)
        self._detail.setVisible(has_gw)
        self._btn_link_gas.setEnabled(has_gw)

        if has_gw:
            self._gw_list.setCurrentRow(0)

    def set_project(self, project: KnxProject):
        self._project = project
        self.refresh()

    # ── Gateway-Auswahl ───────────────────────────────────────────────────────

    def _on_gw_selected(self, row: int):
        item = self._gw_list.item(row)
        self._current_gw = item.data(Qt.UserRole) if item else None
        self._populate_tabs()

    def _populate_tabs(self):
        gw = self._current_gw
        if not gw:
            return
        self._populate_evg_table(gw)
        self._populate_groups_table(gw)
        self._populate_scenes_table(gw)
        self._populate_ga_tab(gw)

    # ── EVG-Tab ───────────────────────────────────────────────────────────────

    def _build_evg_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self._evg_table = QTableWidget()
        self._evg_table.setColumnCount(_C_EVG_COLS)
        self._evg_table.setHorizontalHeaderLabels([
            "Adr.", "Name", "EVG-Typ", "Raum", "Gruppen", "Notlicht", "Notlicht-Modus"
        ])
        self._evg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._evg_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._evg_table)

        btn_row = QHBoxLayout()
        self._btn_add_evg = QPushButton("+ EVG")
        self._btn_add_evg.clicked.connect(self._add_evg)
        self._btn_remove_evg = QPushButton("Entfernen")
        self._btn_remove_evg.setObjectName("danger")
        self._btn_remove_evg.clicked.connect(self._remove_evg)
        self._btn_edit_evg = QPushButton("Bearbeiten...")
        self._btn_edit_evg.clicked.connect(self._edit_evg)
        btn_row.addWidget(self._btn_add_evg)
        btn_row.addWidget(self._btn_remove_evg)
        btn_row.addWidget(self._btn_edit_evg)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    def _populate_evg_table(self, gw: DaliGateway):
        room_map = {r.id: r.name for r in self._project.all_rooms}
        self._evg_table.setRowCount(len(gw.devices))
        for i, dev in enumerate(sorted(gw.devices, key=lambda d: d.short_address)):
            group_names = []
            for g_nr in sorted(dev.group_memberships):
                grp = next((g for g in gw.groups if g.number == g_nr), None)
                group_names.append(grp.name if grp and grp.name else str(g_nr))

            self._evg_table.setItem(i, _C_ADDR, QTableWidgetItem(str(dev.short_address)))
            self._evg_table.setItem(i, _C_NAME, QTableWidgetItem(dev.name))
            self._evg_table.setItem(i, _C_TYPE, QTableWidgetItem(dev.evg_type))
            self._evg_table.setItem(i, _C_ROOM, QTableWidgetItem(room_map.get(dev.room_id, "")))
            self._evg_table.setItem(i, _C_GRPS, QTableWidgetItem(", ".join(group_names)))
            emrg_item = QTableWidgetItem("Ja" if dev.is_emergency else "Nein")
            emrg_item.setData(Qt.UserRole, dev)
            self._evg_table.setItem(i, _C_EMRG, emrg_item)
            self._evg_table.setItem(
                i, _C_EMODE,
                QTableWidgetItem(EMERGENCY_MODES.get(dev.emergency_mode, "") if dev.is_emergency else "")
            )
        fit_columns(self._evg_table)

    def _add_evg(self):
        gw = self._current_gw
        if not gw:
            return
        if len(gw.devices) >= 64:
            QMessageBox.warning(self, "Limit erreicht", "Maximal 64 Betriebsgeräte pro Gateway.")
            return
        used = {d.short_address for d in gw.devices}
        next_addr = next((a for a in range(64) if a not in used), None)
        if next_addr is None:
            return
        dev = DaliDevice(short_address=next_addr, name=f"EVG {next_addr}")
        gw.devices.append(dev)
        self._populate_evg_table(gw)

    def _remove_evg(self):
        gw = self._current_gw
        if not gw:
            return
        rows = {idx.row() for idx in self._evg_table.selectionModel().selectedRows()}
        if not rows:
            return
        sorted_devs = sorted(gw.devices, key=lambda d: d.short_address)
        for row in sorted(rows, reverse=True):
            if row < len(sorted_devs):
                gw.devices.remove(sorted_devs[row])
        self._populate_evg_table(gw)

    def _edit_evg(self):
        gw = self._current_gw
        if not gw:
            return
        rows = list({idx.row() for idx in self._evg_table.selectionModel().selectedRows()})
        if len(rows) != 1:
            QMessageBox.information(self, "Hinweis", "Bitte genau ein EVG auswählen.")
            return
        item = self._evg_table.item(rows[0], _C_EMRG)
        if not item:
            return
        dev: DaliDevice = item.data(Qt.UserRole)
        dlg = _EvgEditDialog(dev, gw.groups, self._project.all_rooms, self)
        if dlg.exec() == QDialog.Accepted:
            self._populate_evg_table(gw)
            self._service.sync_groups_from_devices(gw)
            self._populate_groups_table(gw)

    # ── Gruppen-Tab ───────────────────────────────────────────────────────────

    def _build_groups_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self._groups_table = QTableWidget()
        self._groups_table.setColumnCount(_CG_COLS)
        self._groups_table.setHorizontalHeaderLabels([
            "Nr.", "Name", "Geräte (Adressen)", "GA Schalten", "GA Dimmen", "GA Wert"
        ])
        self._groups_table.horizontalHeader().setSectionResizeMode(
            _CG_NAME, QHeaderView.Stretch
        )
        layout.addWidget(self._groups_table)

        btn_row = QHBoxLayout()
        self._btn_add_grp = QPushButton("+ Gruppe")
        self._btn_add_grp.clicked.connect(self._add_group)
        self._btn_remove_grp = QPushButton("Entfernen")
        self._btn_remove_grp.setObjectName("danger")
        self._btn_remove_grp.clicked.connect(self._remove_group)
        btn_row.addWidget(self._btn_add_grp)
        btn_row.addWidget(self._btn_remove_grp)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    def _populate_groups_table(self, gw: DaliGateway):
        self._service.sync_groups_from_devices(gw)
        self._groups_table.setRowCount(len(gw.groups))
        for i, grp in enumerate(sorted(gw.groups, key=lambda g: g.number)):
            nr_item = QTableWidgetItem(str(grp.number))
            nr_item.setData(Qt.UserRole, grp)
            self._groups_table.setItem(i, _CG_NR, nr_item)
            self._groups_table.setItem(i, _CG_NAME, QTableWidgetItem(grp.name))
            self._groups_table.setItem(
                i, _CG_DEVS,
                QTableWidgetItem(", ".join(str(a) for a in sorted(grp.device_addresses)))
            )
            self._groups_table.setItem(i, _CG_SWITCH, QTableWidgetItem(grp.ga_switch))
            self._groups_table.setItem(i, _CG_DIM,    QTableWidgetItem(grp.ga_dim))
            self._groups_table.setItem(i, _CG_VALUE,  QTableWidgetItem(grp.ga_value))
        fit_columns(self._groups_table)

    def _add_group(self):
        gw = self._current_gw
        if not gw:
            return
        if len(gw.groups) >= 16:
            QMessageBox.warning(self, "Limit erreicht", "Maximal 16 Gruppen pro Gateway.")
            return
        used = {g.number for g in gw.groups}
        nr = next((n for n in range(16) if n not in used), None)
        if nr is None:
            return
        gw.groups.append(DaliGroup(number=nr, name=f"Gruppe {nr}"))
        self._populate_groups_table(gw)

    def _remove_group(self):
        gw = self._current_gw
        if not gw:
            return
        rows = {idx.row() for idx in self._groups_table.selectionModel().selectedRows()}
        sorted_grps = sorted(gw.groups, key=lambda g: g.number)
        for row in sorted(rows, reverse=True):
            if row < len(sorted_grps):
                gw.groups.remove(sorted_grps[row])
        self._populate_groups_table(gw)

    # ── Szenen-Tab ────────────────────────────────────────────────────────────

    def _build_scenes_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self._scenes_table = QTableWidget()
        self._scenes_table.setColumnCount(2)
        self._scenes_table.setHorizontalHeaderLabels(["Nr.", "Name"])
        self._scenes_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._scenes_table)

        btn_row = QHBoxLayout()
        self._btn_add_scene = QPushButton("+ Szene")
        self._btn_add_scene.clicked.connect(self._add_scene)
        self._btn_remove_scene = QPushButton("Entfernen")
        self._btn_remove_scene.setObjectName("danger")
        self._btn_remove_scene.clicked.connect(self._remove_scene)
        self._btn_default_scenes = QPushButton("Standard-Szenen")
        self._btn_default_scenes.setToolTip("Szenen 0–3 mit Standardnamen anlegen")
        self._btn_default_scenes.clicked.connect(self._add_default_scenes)
        btn_row.addWidget(self._btn_add_scene)
        btn_row.addWidget(self._btn_remove_scene)
        btn_row.addWidget(self._btn_default_scenes)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    def _populate_scenes_table(self, gw: DaliGateway):
        self._scenes_table.setRowCount(len(gw.scenes))
        for i, sc in enumerate(sorted(gw.scenes, key=lambda s: s.number)):
            nr_item = QTableWidgetItem(str(sc.number))
            nr_item.setData(Qt.UserRole, sc)
            self._scenes_table.setItem(i, 0, nr_item)
            self._scenes_table.setItem(i, 1, QTableWidgetItem(sc.name))

    def _add_scene(self):
        gw = self._current_gw
        if not gw:
            return
        if len(gw.scenes) >= 16:
            QMessageBox.warning(self, "Limit erreicht", "Maximal 16 Szenen.")
            return
        used = {s.number for s in gw.scenes}
        nr = next((n for n in range(16) if n not in used), None)
        if nr is None:
            return
        gw.scenes.append(DaliScene(number=nr, name=f"Szene {nr}"))
        self._populate_scenes_table(gw)

    def _remove_scene(self):
        gw = self._current_gw
        if not gw:
            return
        rows = {idx.row() for idx in self._scenes_table.selectionModel().selectedRows()}
        sorted_scenes = sorted(gw.scenes, key=lambda s: s.number)
        for row in sorted(rows, reverse=True):
            if row < len(sorted_scenes):
                gw.scenes.remove(sorted_scenes[row])
        self._populate_scenes_table(gw)

    def _add_default_scenes(self):
        gw = self._current_gw
        if not gw:
            return
        DaliService.ensure_default_scenes(gw)
        self._populate_scenes_table(gw)

    # ── KNX-GA-Tab ────────────────────────────────────────────────────────────

    def _build_ga_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        self._ga_switch = QLineEdit()
        self._ga_switch.setPlaceholderText("x/x/x")
        self._ga_switch.editingFinished.connect(self._save_gas)
        form.addRow("Schalten (Broadcast):", self._ga_switch)

        self._ga_dim = QLineEdit()
        self._ga_dim.setPlaceholderText("x/x/x")
        self._ga_dim.editingFinished.connect(self._save_gas)
        form.addRow("Dimmen (Broadcast):", self._ga_dim)

        self._ga_scene = QLineEdit()
        self._ga_scene.setPlaceholderText("x/x/x")
        self._ga_scene.editingFinished.connect(self._save_gas)
        form.addRow("Szenenabruf:", self._ga_scene)

        self._ga_status_value = QLineEdit()
        self._ga_status_value.setPlaceholderText("x/x/x")
        self._ga_status_value.editingFinished.connect(self._save_gas)
        form.addRow("Status Istwert:", self._ga_status_value)

        self._ga_status_fault = QLineEdit()
        self._ga_status_fault.setPlaceholderText("x/x/x")
        self._ga_status_fault.editingFinished.connect(self._save_gas)
        form.addRow("Status Störung:", self._ga_status_fault)

        layout.addLayout(form)
        layout.addStretch()
        return w

    def _populate_ga_tab(self, gw: DaliGateway):
        self._ga_switch.setText(gw.ga_switch_broadcast)
        self._ga_dim.setText(gw.ga_dim_broadcast)
        self._ga_scene.setText(gw.ga_scene)
        self._ga_status_value.setText(gw.ga_status_value)
        self._ga_status_fault.setText(gw.ga_status_fault)

    def _save_gas(self):
        gw = self._current_gw
        if not gw:
            return
        gw.ga_switch_broadcast = self._ga_switch.text().strip()
        gw.ga_dim_broadcast = self._ga_dim.text().strip()
        gw.ga_scene = self._ga_scene.text().strip()
        gw.ga_status_value = self._ga_status_value.text().strip()
        gw.ga_status_fault = self._ga_status_fault.text().strip()

    def _auto_link_gas(self):
        gw = self._current_gw
        if not gw:
            return
        n = self._service.link_gas_from_structure(gw, self._project)
        self._populate_ga_tab(gw)
        QMessageBox.information(
            self, "GAs verknüpft",
            f"{n} KNX-Gruppenadresse(n) automatisch dem Gateway zugeordnet."
            if n else "Keine passenden GAs gefunden."
        )


# ── Hilfsdialog: EVG bearbeiten ───────────────────────────────────────────────

class _EvgEditDialog(QDialog):
    """Dialog zum Bearbeiten eines einzelnen DALI-EVGs."""

    def __init__(self, dev: DaliDevice, groups: list[DaliGroup], rooms, parent=None):
        super().__init__(parent)
        self._dev = dev
        self.setWindowTitle(f"EVG {dev.short_address} bearbeiten")
        self.resize(400, 350)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._addr_spin = QSpinBox()
        self._addr_spin.setRange(0, 63)
        self._addr_spin.setValue(dev.short_address)
        form.addRow("DALI-Kurzadresse (0–63):", self._addr_spin)

        self._name_edit = QLineEdit(dev.name)
        form.addRow("Name:", self._name_edit)

        self._type_edit = QLineEdit(dev.evg_type)
        self._type_edit.setPlaceholderText("z.B. LED, Fluoreszenz, Notlicht")
        form.addRow("EVG-Typ:", self._type_edit)

        self._room_combo = QComboBox()
        self._room_combo.addItem("(kein Raum)", "")
        for room in sorted(rooms, key=lambda r: r.name):
            self._room_combo.addItem(f"{room.number} {room.name}", room.id)
        idx = self._room_combo.findData(dev.room_id)
        if idx >= 0:
            self._room_combo.setCurrentIndex(idx)
        form.addRow("Raum:", self._room_combo)

        self._emrg_check = QCheckBox("Notlicht-EVG (FA-2804)")
        self._emrg_check.setChecked(dev.is_emergency)
        form.addRow("Notlicht:", self._emrg_check)

        self._emode_combo = QComboBox()
        for key, label in EMERGENCY_MODES.items():
            self._emode_combo.addItem(label, key)
        idx_m = self._emode_combo.findData(dev.emergency_mode)
        if idx_m >= 0:
            self._emode_combo.setCurrentIndex(idx_m)
        form.addRow("Notlicht-Modus:", self._emode_combo)

        layout.addLayout(form)

        # Gruppen-Zuweisung
        grp_box = QGroupBox("Gruppen-Zugehörigkeit (0–15)")
        grp_layout = QVBoxLayout()
        self._grp_checks: list[tuple[int, QCheckBox]] = []
        for grp in sorted(groups, key=lambda g: g.number):
            cb = QCheckBox(f"Gruppe {grp.number}: {grp.name}")
            cb.setChecked(grp.number in dev.group_memberships)
            grp_layout.addWidget(cb)
            self._grp_checks.append((grp.number, cb))
        grp_box.setLayout(grp_layout)
        layout.addWidget(grp_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        self._dev.short_address = self._addr_spin.value()
        self._dev.name = self._name_edit.text().strip()
        self._dev.evg_type = self._type_edit.text().strip()
        self._dev.room_id = self._room_combo.currentData() or ""
        self._dev.is_emergency = self._emrg_check.isChecked()
        self._dev.emergency_mode = self._emode_combo.currentData() or "auto"
        self._dev.group_memberships = [
            nr for nr, cb in self._grp_checks if cb.isChecked()
        ]
        self.accept()
