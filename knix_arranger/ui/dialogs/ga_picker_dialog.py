"""
GA-Auswahldialog für die Verknüpfungsmatrix (FA-2503).

Zeigt Gruppenadressen eines Raums (mit Fallback auf alle Adressen bei Bedarf),
durchsuchbar per Freitext, sortiert mit dem zur Funktionsspalte passenden
Gewerk-Code zuerst.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QPushButton, QHeaderView,
    QAbstractItemView, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from ...models.group_address import GroupAddress

_COL_DESIG = 0
_COL_ADDR = 1
_COL_GEWERK = 2
_COL_DPT = 3


class GaPickerDialog(QDialog):
    """Wählt eine Gruppenadresse für eine Verknüpfungsmatrix-Zelle aus (FA-2503)."""

    def __init__(
        self, project, room, gewerk_hint: str = "",
        current_ga_designation: str = "", parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Gruppenadresse zuweisen")
        self.setMinimumSize(640, 480)
        self._project = project
        self._room = room
        self._gewerk_hint = gewerk_hint
        self._filtered: list[GroupAddress] = []
        self.selected_ga: GroupAddress | None = None
        self.clear_requested = False

        layout = QVBoxLayout(self)

        info_text = f"Raum: {room.name} ({room.number})" if room.number else f"Raum: {room.name}"
        if gewerk_hint:
            info_text += f"  |  passendes Gewerk: {gewerk_hint}"
        info = QLabel(info_text)
        info.setStyleSheet("color: #555;")
        layout.addWidget(info)

        top_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Suche nach Bezeichnung oder Adresse…")
        self._search.textChanged.connect(self._apply_filter)
        top_row.addWidget(self._search, 1)
        self._only_room = QCheckBox("Nur GAs dieses Raums")
        self._only_room.setChecked(True)
        self._only_room.toggled.connect(self._reload)
        top_row.addWidget(self._only_room)
        layout.addLayout(top_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Bezeichnung", "Adresse", "Gewerk", "DPT"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(_COL_DESIG, QHeaderView.Stretch)
        self._table.doubleClicked.connect(self._on_accept)
        layout.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        self._btn_clear = QPushButton("Zuweisung entfernen")
        self._btn_clear.setVisible(bool(current_ga_designation))
        self._btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(self._btn_clear)
        btn_row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

        self._all_gas: list[GroupAddress] = []
        self._reload()
        self._select_designation(current_ga_designation)

    def _reload(self):
        gas = [ga for ga in self._project.group_addresses.all_addresses() if not ga.is_placeholder]
        if self._only_room.isChecked():
            room_gas = [
                ga for ga in gas
                if ga.room_id == self._room.id
                or (ga.room_number and ga.room_number == self._room.number)
            ]
            # Ohne raumeigene GAs lieber alle anzeigen als eine leere Liste
            self._all_gas = room_gas or gas
        else:
            self._all_gas = gas
        self._all_gas.sort(key=lambda g: (g.gewerk_code != self._gewerk_hint, g.designation))
        self._apply_filter()

    def _apply_filter(self):
        text = self._search.text().strip().lower()
        self._filtered = [
            ga for ga in self._all_gas
            if not text or text in ga.designation.lower() or text in ga.address.lower()
        ]
        self._table.setRowCount(len(self._filtered))
        for i, ga in enumerate(self._filtered):
            self._table.setItem(i, _COL_DESIG, QTableWidgetItem(ga.designation))
            self._table.setItem(i, _COL_ADDR, QTableWidgetItem(ga.address))
            self._table.setItem(i, _COL_GEWERK, QTableWidgetItem(ga.gewerk_code))
            self._table.setItem(i, _COL_DPT, QTableWidgetItem(ga.datapoint_type))

    def _select_designation(self, designation: str):
        if not designation:
            return
        for i, ga in enumerate(self._filtered):
            if ga.designation == designation:
                self._table.selectRow(i)
                self._table.scrollToItem(self._table.item(i, _COL_DESIG))
                break

    def _on_accept(self):
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            self.reject()
            return
        self.selected_ga = self._filtered[selected[0].row()]
        self.accept()

    def _on_clear(self):
        self.clear_requested = True
        self.accept()
