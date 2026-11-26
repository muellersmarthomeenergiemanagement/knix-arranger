"""
Räume zuordnen (FA-3105c): Taster und Sensoren samt den Aktorkanälen, die
sie bedienen, einem Raum zuweisen. Vor Ort: Taste drücken, KNiX wählt den
Taster und schlägt die Aktorkanäle vor, die verknüpft sind oder in den
Sekunden danach auf dem Bus vorkommen (Logikserver, Status der Aktoren).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...services import room_from_bus as rb
from ..styles import COLOR_OK, TEXT_MUTED

_SHOW_OPERATORS, _SHOW_ORPHANS = "operators", "orphans"
_COLUMNS = ["Gerät", "Produkt", "Raum", "Aktorkanäle"]


class NewRoomDialog(QDialog):
    """Gebäude und Gebäudeteil (bei mehreren), Stockwerk, Zone, Raumnummer
    und Name. Neues Stockwerk oder neue Zone erst nach Rückfrage (vor Ort
    vertippt man sich leicht: «OG» und «1.OG» wären zwei Stockwerke). Die
    Raumnummer folgt dem Schema von Schritt 3 und ist im Projekt eindeutig,
    sonst wären die GA-Namen zweier Räume gleich."""

    def __init__(self, project, parent=None, floor_hint: str = "", zone_hint: str = ""):
        super().__init__(parent)
        self._project = project
        self._suggested = ""
        self.setWindowTitle("Neuer Raum")
        form = QFormLayout(self)
        buildings = list(project.areal.buildings)
        self.building = QComboBox()
        for building in buildings:
            self.building.addItem(building.name or "Gebäude", building)
        self.wing = QComboBox()
        self.floor = QComboBox()
        self.floor.setEditable(True)
        self.floor.setToolTip("Bestehendes Stockwerk wählen oder ein neues Kürzel eingeben")
        self.zone = QComboBox()
        self.zone.setEditable(True)
        self.zone.setToolTip("Zone des Raums (z.B. Innen/Aussen, Wohnung). Gleicher Name "
                             "auf mehreren Stockwerken = eine Zone.")
        self.zone.addItems(rb.zone_names(project))
        self.number = QLineEdit()
        self.number.setPlaceholderText("leer = ohne Nummer")
        self.number.setToolTip("Vorschlag nach dem Schema der übrigen Räume; im Projekt "
                               "eindeutig, damit die GA-Namen eindeutig bleiben")
        self.name = QLineEdit()
        self.name.setPlaceholderText("z.B. Wohnen")
        if len(buildings) > 1:
            form.addRow("Gebäude:", self.building)
        self._wing_label = QLabel("Gebäudeteil:")
        form.addRow(self._wing_label, self.wing)
        form.addRow("Stockwerk:", self.floor)
        form.addRow("Zone:", self.zone)
        form.addRow("Raumnummer:", self.number)
        form.addRow("Name:", self.name)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.building.currentIndexChanged.connect(self._fill_wings)
        self.wing.currentIndexChanged.connect(self._fill_floors)
        self.floor.currentTextChanged.connect(self._floor_changed)
        self.zone.currentTextChanged.connect(lambda _t: self._suggest_number())
        self._fill_wings()
        if floor_hint and self.floor.findText(floor_hint) >= 0:
            self.floor.setCurrentText(floor_hint)
        if zone_hint:
            self.zone.setCurrentText(zone_hint)
        self.name.setFocus()

    def selected_building(self):
        return self.building.currentData()

    def selected_wing(self):
        return self.wing.currentData()

    def _floors(self) -> list:
        wing = self.selected_wing()
        if wing is not None:
            return list(wing.floors)
        building = self.selected_building()
        return list(building.all_floors) if building is not None else []

    def _current_floor(self):
        building = self.selected_building()
        if building is None:
            return None
        return rb.find_floor(building, self.floor.currentText(), self.selected_wing())

    def _fill_wings(self) -> None:
        self.wing.blockSignals(True)
        self.wing.clear()
        building = self.selected_building()
        wings = list(building.wings) if building is not None else []
        for wing in wings:
            self.wing.addItem(wing.name or "Gebäudeteil", wing)
        self.wing.blockSignals(False)
        self.wing.setVisible(len(wings) > 1)
        self._wing_label.setVisible(len(wings) > 1)
        self._fill_floors()

    def _fill_floors(self) -> None:
        self.floor.blockSignals(True)
        self.floor.clear()
        floors = [f.short_code or f.name for f in self._floors() if f.short_code or f.name]
        self.floor.addItems(floors or ["UG", "EG", "OG", "DG"])
        self.floor.setCurrentText(floors[0] if floors else "EG")
        self.floor.blockSignals(False)
        self._floor_changed(self.floor.currentText())

    def _floor_changed(self, _text: str) -> None:
        """Zone vorschlagen: die einzige benannte Zone des Stockwerks."""
        floor = self._current_floor()
        if floor is not None:
            named = [a.name for a in floor.apartments if rb._named_zone(floor, a)]
            if len(named) == 1:
                self.zone.setCurrentText(named[0])
            elif not named:
                self.zone.setCurrentText("")
        self._suggest_number()

    def _suggest_number(self) -> None:
        """Nummer vorschlagen, solange sie nicht von Hand geändert wurde."""
        if self.number.text().strip() not in ("", self._suggested):
            return
        floor = self._current_floor()
        self._suggested = rb.suggest_number(self._project, floor, self.zone.currentText(),
                                            self.selected_wing()) if floor else ""
        self.number.setText(self._suggested)

    def _accept(self) -> None:
        if not self.name.text().strip() and not self.number.text().strip():
            QMessageBox.information(self, "Neuer Raum", "Name oder Raumnummer angeben.")
            return
        floor_text = self.floor.currentText().strip()
        new = []
        if self._current_floor() is None and self._floors():
            new.append(f"das Stockwerk «{floor_text or 'EG'}»")
        zone = self.zone.currentText().strip()
        known = [z.lower() for z in rb.zone_names(self._project)]
        if zone and known and zone.lower() not in known:
            new.append(f"die Zone «{zone}»")
        if new:
            text = " und ".join(new)
            if QMessageBox.question(
                    self, "Neuer Raum",
                    f"{text[0].upper()}{text[1:]} gibt es noch nicht. Neu anlegen?")                     != QMessageBox.Yes:
                return
        number = self.number.text().strip()
        taken = rb.duplicate_number(self._project, number)
        if taken and QMessageBox.question(
                self, "Neuer Raum",
                f"Die Raumnummer {number} hat schon «{taken}». Die GA-Namen beider Räume "
                "wären gleich. Trotzdem verwenden?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.accept()

    def create_room(self):
        """Raum nach den Eingaben anlegen."""
        return rb.add_room(self._project, self.floor.currentText(), self.number.text(),
                           self.name.text(), zone=self.zone.currentText(),
                           building=self.selected_building(), wing=self.selected_wing())


class RoomAssignDialog(QDialog):

    def __init__(self, project, monitor=None, bus=None, parent=None):
        super().__init__(parent)
        self._project = project
        self._monitor = monitor
        self._bus = bus
        self._plan = rb.analyse(project)
        self._last_room_id = ""
        self._selected: tuple[str, object] | None = None     # ("op", pa) | ("ch", key)

        self.setWindowTitle("Räume zuordnen – Übersicht")
        self.resize(1150, 640)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Taster und Sensoren mit ihrem Raum und den Aktorkanälen, die sie bedienen; "
            "zum Nachprüfen und Korrigieren. Vor Ort führt der Rundgang Raum für Raum. Die "
            "GA-Namen bekommen den Raum an Stelle der Geräteadresse. Der Aktor selbst "
            "bleibt im Verteiler.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        show = QHBoxLayout()
        show.addWidget(QLabel("Anzeigen:"))
        self._show = QComboBox()
        self._show.addItem("Taster und Sensoren", _SHOW_OPERATORS)
        self._show.addItem("Aktorkanäle ohne Taster", _SHOW_ORPHANS)
        self._show.currentIndexChanged.connect(self._fill_table)
        show.addWidget(self._show, 1)
        left_layout.addLayout(show)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((70, 230, 150)):
            self._table.setColumnWidth(column, width)
        self._table.itemSelectionChanged.connect(self._on_selection)
        left_layout.addWidget(self._table, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: 600;")
        right_layout.addWidget(self._title)
        room_row = QHBoxLayout()
        room_row.addWidget(QLabel("Raum:"))
        self._room = QComboBox()
        room_row.addWidget(self._room, 1)
        new_room = QPushButton("Neuer Raum…")
        new_room.setObjectName("secondary")
        new_room.clicked.connect(self._new_room)
        room_row.addWidget(new_room)
        right_layout.addLayout(room_row)
        right_layout.addWidget(QLabel("Aktorkanäle in denselben Raum:"))
        self._channels = QListWidget()
        right_layout.addWidget(self._channels, 1)
        self._gas = QLabel()
        self._gas.setWordWrap(True)
        self._gas.setStyleSheet(f"color: {TEXT_MUTED};")
        right_layout.addWidget(self._gas)
        assign_row = QHBoxLayout()
        self._result = QLabel()
        self._result.setWordWrap(True)
        self._assign = QPushButton("Zuordnen")
        self._assign.setDefault(True)
        self._assign.clicked.connect(self._do_assign)
        assign_row.addWidget(self._result, 1)
        assign_row.addWidget(self._assign)
        right_layout.addLayout(assign_row)
        splitter.addWidget(right)
        splitter.setSizes([560, 560])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._fill_rooms()
        self._fill_table()

    # ── Anzeige ──────────────────────────────────────────────────────────

    @staticmethod
    def _product(device) -> str:
        return device.product_name or device.product or ""

    def _fill_rooms(self, select_id: str = "") -> None:
        current = select_id or self._room.currentData() or ""
        self._room.blockSignals(True)
        self._room.clear()
        self._room.addItem("– Raum wählen –", "")
        for label, _floor, room in rb.all_rooms(self._project):
            self._room.addItem(label, room.id)
        index = self._room.findData(current)
        self._room.setCurrentIndex(max(index, 0))
        self._room.blockSignals(False)

    def _fill_table(self) -> None:
        show = self._show.currentData()
        selected = self._selected
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        rows: list[tuple[tuple, list[str]]] = []
        if show == _SHOW_OPERATORS:
            for pa in sorted(self._plan.operators, key=rb._pa_key):
                operator = self._plan.operators[pa]
                rows.append((("op", pa), [
                    pa, self._product(operator.device),
                    rb.room_label(self._project, operator.device.room_id) or "–",
                    ", ".join(self._plan.channels[k].label for k in operator.channels) or "–"]))
        else:
            for channel in sorted(self._plan.orphan_channels(),
                                  key=lambda c: (rb._pa_key(c.device_address), c.channel)):
                rows.append((("ch", channel.key), [
                    channel.device_address, f"{channel.channel} ({channel.gewerk or 'SF'})",
                    rb.room_label(self._project, rb.channel_room(self._project, channel))
                    or "–", f"{len(channel.addresses)} GAs"]))
        self._table.setRowCount(len(rows))
        for row, (key, texts) in enumerate(rows):
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.UserRole, key)
                self._table.setItem(row, column, item)
        self._table.blockSignals(False)
        if selected is not None:
            self._select(selected)

    def _select(self, key) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == key:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return

    def _on_selection(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._selected = None
        else:
            self._selected = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        if self._selected is not None:
            kind, value = self._selected
            room_id = ""
            if kind == "op":
                room_id = self._plan.operators[value].device.room_id
            else:
                room_id = rb.channel_room(self._project, self._plan.channels[value])
            self._fill_rooms(room_id or self._last_room_id)
        self._fill_channels()

    def _fill_channels(self) -> None:
        self._channels.clear()
        self._result.clear()
        selected = self._selected
        self._assign.setEnabled(selected is not None)
        if selected is None:
            self._title.setText("Links einen Taster wählen oder eine Taste drücken.")
            self._gas.clear()
            return
        kind, value = selected
        if kind == "ch":
            channel = self._plan.channels[value]
            self._title.setText(f"Aktorkanal {channel.label}")
            self._add_channel(channel.key, "", checked=True)
            self._gas.setText(self._ga_text(channel.addresses))
            return
        operator = self._plan.operators[value]
        self._title.setText(f"{value} {self._product(operator.device)}")
        keys = list(operator.channels)
        for key in keys:
            self._add_channel(key, "verknüpft")
        if not keys:
            item = QListWidgetItem("Keine Aktorkanäle verknüpft (z.B. nur über einen "
                                   "Logikserver) – vor Ort mit dem Rundgang zuordnen.")
            item.setFlags(Qt.NoItemFlags)
            self._channels.addItem(item)
        self._gas.setText(self._ga_text(operator.addresses, "Eigene GAs"))

    def _add_channel(self, key, source: str, checked: bool | None = None) -> None:
        channel = self._plan.channels[key]
        room_id = rb.channel_room(self._project, channel)
        room = rb.room_label(self._project, room_id)
        operators = [op.address for op in self._plan.operators_of(key)]
        text = f"{channel.label} ({channel.gewerk or 'SF'}) · {len(channel.addresses)} GAs"
        if source:
            text += f" · {source}"
        if len(operators) > 1:
            text += f" · auch von {', '.join(o for o in operators if o != self._selected[1])}"
        text += f" · Raum: {room or '–'}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, key)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        if checked is None:
            checked = not room_id     # schon zugeordnete Kanäle nicht ungefragt verschieben
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._channels.addItem(item)

    def _ga_text(self, addresses: list[str], title: str = "GAs") -> str:
        if not addresses:
            return ""
        by_address = {ga.address: ga for ga in self._project.group_addresses.all_addresses()}
        names = [f"{a} {by_address[a].designation}" for a in addresses[:6] if a in by_address]
        more = f" … (+{len(addresses) - 6})" if len(addresses) > 6 else ""
        return f"{title}: " + "; ".join(names) + more

    # ── Aktionen ─────────────────────────────────────────────────────────

    def _new_room(self) -> None:
        floor, zone = rb.room_place(self._project, self._room.currentData() or "")
        dialog = NewRoomDialog(self._project, self, floor, zone)
        if dialog.exec() != QDialog.Accepted:
            return
        if self._bus is not None:
            self._bus.begin_change("Raum angelegt")
        room = dialog.create_room()
        if self._bus is not None:
            self._bus.emit_building_changed()
        self._fill_rooms(room.id)

    def _do_assign(self) -> None:
        if self._selected is None:
            return
        room_id = self._room.currentData() or ""
        room = next((r for _l, _f, r in rb.all_rooms(self._project) if r.id == room_id), None)
        if room is None:
            QMessageBox.information(self, "Räume zuordnen",
                                    "Zuerst einen Raum wählen oder «Neuer Raum…» anlegen.")
            return
        keys = []
        for row in range(self._channels.count()):
            item = self._channels.item(row)
            if item.checkState() == Qt.Checked and item.data(Qt.UserRole) is not None:
                keys.append(item.data(Qt.UserRole))
        kind, value = self._selected
        label = value if kind == "op" else self._plan.channels[value].label
        if self._bus is not None:
            self._bus.begin_change(f"Raum zugeordnet: {label}")
        result = rb.assign(self._project, self._plan, room,
                           value if kind == "op" else "", keys)
        if self._bus is not None:
            self._bus.emit_topology_changed()
            self._bus.emit_addresses_changed()
        self._last_room_id = room.id
        self._fill_table()
        self._fill_channels()
        self._result.setText(f"{rb.room_label(self._project, room.id)}: {result.text()}")
        self._result.setStyleSheet(f"color: {COLOR_OK};")
