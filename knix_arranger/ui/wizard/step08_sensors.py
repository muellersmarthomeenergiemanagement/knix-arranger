"""
Wizard Schritt 9: Funktionszuordnung (FA-1410)

Weist jedem Bedienelement die passenden Gruppenadressen zu.
Geräte (Tastereinheiten, Thermostate usw.) wurden bereits in Schritt 5c
konfiguriert.  Hier wird nur noch festgelegt, welche GA welchen Kanal steuert.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QAbstractItemView, QGroupBox,
    QDialog, QDialogButtonBox, QComboBox, QFormLayout,
    QLineEdit, QListWidget, QListWidgetItem, QMenu,
)
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont, QColor, QBrush

from ...models.project import KnxProject
from ...models.building import Bedienelement, SensorFunktion
from ...models.material_list import MaterialEntry
from ...models.device import GEWERK_TO_SENSOR_TYPE
from ...services.sensor_service import (
    SensorService, GEWERK_PRIMARY_FUNCTIONS, GEWERK_FEEDBACK_FUNCTIONS,
)
from ...services.topology_engine import TopologyEngine
from ..column_utils import fit_columns


_SENSOR_TYPE_CHOICES = [
    "Tastereinheit",
    "Präsenzmelder",
    "Bewegungsmelder",
    "Raumthermostat",
    "Temperaturfühler",
    "Fensterkontakt",
    "Türkontakt",
    "Magnetkontakt",
    "Wetterstation",
    "Energiezähler",
]

_TASTER_CHANNEL_OPTIONS = ["1", "2", "4", "6"]

_COLOR_AUTO   = QColor("#1B5E20")
_COLOR_MANUAL = QColor("#E65100")


class _SensorFunktionDialog(QDialog):
    """
    Dialog zum Zuweisen von Funktionen (GAs) zu einem Bedienelement (FA-1410).

    Drei Tabs:
      1. Eigener Raum  – Gewerke des aktuellen Raums
      2. Anderer Raum  – Gewerke aus einem anderen Raum
      3. Direkte GA    – freie Eingabe einer Gruppenadresse
      4. Szene         – Szenen-GA aus der GA-Struktur
    """

    def __init__(self, be: Bedienelement, room, all_rooms: list,
                 group_addresses, all_scenes: list | None = None, parent=None):
        super().__init__(parent)
        self._be = be
        self._room = room
        self._all_rooms = all_rooms
        self._gas = group_addresses
        self._all_scenes = all_scenes or []

        self.setWindowTitle(
            f"Funktionszuordnung – {room.number} {room.name}"
        )
        self.setMinimumWidth(520)
        self.setMinimumHeight(500)

        main = QVBoxLayout(self)

        # ── Kopfzeile: Typ + Kanäle (zur Information, bearbeitbar) ────────────
        form = QFormLayout()

        self._type_combo = QComboBox()
        self._type_combo.addItems(_SENSOR_TYPE_CHOICES)
        idx = self._type_combo.findText(be.element_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        elif be.element_type:
            self._type_combo.insertItem(0, be.element_type)
            self._type_combo.setCurrentIndex(0)
        form.addRow("Gerätetyp:", self._type_combo)

        self._channel_combo = QComboBox()
        self._channel_combo.addItems(_TASTER_CHANNEL_OPTIONS)
        ch_str = str(be.channels) if be.channels in (1, 2, 4, 6) else "4"
        ch_idx = self._channel_combo.findText(ch_str)
        self._channel_combo.setCurrentIndex(max(ch_idx, 0))
        from PySide6.QtWidgets import QLabel as _QLabel
        self._channel_row_label = _QLabel("Kanalzahl:")
        form.addRow(self._channel_row_label, self._channel_combo)

        self._label_edit = QLineEdit(be.product_name or "")
        self._label_edit.setPlaceholderText("z.B. Taster Eingang, Thermostat Süd")
        form.addRow("Bezeichnung:", self._label_edit)

        main.addLayout(form)

        # ── Funktionsliste ─────────────────────────────────────────────────────
        main.addWidget(QLabel("Sensorfunktionen (je eine logische Steuereinheit):"))
        self._fn_list = QListWidget()
        self._fn_list.setMaximumHeight(150)
        self._fn_list.setAlternatingRowColors(True)
        self._fn_list.setSelectionMode(QAbstractItemView.SingleSelection)
        for sf in be.funktionen:
            self._fn_list.addItem(self._sf_label(sf))
            self._fn_list.item(self._fn_list.count() - 1).setData(Qt.UserRole, sf)
        main.addWidget(self._fn_list)

        fn_btn_row = QHBoxLayout()
        self._btn_remove_fn = QPushButton("Entfernen")
        self._btn_remove_fn.clicked.connect(self._remove_fn)
        fn_btn_row.addWidget(self._btn_remove_fn)
        fn_btn_row.addStretch()
        main.addLayout(fn_btn_row)

        # ── Tabs: Sensorfunktion hinzufügen ────────────────────────────────────
        from PySide6.QtWidgets import QTabWidget
        main.addWidget(QLabel("Sensorfunktion hinzufügen:"))
        tabs = QTabWidget()

        # Tab 1: Eigener Raum
        from PySide6.QtWidgets import QWidget as _QWidget
        own_tab = _QWidget()
        own_layout = QVBoxLayout(own_tab)
        own_layout.addWidget(QLabel("Gewerk aus diesem Raum:"))
        self._own_combo = QComboBox()
        self._populate_own_combo()
        own_layout.addWidget(self._own_combo)
        self._own_label = QLineEdit()
        self._own_label.setPlaceholderText("Bezeichnung (optional)")
        own_layout.addWidget(self._own_label)
        btn_add_own = QPushButton("Hinzufügen")
        btn_add_own.clicked.connect(self._add_own)
        own_layout.addWidget(btn_add_own)
        own_layout.addStretch()
        tabs.addTab(own_tab, "Eigener Raum")

        # Tab 2: Anderer Raum
        other_tab = _QWidget()
        other_layout = QVBoxLayout(other_tab)
        other_layout.addWidget(QLabel("Raum auswählen:"))
        self._other_room_combo = QComboBox()
        other_rooms = [r for r in all_rooms if r.id != room.id]
        for r in other_rooms:
            self._other_room_combo.addItem(f"{r.number} {r.name}", r)
        self._other_room_combo.currentIndexChanged.connect(self._refresh_other_gewerk)
        other_layout.addWidget(self._other_room_combo)
        other_layout.addWidget(QLabel("Gewerk:"))
        self._other_gewerk_combo = QComboBox()
        other_layout.addWidget(self._other_gewerk_combo)
        self._other_label = QLineEdit()
        self._other_label.setPlaceholderText("Bezeichnung (optional)")
        other_layout.addWidget(self._other_label)
        btn_add_other = QPushButton("Hinzufügen")
        btn_add_other.clicked.connect(self._add_other)
        other_layout.addWidget(btn_add_other)
        other_layout.addStretch()
        self._other_rooms = other_rooms
        self._refresh_other_gewerk()
        tabs.addTab(other_tab, "Anderer Raum")

        # Tab 3: Direkte GA
        ga_tab = _QWidget()
        ga_layout = QVBoxLayout(ga_tab)
        ga_layout.addWidget(QLabel("Gruppenadresse (Einzelfunktion):"))
        self._ga_combo = QComboBox()
        self._ga_combo.setEditable(True)
        self._ga_combo.setInsertPolicy(QComboBox.NoInsert)
        all_gas = sorted(
            [ga.designation for ga in self._gas.all_addresses()
             if ga.designation and not ga.is_placeholder],
            key=str.lower,
        )
        self._ga_combo.addItems(all_gas)
        ga_layout.addWidget(self._ga_combo)
        self._ga_label = QLineEdit()
        self._ga_label.setPlaceholderText("Bezeichnung (optional)")
        ga_layout.addWidget(self._ga_label)
        btn_add_ga = QPushButton("Hinzufügen")
        btn_add_ga.clicked.connect(self._add_ga)
        ga_layout.addWidget(btn_add_ga)
        ga_layout.addStretch()
        tabs.addTab(ga_tab, "Direkte GA")

        # Tab 4: Szene
        scene_tab = _QWidget()
        scene_layout = QVBoxLayout(scene_tab)
        self._scene_gas = sorted(
            [ga for ga in self._gas.all_addresses()
             if ga.function_name == "SZENE" and not ga.is_placeholder],
            key=lambda g: g.designation,
        )
        if self._scene_gas:
            scene_layout.addWidget(QLabel("Szene auswählen:"))
            self._scene_combo = QComboBox()
            for ga in self._scene_gas:
                self._scene_combo.addItem(ga.designation, ga)
            scene_layout.addWidget(self._scene_combo)
            self._scene_label = QLineEdit()
            self._scene_label.setPlaceholderText("Taste-Bezeichnung (optional, z.B. «Kino»)")
            scene_layout.addWidget(self._scene_label)
            btn_add_scene = QPushButton("Hinzufügen")
            btn_add_scene.clicked.connect(self._add_scene)
            scene_layout.addWidget(btn_add_scene)
        else:
            hint = QLabel(
                "Keine Szenen-GAs vorhanden.\n"
                "Bitte zuerst Szenen definieren und Gruppenadressen\n"
                "in Schritt 8 neu generieren."
            )
            hint.setStyleSheet("color: #E67E22; font-style: italic;")
            hint.setWordWrap(True)
            scene_layout.addWidget(hint)
        scene_layout.addStretch()
        tabs.addTab(scene_tab, "Szene")

        main.addWidget(tabs)

        # ── Dialog-Buttons ─────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        main.addWidget(btns)

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._on_type_changed(self._type_combo.currentText())

    # ── Typ-Wechsel ────────────────────────────────────────────────────────────

    def _on_type_changed(self, text: str):
        is_taster = (text == "Tastereinheit")
        self._channel_row_label.setVisible(is_taster)
        self._channel_combo.setVisible(is_taster)

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def _sf_label(self, sf: SensorFunktion) -> str:
        if sf.ga_designation:
            return f"GA: {sf.label or sf.ga_designation}"
        room_lbl = ""
        if sf.source_room_id:
            src = next((r for r in self._all_rooms if r.id == sf.source_room_id), None)
            room_lbl = f" [{src.number} {src.name}]" if src else " [Fremdraum]"
        gewerk_name = sf.gewerk_code
        for _lbl, _fn, desc, *_ in GEWERK_PRIMARY_FUNCTIONS.get(sf.gewerk_code, []):
            gewerk_name = f"{sf.gewerk_code} – {desc}"
            break
        lbl = sf.label or gewerk_name
        if sf.element_number > 1:
            lbl += f" #{sf.element_number}"
        return f"{lbl}{room_lbl}"

    def _populate_own_combo(self):
        self._own_combo.clear()
        seen = set()
        for assignment in self._room.gewerk_assignments:
            code = assignment.gewerk_code
            if code not in GEWERK_PRIMARY_FUNCTIONS:
                continue
            for elem_nr in range(1, assignment.count + 1):
                key = (code, elem_nr)
                if key in seen:
                    continue
                seen.add(key)
                first_desc = GEWERK_PRIMARY_FUNCTIONS[code][0][2] if GEWERK_PRIMARY_FUNCTIONS.get(code) else code
                display = f"{code} – {first_desc}"
                if assignment.count > 1:
                    display += f" #{elem_nr}"
                self._own_combo.addItem(display, (code, elem_nr))

    def _refresh_other_gewerk(self):
        self._other_gewerk_combo.clear()
        idx = self._other_room_combo.currentIndex()
        if idx < 0 or idx >= len(self._other_rooms):
            return
        other_room = self._other_rooms[idx]
        seen = set()
        for assignment in other_room.gewerk_assignments:
            code = assignment.gewerk_code
            if code not in GEWERK_PRIMARY_FUNCTIONS:
                continue
            for elem_nr in range(1, assignment.count + 1):
                key = (code, elem_nr)
                if key in seen:
                    continue
                seen.add(key)
                first_desc = GEWERK_PRIMARY_FUNCTIONS[code][0][2] if GEWERK_PRIMARY_FUNCTIONS.get(code) else code
                display = f"{code} – {first_desc}"
                if assignment.count > 1:
                    display += f" #{elem_nr}"
                self._other_gewerk_combo.addItem(display, (code, elem_nr, other_room.id))

    def _add_own(self):
        data = self._own_combo.currentData()
        if data is None:
            return
        code, elem_nr = data
        sf = SensorFunktion(
            label=self._own_label.text().strip(),
            gewerk_code=code,
            element_number=elem_nr,
            source_room_id="",
        )
        self._fn_list.addItem(self._sf_label(sf))
        self._fn_list.item(self._fn_list.count() - 1).setData(Qt.UserRole, sf)
        self._own_label.clear()

    def _add_other(self):
        data = self._other_gewerk_combo.currentData()
        if data is None:
            return
        code, elem_nr, room_id = data
        sf = SensorFunktion(
            label=self._other_label.text().strip(),
            gewerk_code=code,
            element_number=elem_nr,
            source_room_id=room_id,
        )
        self._fn_list.addItem(self._sf_label(sf))
        self._fn_list.item(self._fn_list.count() - 1).setData(Qt.UserRole, sf)
        self._other_label.clear()

    def _add_ga(self):
        ga_text = self._ga_combo.currentText().strip()
        if not ga_text:
            return
        sf = SensorFunktion(
            label=self._ga_label.text().strip() or ga_text,
            ga_designation=ga_text,
            action_type="",
        )
        self._fn_list.addItem(self._sf_label(sf))
        self._fn_list.item(self._fn_list.count() - 1).setData(Qt.UserRole, sf)
        self._ga_label.clear()

    def _add_scene(self):
        ga = self._scene_combo.currentData()
        if ga is None:
            return
        label = self._scene_label.text().strip() or ga.designation
        sf = SensorFunktion(
            label=label,
            ga_designation=ga.designation,
            action_type="kurz",
        )
        self._fn_list.addItem(self._sf_label(sf))
        self._fn_list.item(self._fn_list.count() - 1).setData(Qt.UserRole, sf)
        self._scene_label.clear()

    def _remove_fn(self):
        row = self._fn_list.currentRow()
        if row >= 0:
            self._fn_list.takeItem(row)

    def _apply(self):
        self._be.element_type = self._type_combo.currentText()
        self._be.product_name = self._label_edit.text().strip()
        self._be.is_auto = False

        sfs = []
        for i in range(self._fn_list.count()):
            sf = self._fn_list.item(i).data(Qt.UserRole)
            if sf:
                sfs.append(sf)
        self._be.funktionen = sfs

        if self._be.element_type == "Tastereinheit":
            self._be.channels = int(self._channel_combo.currentText())
        else:
            n = sum(1 for sf in sfs if sf.gewerk_code) or max(len(sfs), 1)
            self._be.channels = n if n > 1 else 1

        self.accept()


class Step08Sensors(QWidget):
    """Funktionszuordnung – welche GA steuert welches Gerät (FA-1410)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project

        layout = QVBoxLayout(self)

        info = QLabel(
            "Weisen Sie jedem Bedienelement die passenden Gruppenadressen zu.\n"
            "Doppelklick auf ein Gerät öffnet den Zuordnungs-Dialog.\n"
            "Geräte hinzufügen oder löschen: bitte in Schritt 6 (Gerätekonfiguration)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._no_topology_hint = QLabel(
            "Hinweis: Keine Topologie vorhanden. "
            "Bitte zuerst in Schritt 7 die Topologie berechnen."
        )
        self._no_topology_hint.setStyleSheet("color: #E67E22; font-weight: bold;")
        self._no_topology_hint.setWordWrap(True)
        self._no_topology_hint.setVisible(False)
        layout.addWidget(self._no_topology_hint)

        self._no_ga_hint = QLabel(
            "Hinweis: Noch keine Gruppenadressen vorhanden. "
            "Bitte zuerst in Schritt 8 Gruppenadressen generieren."
        )
        self._no_ga_hint.setStyleSheet("color: #E67E22; font-weight: bold;")
        self._no_ga_hint.setWordWrap(True)
        self._no_ga_hint.setVisible(False)
        layout.addWidget(self._no_ga_hint)

        self._summary = QLabel("")
        self._summary.setObjectName("subtitle")
        layout.addWidget(self._summary)

        # Haupt-Baum: Linie > Raum > Bedienelement
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels([
            "Raum / Bedienelement", "Typ", "Funktionen", "Status",
        ])
        self._tree.setAlternatingRowColors(True)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setRootIsDecorated(True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tree)

        # Materialliste (FA-1405)
        mat_group = QGroupBox("Materialliste Sensoren")
        mat_layout = QVBoxLayout()
        self._mat_tree = QTreeWidget()
        self._mat_tree.itemExpanded.connect(lambda _: fit_columns(self._mat_tree))
        self._mat_tree.setHeaderLabels(["Typ", "Anzahl", "Hersteller", "Artikelnummer"])
        self._mat_tree.setMaximumHeight(150)
        self._mat_tree.setAlternatingRowColors(True)
        self._mat_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._mat_tree.setRootIsDecorated(False)
        mat_layout.addWidget(self._mat_tree)
        btn_mat = QPushButton("In Projekt-Materialliste übernehmen →")
        btn_mat.clicked.connect(self._transfer_to_material_list)
        mat_layout.addWidget(btn_mat)
        mat_group.setLayout(mat_layout)
        layout.addWidget(mat_group)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def on_enter(self):
        rooms = self._project.all_rooms
        if any(r.gewerk_assignments for r in rooms):
            self._refresh_from_project()

    # ── Baum-Aufbau ────────────────────────────────────────────────────────────

    def _refresh_from_project(self, run_auto_assign: bool = True):
        topology = self._project.topology
        has_ga = bool(self._project.group_addresses.all_addresses())

        self._no_topology_hint.setVisible(not topology.areas)
        self._no_ga_hint.setVisible(bool(topology.areas) and not has_ga)

        if not topology.areas:
            self._tree.clear()
            self._summary.setText("")
            return

        all_rooms = self._project.all_rooms

        # Funktionszuordnung aktualisieren (nicht nach manuellem Edit – BE.funktionen schon gesetzt)
        if run_auto_assign:
            service = SensorService()
            service.auto_assign_functions(all_rooms, self._project.group_addresses)

        self._tree.clear()
        room_by_id = {r.id: r for r in all_rooms}
        bold_font = QFont()
        bold_font.setBold(True)

        total_be = 0
        total_with_fn = 0

        for area in topology.areas:
            for line in area.lines:
                line_rooms = [
                    room_by_id[rid] for rid in line.assigned_room_ids
                    if rid in room_by_id
                ]
                if not line_rooms:
                    continue

                line_item = QTreeWidgetItem(self._tree, [
                    f"Linie {line.coupler_address} – {line.name}", "", "", "",
                ])
                line_item.setFont(0, bold_font)
                line_item.setExpanded(True)

                for room in line_rooms:
                    if not room.gewerk_assignments:
                        continue

                    room_item = QTreeWidgetItem(line_item, [
                        f"{room.number} {room.name}", "", "", "",
                    ])
                    room_item.setFont(0, bold_font)
                    room_item.setData(0, Qt.UserRole, ("room", room))
                    room_item.setExpanded(True)

                    for be in room.bedienelemente:
                        if be.suppressed:
                            continue
                        self._add_be_item(room_item, be, room)
                        total_be += 1
                        if be.funktionen:
                            total_with_fn += 1

        fit_columns(self._tree)
        self._summary.setText(
            f"{total_be} Geräte – {total_with_fn} mit Funktionszuordnung, "
            f"{total_be - total_with_fn} noch ohne"
        )
        self._refresh_material()

    def _add_be_item(self, parent: QTreeWidgetItem, be: Bedienelement, room):
        fn_summary = self._fn_summary(be)
        status = "Auto" if be.is_auto else "Manuell"
        item = QTreeWidgetItem(parent, [
            f"  {be.element_type or '(kein Typ)'}",
            f"{be.channels}-kanalig",
            fn_summary,
            status,
        ])
        item.setData(0, Qt.UserRole, ("be", room, be))
        color = _COLOR_AUTO if be.is_auto else _COLOR_MANUAL
        for col in range(item.columnCount()):
            item.setForeground(col, QBrush(color))
        for sf in be.funktionen:
            sf_item = QTreeWidgetItem(item, [
                f"    → {self._sf_display(sf)}", "", "", "",
            ])
            sf_item.setData(0, Qt.UserRole, None)
        item.setExpanded(bool(be.funktionen))
        return item

    def _fn_summary(self, be: Bedienelement) -> str:
        n = len(be.funktionen)
        if n == 0:
            return "–"
        codes = []
        for sf in be.funktionen:
            if sf.ga_designation:
                codes.append("GA")
            elif sf.gewerk_code:
                codes.append(sf.gewerk_code)
        unique = list(dict.fromkeys(codes))
        suffix = "…" if n > 4 else ""
        return ", ".join(unique[:4]) + suffix

    def _sf_display(self, sf: SensorFunktion) -> str:
        if sf.ga_designation:
            return sf.label or sf.ga_designation
        room_lbl = ""
        if sf.source_room_id:
            src = next((r for r in self._project.all_rooms
                        if r.id == sf.source_room_id), None)
            room_lbl = f" [{src.number} {src.name}]" if src else " [Fremdraum]"
        first_desc = GEWERK_PRIMARY_FUNCTIONS.get(
            sf.gewerk_code, [("", "", sf.gewerk_code)]
        )[0][2]
        lbl = sf.label or f"{sf.gewerk_code} – {first_desc}"
        if sf.element_number > 1:
            lbl += f" #{sf.element_number}"
        return f"{lbl}{room_lbl}"

    # ── Interaktion ────────────────────────────────────────────────────────────

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind = data[0]
        if kind == "be":
            _, room, be = data
            self._edit_bedienelement(be, room)
        elif kind == "room":
            _, room = data
            visible = [b for b in room.bedienelemente if not b.suppressed]
            if visible:
                self._edit_bedienelement(visible[0], room)

    def _on_context_menu(self, pos: QPoint):
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != "be":
            return
        _, room, be = data
        menu = QMenu(self)
        act_edit = menu.addAction("Funktionen bearbeiten…")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == act_edit:
            self._edit_bedienelement(be, room)

    def _edit_bedienelement(self, be: Bedienelement, room):
        dlg = _SensorFunktionDialog(
            be, room, self._project.all_rooms,
            self._project.group_addresses,
            all_scenes=self._project.scenes, parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            # BE wurde von _apply() bereits direkt modifiziert (is_auto=False, funktionen gesetzt).
            # auto_assign_functions NICHT aufrufen – es würde room.bedienelemente leeren und
            # beim Re-Matching könnte das manuelle BE verloren gehen.
            # function_assignments werden beim Eintritt in Schritt 12 (step09) expandiert.
            self._refresh_from_project(run_auto_assign=False)

    # ── Materialliste ──────────────────────────────────────────────────────────

    def _refresh_material(self):
        topology = self._project.topology
        self._mat_tree.clear()
        by_type: dict[str, int] = {}
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type == "sensor":
                        by_type[device.product] = by_type.get(device.product, 0) + 1
        for sensor_type, qty in sorted(by_type.items()):
            QTreeWidgetItem(self._mat_tree, [sensor_type, str(qty), "–", "–"])
        fit_columns(self._mat_tree)

    def _transfer_to_material_list(self):
        from PySide6.QtWidgets import QMessageBox
        topology = self._project.topology
        if not topology.areas:
            QMessageBox.information(
                self, "Keine Sensoren",
                "Bitte zuerst die Topologie berechnen (Schritt 7).",
            )
            return

        ml = self._project.material_list
        ml.entries = [
            e for e in ml.entries
            if not (e.source == "wizard_auto" and e.category == "Sensor")
        ]

        total_entries = 0
        for area in topology.areas:
            for line in area.lines:
                sensor_devices = [d for d in line.devices if d.device_type == "sensor"]
                if not sensor_devices:
                    continue
                by_type: dict[str, list] = {}
                for device in sensor_devices:
                    key = f"{device.product}|{device.manufacturer}|{device.order_number}"
                    by_type.setdefault(key, []).append(device)
                line_label = f"{line.coupler_address} {line.name}".strip()
                for devices in by_type.values():
                    addresses = [d.physical_address for d in devices if d.physical_address]
                    entry = MaterialEntry(
                        quantity=len(devices),
                        category="Sensor",
                        device_type=devices[0].product,
                        manufacturer=devices[0].manufacturer,
                        order_number=devices[0].order_number,
                        product_name=devices[0].product,
                        source="wizard_auto",
                        line_id=line.id,
                        line_name=line_label,
                        physical_addresses=addresses,
                    )
                    ml.entries.append(entry)
                    total_entries += 1

        QMessageBox.information(
            self, "Materialliste aktualisiert",
            f"{total_entries} Sensor-Position(en) in die Projekt-Materialliste übertragen.",
        )
