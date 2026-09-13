"""
Dialog zur manuellen Verknüpfung einer GewerkAssignment mit einem
bestehenden Aktor-Kanal (FA-521f).

Dreistufig: Gerät wählen -> Kanal wählen -> Vorschau/Korrektur der
automatisch erkannten Funktions-Zuordnung (services/gewerk_channel_matching.py)
vor der Übernahme. Einzelne Slots lassen sich über den bereits vorhandenen
GaPickerDialog korrigieren oder leeren.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QPushButton, QHeaderView,
    QAbstractItemView, QDialogButtonBox, QStackedWidget, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush

from ...models.topology import Device, CommunicationObject
from ...services.address_generator import AddressGenerator
from ...services.gewerk_channel_matching import (
    group_channels_by_name, match_channel_to_schema, all_linked_ga_ids,
)
from .ga_picker_dialog import GaPickerDialog
from ..column_utils import fit_columns

_DEV_COL_ADDR = 0
_DEV_COL_PRODUCT = 1
_DEV_COL_LOCATION = 2

_CH_COL_NAME = 0
_CH_COL_OBJECTS = 1
_CH_COL_STATUS = 2

_PREV_COL_FUNCTION = 0
_PREV_COL_GA = 1
_PREV_COL_ACTION = 2

# Farben analog zum bestehenden Schema in co_linking_view.py.
_COLOR_ROOM_MATCH = QColor("#E8F5E9")    # Hellgruen: Geraet steht im Zielraum
_COLOR_ALREADY_OWN = QColor("#E3F2FD")   # Blau: Kanal bereits dieser Zuweisung zugeordnet
_COLOR_ALREADY_OTHER = QColor("#FFF9C4")  # Gelb: Kanal bereits einem anderen Gewerk zugewiesen


class GewerkChannelAssignDialog(QDialog):
    """Verknüpft eine GewerkAssignment mit einem bestehenden Aktor-Kanal.

    Ergebnis nach Accepted: `self.linked_ga_ids` ({function: GroupAddress.id}),
    vom Aufrufer in `assignment.linked_ga_ids` zu übernehmen (siehe
    step05_gewerke.py._assign_channel).
    """

    def __init__(self, project, room, assignment, gewerk, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aktor-Kanal zuweisen")
        self.setMinimumSize(700, 500)
        self._project = project
        self._room = room
        self._assignment = assignment
        self._gewerk = gewerk
        self.linked_ga_ids: dict[str, str] = {}

        gen = AddressGenerator(project.gewerk_catalog, variant=project.config.mg_variant)
        self._schema = gen._get_block_schema(gewerk, assignment=assignment, is_feedback=False)

        self._selected_device: Device | None = None
        self._selected_channel: str = ""
        self._matched: dict[str, object] = {}  # function -> GroupAddress

        layout = QVBoxLayout(self)
        title = f"Gewerk: {gewerk.code} – {gewerk.name}  |  Raum: {room.name}"
        info = QLabel(title)
        info.setStyleSheet("color: #555;")
        layout.addWidget(info)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        self._stack.addWidget(self._build_device_page())
        self._stack.addWidget(self._build_channel_page())
        self._stack.addWidget(self._build_preview_page())

        self._reload_devices()

    def showEvent(self, event):
        super().showEvent(event)
        # Beim ersten Befuellen (in __init__) ist der Viewport noch 0px
        # breit -- fit_columns() konnte die Spalten daher nur nach Inhalt,
        # nicht nach verfuegbarer Breite ausrichten. Jetzt nachholen.
        fit_columns(self._device_table)

    # ── Seite 1: Gerät ──────────────────────────────────────────────

    def _build_device_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)

        filter_row = QHBoxLayout()
        self._device_filter_addr = QLineEdit()
        self._device_filter_addr.setPlaceholderText("Adresse filtern…")
        self._device_filter_addr.setClearButtonEnabled(True)
        self._device_filter_addr.textChanged.connect(self._apply_device_filter)
        filter_row.addWidget(self._device_filter_addr, 1)

        self._device_filter_product = QLineEdit()
        self._device_filter_product.setPlaceholderText("Produkt filtern…")
        self._device_filter_product.setClearButtonEnabled(True)
        self._device_filter_product.textChanged.connect(self._apply_device_filter)
        filter_row.addWidget(self._device_filter_product, 2)

        self._device_filter_location = QLineEdit()
        self._device_filter_location.setPlaceholderText("Einbauort filtern…")
        self._device_filter_location.setClearButtonEnabled(True)
        self._device_filter_location.textChanged.connect(self._apply_device_filter)
        filter_row.addWidget(self._device_filter_location, 1)
        v.addLayout(filter_row)

        hint = QLabel("Grün hervorgehoben: Gerät steht im Zielraum dieser Zuweisung.")
        hint.setStyleSheet("color: #555;")
        v.addWidget(hint)

        self._device_table = QTableWidget(0, 3)
        self._device_table.setHorizontalHeaderLabels(["Adresse", "Produkt", "Einbauort"])
        self._device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._device_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._device_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._device_table.setSortingEnabled(True)
        self._device_table.sortByColumn(_DEV_COL_ADDR, Qt.AscendingOrder)
        self._device_table.doubleClicked.connect(self._on_device_chosen)
        v.addWidget(self._device_table, 1)

        row = QHBoxLayout()
        row.addStretch()
        btn_next = QPushButton("Weiter…")
        btn_next.clicked.connect(self._on_device_chosen)
        row.addWidget(btn_next)
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        v.addLayout(row)
        return page

    def _all_devices(self) -> list[Device]:
        return [
            d
            for area in self._project.topology.areas
            for line in area.lines
            for d in line.devices
            if d.communication_objects
        ]

    def _reload_devices(self):
        devices = self._all_devices()
        devices.sort(key=lambda d: d.physical_address)
        self._devices = devices
        self._apply_device_filter()

    def _apply_device_filter(self):
        addr_f = self._device_filter_addr.text().strip().lower()
        product_f = self._device_filter_product.text().strip().lower()
        location_f = self._device_filter_location.text().strip().lower()
        self._filtered_devices = [
            d for d in self._devices
            if (not addr_f or addr_f in d.physical_address.lower())
            and (not product_f or product_f in f"{d.manufacturer} {d.product}".lower())
            and (not location_f or location_f in (d.installation_location or "").lower())
        ]
        # Sortierung waehrend des Befuellens aus -- sonst sortiert Qt nach
        # jeder einzelnen setItem()-Zelle neu und die Zeilen verrutschen.
        # Aktuellen Sortierzustand merken und danach explizit wiederherstellen:
        # setSortingEnabled(True) alleine reicht nicht -- Qt greift sonst auf
        # eine ueberraschende Standard-Sortierung zurueck (siehe Kommentar in
        # showEvent-Nachbarschaft, empirisch verifiziert).
        header = self._device_table.horizontalHeader()
        sort_col, sort_order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        self._device_table.setSortingEnabled(False)
        self._device_table.setRowCount(len(self._filtered_devices))
        room_brush = QBrush(_COLOR_ROOM_MATCH)
        for i, d in enumerate(self._filtered_devices):
            product = f"{d.manufacturer} {d.product}".strip()
            self._device_table.setItem(i, _DEV_COL_ADDR, QTableWidgetItem(d.physical_address))
            self._device_table.setItem(i, _DEV_COL_PRODUCT, QTableWidgetItem(product))
            self._device_table.setItem(
                i, _DEV_COL_LOCATION, QTableWidgetItem(d.installation_location),
            )
            if d.room_id and d.room_id == self._room.id:
                for col in (_DEV_COL_ADDR, _DEV_COL_PRODUCT, _DEV_COL_LOCATION):
                    self._device_table.item(i, col).setBackground(room_brush)
        self._device_table.setSortingEnabled(True)
        if sort_col >= 0:
            self._device_table.sortByColumn(sort_col, sort_order)
        fit_columns(self._device_table)

    def _on_device_chosen(self):
        selected = self._device_table.selectionModel().selectedRows()
        if not selected:
            return
        # Ueber die Adress-Zelle statt Zeilenindex nachschlagen -- die
        # Tabelle ist sortierbar, ihre Zeilenreihenfolge entspricht nach
        # einem Klick auf den Spaltenkopf nicht mehr der Reihenfolge von
        # self._filtered_devices.
        addr = self._device_table.item(selected[0].row(), _DEV_COL_ADDR).text()
        device = next((d for d in self._filtered_devices if d.physical_address == addr), None)
        if not device:
            return
        self._selected_device = device
        self._reload_channels()
        self._stack.setCurrentIndex(1)

    # ── Seite 2: Kanal ──────────────────────────────────────────────

    def _build_channel_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        hint = QLabel(
            "Gelb: Kanal ist bereits einem anderen Gewerk zugewiesen — bitte "
            "prüfen, bevor er hier erneut verwendet wird. Blau: Kanal ist "
            "bereits dieser Zuweisung zugeordnet."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555;")
        v.addWidget(hint)

        self._channel_table = QTableWidget(0, 3)
        self._channel_table.setHorizontalHeaderLabels(["Kanal", "ComObjects", "Status"])
        self._channel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._channel_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._channel_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._channel_table.doubleClicked.connect(self._on_channel_chosen)
        v.addWidget(self._channel_table, 1)

        row = QHBoxLayout()
        btn_back = QPushButton("Zurück")
        btn_back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        row.addWidget(btn_back)
        row.addStretch()
        btn_next = QPushButton("Weiter…")
        btn_next.clicked.connect(self._on_channel_chosen)
        row.addWidget(btn_next)
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        v.addLayout(row)
        return page

    def _reload_channels(self):
        self._channels = group_channels_by_name(self._selected_device)
        names = sorted(self._channels.keys())
        self._channel_names = names
        self._channel_table.setRowCount(len(names))
        for i, name in enumerate(names):
            cos = self._channels[name]
            summary = ", ".join(co.object_function for co in cos if co.object_function)
            status_text, color = self._channel_status(cos)
            self._channel_table.setItem(i, _CH_COL_NAME, QTableWidgetItem(name))
            self._channel_table.setItem(i, _CH_COL_OBJECTS, QTableWidgetItem(summary))
            self._channel_table.setItem(i, _CH_COL_STATUS, QTableWidgetItem(status_text))
            if color:
                brush = QBrush(color)
                for col in (_CH_COL_NAME, _CH_COL_OBJECTS, _CH_COL_STATUS):
                    self._channel_table.item(i, col).setBackground(brush)
        fit_columns(self._channel_table)

    def _channel_status(self, cos: list[CommunicationObject]) -> tuple[str, QColor | None]:
        """Prüft, ob die GAs dieses Kanals bereits über eine
        GewerkAssignment verknüpft sind -- entweder schon dieser Zuweisung
        (informativ) oder einer anderen (Achtung, Doppelverwendung möglich,
        siehe Vorschlag zur besseren Auffindbarkeit des passenden Aktors)."""
        ga_by_address = {
            ga.address: ga for ga in self._project.group_addresses.all_addresses()
        }
        own_ids = set(self._assignment.linked_ga_ids.values())
        all_linked = all_linked_ga_ids(self._project)
        other_hits: set[str] = set()
        own_hit = False
        for co in cos:
            for addr in co.connected_gas:
                ga = ga_by_address.get(addr)
                if not ga:
                    continue
                if ga.id in own_ids:
                    own_hit = True
                elif ga.id in all_linked:
                    gewerk_code, room_number = all_linked[ga.id]
                    other_hits.add(f"{gewerk_code} Raum {room_number}")
        if other_hits:
            return f"⚠ bereits verwendet: {', '.join(sorted(other_hits))}", _COLOR_ALREADY_OTHER
        if own_hit:
            return "✓ bereits dieser Zuweisung zugeordnet", _COLOR_ALREADY_OWN
        return "", None

    def _on_channel_chosen(self):
        selected = self._channel_table.selectionModel().selectedRows()
        if not selected:
            return
        self._selected_channel = self._channel_names[selected[0].row()]
        self._run_matching()
        self._stack.setCurrentIndex(2)

    # ── Seite 3: Vorschau/Korrektur ─────────────────────────────────

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        hint = QLabel(
            "Automatisch erkannte Zuordnung — bei Bedarf über \"Ändern\" "
            "korrigieren oder mit \"Leeren\" auf automatische Generierung "
            "zurücksetzen."
        )
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._preview_table = QTableWidget(0, 3)
        self._preview_table.setHorizontalHeaderLabels(["Funktion", "Gruppenadresse", ""])
        self._preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview_table.horizontalHeader().setSectionResizeMode(
            _PREV_COL_GA, QHeaderView.Stretch,
        )
        v.addWidget(self._preview_table, 1)

        row = QHBoxLayout()
        btn_back = QPushButton("Zurück")
        btn_back.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        row.addWidget(btn_back)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        v.addLayout(row)
        return page

    def _run_matching(self):
        cos = self._channels.get(self._selected_channel, [])
        matched_cos = match_channel_to_schema(cos, self._schema) if self._schema else {}
        ga_by_address = {
            ga.address: ga for ga in self._project.group_addresses.all_addresses()
        }
        self._matched = {}
        for function, co in matched_cos.items():
            if not co.connected_gas:
                continue
            ga = ga_by_address.get(co.connected_gas[0])
            if ga:
                self._matched[function] = ga
        self._refresh_preview()

    def _refresh_preview(self):
        entries = [
            e for e in (self._schema.entries if self._schema else [])
            if not e.is_reserve and e.function
        ]
        self._preview_functions = [e.function for e in entries]
        self._preview_table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            self._preview_table.setItem(i, _PREV_COL_FUNCTION, QTableWidgetItem(entry.function))
            ga = self._matched.get(entry.function)
            text = f"{ga.designation} ({ga.address})" if ga else "— automatisch generieren —"
            self._preview_table.setItem(i, _PREV_COL_GA, QTableWidgetItem(text))

            btn = QPushButton("Ändern" if ga else "Zuweisen")
            btn.clicked.connect(lambda checked, f=entry.function: self._change_slot(f))
            self._preview_table.setCellWidget(i, _PREV_COL_ACTION, btn)
        fit_columns(self._preview_table)

    def _change_slot(self, function: str):
        current = self._matched.get(function)
        dlg = GaPickerDialog(
            self._project, self._room, gewerk_hint=self._gewerk.code,
            current_ga_designation=current.designation if current else "",
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.clear_requested:
            self._matched.pop(function, None)
        elif dlg.selected_ga:
            self._matched[function] = dlg.selected_ga
        self._refresh_preview()

    def _on_accept(self):
        self.linked_ga_ids = {
            function: ga.id for function, ga in self._matched.items()
        }
        self.accept()
