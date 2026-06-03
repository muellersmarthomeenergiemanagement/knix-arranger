"""
Wizard Schritt 5c: Gerätekonfiguration pro Raum (FA-1400a)

Alle physischen Bedienelemente (Tastereinheiten, Bewegungsmelder, Präsenzmelder,
Thermostate usw.) werden hier pro Raum festgelegt – BEVOR die Topologie
berechnet wird.  So kennt populate_devices() alle Geräte von Anfang an und
muss keine Geräte nachträglich einfügen.

Die Funktionszuordnung (welche Gruppenadresse steuert welchen Kanal) erfolgt
erst nach der GA-Generierung in Schritt 9 (Funktionszuordnung).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QAbstractItemView, QGroupBox,
    QMessageBox, QDialog, QDialogButtonBox, QComboBox, QFormLayout,
    QLineEdit, QMenu,
)
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont, QColor, QBrush

from ...models.project import KnxProject
from ...models.building import Bedienelement
from ...services.sensor_service import SensorService
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

_COLOR_AUTO   = QColor("#1B5E20")   # Dunkelgrün: automatisch
_COLOR_MANUAL = QColor("#E65100")   # Orange: manuell


class _DeviceConfigDialog(QDialog):
    """
    Einfacher Konfigurations-Dialog: Gerätetyp + Kanalzahl.

    Keine Funktionszuordnung – diese erfolgt in Schritt 9.
    """

    def __init__(self, be: Bedienelement, parent=None):
        super().__init__(parent)
        self._be = be
        self.setWindowTitle("Gerät konfigurieren")
        self.setMinimumWidth(340)

        main = QVBoxLayout(self)

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
        self._channel_label = QLabel("Kanalzahl:")
        form.addRow(self._channel_label, self._channel_combo)

        self._label_edit = QLineEdit(be.product_name or "")
        self._label_edit.setPlaceholderText("z.B. Taster Eingang, Thermostat Süd")
        form.addRow("Bezeichnung (opt.):", self._label_edit)

        main.addLayout(form)

        hint = QLabel(
            "Funktionen (welche GA dieses Gerät steuert) werden\n"
            "in Schritt 9 nach der GA-Generierung zugewiesen."
        )
        hint.setStyleSheet("color: #808080; font-style: italic;")
        main.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        main.addWidget(btns)

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._on_type_changed(self._type_combo.currentText())

    def _on_type_changed(self, text: str):
        is_taster = (text == "Tastereinheit")
        self._channel_label.setVisible(is_taster)
        self._channel_combo.setVisible(is_taster)

    def _apply(self):
        self._be.element_type = self._type_combo.currentText()
        self._be.product_name = self._label_edit.text().strip()
        self._be.is_auto = False
        if self._be.element_type == "Tastereinheit":
            self._be.channels = int(self._channel_combo.currentText())
        self.accept()


class Step05cDevices(QWidget):
    """
    Gerätekonfiguration pro Raum – VOR der Topologie (FA-1400a).

    Zeigt alle auto-ermittelten Bedienelemente aus den Gewerk-Zuweisungen
    und erlaubt manuelle Anpassungen (Typ ändern, Gerät hinzufügen/löschen).
    """

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project

        layout = QVBoxLayout(self)

        info = QLabel(
            "Legen Sie pro Raum fest, welche physischen Bedienelemente vorhanden sind "
            "(Tastereinheiten, Bewegungsmelder, Thermostate usw.).\n"
            "Automatisch ermittelte Geräte (grün) basieren auf den Gewerk-Zuweisungen. "
            "Manuelle Geräte (orange) werden zusätzlich eingefügt."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()

        self._btn_auto = QPushButton("Alle automatisch berechnen")
        self._btn_auto.setToolTip(
            "Setzt alle manuellen Typ-Änderungen zurück und berechnet Geräte\n"
            "neu aus den Gewerk-Zuweisungen."
        )
        self._btn_auto.clicked.connect(self._recalc_all_auto)
        btn_row.addWidget(self._btn_auto)

        self._btn_restore = QPushButton("Gelöschte wiederherstellen")
        self._btn_restore.setObjectName("secondary")
        self._btn_restore.setToolTip("Hebt die Unterdrückung aller manuell gelöschten Geräte auf.")
        self._btn_restore.clicked.connect(self._restore_suppressed)
        btn_row.addWidget(self._btn_restore)

        btn_row.addStretch()

        self._topology_hint = QLabel(
            "Geräte geändert – bitte Topologie (Schritt 7) neu berechnen."
        )
        self._topology_hint.setStyleSheet("color: #E65100; font-weight: bold;")
        self._topology_hint.setVisible(False)
        btn_row.addWidget(self._topology_hint)

        layout.addLayout(btn_row)

        self._summary = QLabel("")
        self._summary.setObjectName("subtitle")
        layout.addWidget(self._summary)

        # Haupt-Baum: Raum > Bedienelement
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels(["Gerät / Raum", "Bezeichnung", "Kanäle", "Status"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setRootIsDecorated(True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tree)

        # Systemgeräte (FA-1409)
        self._sys_group = QGroupBox("Systemgeräte (projektweite Geräte)")
        sys_layout = QVBoxLayout()
        sys_hint = QLabel(
            "Systemgeräte (z.B. Wetterstation) werden einmalig pro Projekt geplant, "
            "nicht raumweise."
        )
        sys_hint.setWordWrap(True)
        sys_hint.setStyleSheet("color: #1565C0; font-style: italic;")
        sys_layout.addWidget(sys_hint)
        self._sys_tree = QTreeWidget()
        self._sys_tree.setHeaderLabels(["Gewerk", "Typ", "Menge"])
        self._sys_tree.setMaximumHeight(80)
        self._sys_tree.setAlternatingRowColors(True)
        self._sys_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._sys_tree.setRootIsDecorated(False)
        sys_layout.addWidget(self._sys_tree)
        self._sys_group.setLayout(sys_layout)
        self._sys_group.setVisible(False)
        layout.addWidget(self._sys_group)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def on_enter(self):
        rooms = self._project.all_rooms
        if any(r.gewerk_assignments for r in rooms):
            service = SensorService()
            service.auto_assign_functions(rooms, self._project.group_addresses)
        self._refresh_tree()

    # ── Baum-Aufbau ────────────────────────────────────────────────────────────

    def _refresh_tree(self):
        from collections import defaultdict

        self._tree.setUpdatesEnabled(False)
        self._tree.clear()
        all_rooms = self._project.all_rooms
        bold_font = QFont()
        bold_font.setBold(True)

        total_be = 0
        total_manual = 0

        # --- Geräte nach Typ gruppieren ---
        # type_groups: element_type -> [ (room, be), ... ]  (nach Raumnummer sortiert)
        type_groups: dict[str, list] = defaultdict(list)
        for room in sorted(all_rooms, key=lambda r: r.number):
            if not room.gewerk_assignments and not room.bedienelemente:
                continue
            for be in room.bedienelemente:
                if be.suppressed:
                    continue
                et = be.element_type or "(kein Typ)"
                type_groups[et].append((room, be))
                total_be += 1
                if not be.is_auto:
                    total_manual += 1

        # Reihenfolge: Tastereinheit zuerst, dann alphabetisch
        _PRIORITY = ["Tastereinheit"]
        sorted_types = sorted(
            type_groups.keys(),
            key=lambda t: (0 if t in _PRIORITY else 1, t),
        )

        for et in sorted_types:
            entries = type_groups[et]  # list[(room, be)], schon nach Raumnummer

            # Pro Typ: Räume zusammenfassen
            room_bes: dict[str, list] = defaultdict(list)   # room_id -> [be, ...]
            room_obj: dict[str, object] = {}
            for room, be in entries:
                room_bes[room.id].append(be)
                room_obj[room.id] = room

            sorted_room_ids = sorted(
                room_bes.keys(), key=lambda rid: room_obj[rid].number
            )

            type_item = QTreeWidgetItem(self._tree, [
                f"{et}  ({len(entries)} Gerät{'e' if len(entries) != 1 else ''})",
                "", "", "",
            ])
            type_item.setFont(0, bold_font)
            type_item.setData(0, Qt.UserRole, ("type", et))
            type_item.setExpanded(True)

            # Fortlaufende Gesamtnummer pro Typ (FA-222: TE starten bei 101)
            global_nr = 101 if et == "Tastereinheit" else 1

            for room_id in sorted_room_ids:
                room = room_obj[room_id]
                bes = room_bes[room_id]
                count_in_room = len(bes)
                count_suffix = f"  ({count_in_room}×)" if count_in_room > 1 else ""

                room_item = QTreeWidgetItem(type_item, [
                    f"{room.number} {room.name}{count_suffix}", "", "", "",
                ])
                room_item.setFont(0, bold_font)
                room_item.setData(0, Qt.UserRole, ("room_in_type", room, et))
                room_item.setExpanded(True)

                for be in bes:
                    nr = global_nr
                    global_nr += 1
                    ch_str = str(be.channels) if be.channels > 1 else "1"
                    status = "Auto" if be.is_auto else "Manuell"
                    be_item = QTreeWidgetItem(room_item, [
                        f"  {et} {nr}",
                        be.product_name or "",
                        f"{ch_str}-kanalig" if et == "Tastereinheit" else "",
                        status,
                    ])
                    be_item.setData(0, Qt.UserRole, ("be", room, be))
                    color = _COLOR_AUTO if be.is_auto else _COLOR_MANUAL
                    for col in range(be_item.columnCount()):
                        be_item.setForeground(col, QBrush(color))

                # [+ Gerät hinzufügen] am Ende jedes Raums im Typ-Block
                add_item = QTreeWidgetItem(room_item, ["  + Gerät hinzufügen", "", "", ""])
                add_item.setForeground(0, QBrush(QColor("#1565C0")))
                add_item.setData(0, Qt.UserRole, ("add", room, et))

        # Räume mit Gewerk-Zuweisungen aber noch ohne BEs: Platzhalter
        for room in sorted(all_rooms, key=lambda r: r.number):
            if room.gewerk_assignments and not any(
                not be.suppressed for be in room.bedienelemente
            ):
                placeholder = QTreeWidgetItem(self._tree, [
                    f"{room.number} {room.name}  (keine Geräte)", "", "", "",
                ])
                placeholder.setForeground(0, QBrush(QColor("#9E9E9E")))
                add_item = QTreeWidgetItem(placeholder, ["  + Gerät hinzufügen", "", "", ""])
                add_item.setForeground(0, QBrush(QColor("#1565C0")))
                add_item.setData(0, Qt.UserRole, ("add", room, None))
                placeholder.setExpanded(True)

        self._tree.setUpdatesEnabled(True)
        fit_columns(self._tree)

        self._summary.setText(
            f"{total_be} Geräte "
            f"({total_manual} manuell, {total_be - total_manual} automatisch)"
        )

        # Systemgeräte aktualisieren
        service = SensorService()
        system_entries = service.determine_system_sensors(all_rooms)
        self._sys_tree.clear()
        for entry in system_entries:
            QTreeWidgetItem(self._sys_tree, [
                entry["gewerk_code"], entry["sensor_type"], str(entry["count"]),
            ])
        self._sys_group.setVisible(bool(system_entries))

    # ── Interaktion ────────────────────────────────────────────────────────────

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind = data[0]
        if kind == "add":
            # data = ("add", room, default_type_or_None)
            self._add_bedienelement(data[1], default_type=data[2] if len(data) > 2 else None)
        elif kind == "be":
            self._edit_bedienelement(data[2], data[1])
        elif kind == "room_in_type":
            _, room, et = data
            visible = [b for b in room.bedienelemente
                       if not b.suppressed and b.element_type == et]
            if visible:
                self._edit_bedienelement(visible[0], room)
            else:
                self._add_bedienelement(room, default_type=et)

    def _on_context_menu(self, pos: QPoint):
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != "be":
            return
        _, room, be = data
        menu = QMenu(self)
        act_edit = menu.addAction("Bearbeiten…")
        act_del  = menu.addAction("Löschen")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == act_edit:
            self._edit_bedienelement(be, room)
        elif action == act_del:
            self._delete_bedienelement(be, room)

    def _add_bedienelement(self, room, default_type: str | None = None):
        """Legt ein neues Gerät an und öffnet den Konfigurations-Dialog."""
        used_indices = {
            idx
            for assignment in room.gewerk_assignments
            for idx in assignment.taster_indices
        }
        for existing_be in room.bedienelemente:
            if not existing_be.is_auto:
                used_indices.add(existing_be.taster_index)
        next_idx = max(used_indices, default=0) + 1

        be = Bedienelement(
            element_type=default_type or "Tastereinheit",
            channels=4,
            is_auto=False,
            taster_index=next_idx,
        )
        dlg = _DeviceConfigDialog(be, parent=self)
        if dlg.exec() == QDialog.Accepted:
            room.bedienelemente.append(be)
            self._run_service()

    def _edit_bedienelement(self, be: Bedienelement, room):
        """Öffnet den Konfigurations-Dialog für ein bestehendes Gerät."""
        dlg = _DeviceConfigDialog(be, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._run_service()

    def _delete_bedienelement(self, be: Bedienelement, room):
        """Löscht ein Gerät (Auto-BEs werden als Tombstone markiert)."""
        ans = QMessageBox.question(
            self, "Gerät löschen",
            f"«{be.element_type or '(kein Typ)'}» wirklich löschen?\n\n"
            + ("Das Gerät wird unterdrückt und nicht neu berechnet.\n"
               "«Gelöschte wiederherstellen» macht dies rückgängig."
               if be.is_auto else ""),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        if be.is_auto:
            be.is_auto = False
            be.suppressed = True
            be.funktionen = []
            be.function_assignments = []
        else:
            try:
                room.bedienelemente.remove(be)
            except ValueError:
                pass
        self._run_service()

    def _recalc_all_auto(self):
        """Setzt alle manuellen Übersteuerungen zurück."""
        ans = QMessageBox.question(
            self, "Automatisch berechnen",
            "Alle manuellen Typ-Änderungen und zusätzlichen Geräte werden "
            "zurückgesetzt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        for room in self._project.all_rooms:
            for be in room.bedienelemente:
                be.is_auto = True
                be.suppressed = False
        service = SensorService()
        service.auto_assign_functions(
            self._project.all_rooms, self._project.group_addresses
        )
        self._topology_hint.setVisible(True)
        self._refresh_tree()

    def _restore_suppressed(self):
        """Hebt die Unterdrückung aller manuell gelöschten Geräte auf."""
        count = 0
        for room in self._project.all_rooms:
            to_remove = [be for be in room.bedienelemente if be.suppressed]
            for be in to_remove:
                room.bedienelemente.remove(be)
                count += 1
        if count:
            self._run_service()
        else:
            QMessageBox.information(
                self, "Wiederherstellen",
                "Keine unterdrückten Geräte vorhanden.",
            )

    def _run_service(self):
        """auto_assign_functions ausführen und Baum aktualisieren."""
        service = SensorService()
        service.auto_assign_functions(
            self._project.all_rooms, self._project.group_addresses
        )
        self._topology_hint.setVisible(True)
        self._refresh_tree()
