"""
GA-Tabellenansicht mit allen Feldern (FA-822)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QAbstractItemView, QMenu,
)
from PySide6.QtCore import Signal, Qt
from ..widgets.search_filter_bar import SearchFilterBar
from ..dialogs.ga_edit_dialog import GaEditDialog
from ...models.group_address import GroupAddressStructure, GroupAddress
from ..column_utils import fit_columns


class AddressTableView(QWidget):
    """GA-Tabelle mit allen Feldern, sortierbar."""

    address_selected = Signal(str)
    ga_modified = Signal()  # Emitted when a GA was edited

    COLUMNS = [
        "Adresse", "Bezeichnung", "DPT", "Gewerk", "Raum",
        "Nr.", "Funktion", "Zentral", "Sicherheit",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._structure: GroupAddressStructure | None = None
        self._all_gas: list[GroupAddress] = []
        self._row_ga_map: dict[int, GroupAddress] = {}
        self._bus = None

        layout = QVBoxLayout(self)

        title = QLabel("Gruppenadressen - Tabelle")
        title.setObjectName("title")
        layout.addWidget(title)

        self._search_bar = SearchFilterBar(
            filters=[
                ("licht", "Licht"), ("jalousie", "Jalousie"),
                ("heizung", "Heizung"), ("lueftung", "Lüftung/Klima"),
                ("energie", "Energie"),
            ]
        )
        self._search_bar.search_changed.connect(self._apply_filter)
        self._search_bar.filter_changed.connect(self._apply_category_filter)
        layout.addWidget(self._search_bar)

        # Info-Label
        self._info_label = QLabel("")
        self._info_label.setObjectName("subtitle")
        layout.addWidget(self._info_label)

        # Tabelle
        self._table = QTableWidget()
        self._table.setColumnCount(len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._table)

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus."""
        self._bus = bus

    def set_structure(self, structure: GroupAddressStructure):
        self._structure = structure
        self._all_gas = structure.all_addresses()
        self._populate_table(self._all_gas)

    def _populate_table(self, addresses: list[GroupAddress]):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(addresses))
        self._row_ga_map.clear()

        for row, ga in enumerate(addresses):
            self._row_ga_map[row] = ga
            items = [
                ga.address,
                ga.designation if not ga.is_placeholder else "(Reserve)",
                ga.datapoint_type,
                ga.gewerk_code,
                ga.room_number,
                str(ga.element_number) if ga.element_number else "",
                ga.function_name,
                ga.central,
                ga.security,
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, ga.id)
                if ga.is_placeholder:
                    item.setForeground(Qt.gray)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        fit_columns(self._table)
        self._info_label.setText(f"{len(addresses)} Gruppenadressen")

    def _find_ga_for_row(self, row: int) -> GroupAddress | None:
        """Findet die GroupAddress für eine Tabellenzeile."""
        item = self._table.item(row, 0)
        if not item:
            return None
        ga_id = item.data(Qt.UserRole)
        for ga in self._all_gas:
            if ga.id == ga_id:
                return ga
        return None

    def _on_cell_clicked(self, row: int, col: int):
        addr_item = self._table.item(row, 0)
        if addr_item:
            self.address_selected.emit(addr_item.text())

    def _on_cell_double_clicked(self, row: int, col: int):
        """Oeffnet den Bearbeitungsdialog per Doppelklick."""
        ga = self._find_ga_for_row(row)
        if ga:
            self._edit_ga(ga)

    def _show_context_menu(self, pos):
        """Kontextmenue mit Bearbeiten-Option."""
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        ga = self._find_ga_for_row(row)
        if not ga:
            return
        menu = QMenu(self)
        edit_action = menu.addAction("Bearbeiten...")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == edit_action:
            self._edit_ga(ga)

    def _edit_ga(self, ga: GroupAddress):
        """Oeffnet den GA-Bearbeitungsdialog."""
        dialog = GaEditDialog(ga, parent=self)
        if dialog.exec() == GaEditDialog.Accepted:
            self._populate_table(self._all_gas)
            self.ga_modified.emit()

    def _apply_filter(self, search: str):
        search = search.lower()
        for row in range(self._table.rowCount()):
            visible = False
            if not search:
                visible = True
            else:
                for col in range(self._table.columnCount()):
                    item = self._table.item(row, col)
                    if item and search in item.text().lower():
                        visible = True
                        break
            self._table.setRowHidden(row, not visible)

    def _apply_category_filter(self, category: str):
        if not category:
            for row in range(self._table.rowCount()):
                self._table.setRowHidden(row, False)
            return

        category_codes = {
            "licht":    {"L", "LD", "LDA", "LC", "LCT", "LCW", "DMX", "S", "SD"},
            "jalousie": {"J", "R", "M", "T", "DF"},
            "heizung":  {"H", "WP", "TF"},
            "lueftung": {"LU", "KL", "V"},
            "energie":  {"EV", "PV", "SP", "E"},
        }
        codes = category_codes.get(category, set())

        for row in range(self._table.rowCount()):
            gewerk_item = self._table.item(row, 3)
            visible = gewerk_item and gewerk_item.text() in codes
            self._table.setRowHidden(row, not visible)
