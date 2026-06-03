"""
Gewerke-Übersicht pro Raum/Stockwerk (FA-300) – editierbar in der manuellen Phase.

Zeigt alle Räume mit ihren Gewerk-Zuweisungen. Der Integrator kann ohne
den Wizard Gewerke hinzufügen, entfernen und die Anzahl anpassen.
Änderungen werden sofort über den ProjectBus an alle anderen Views gemeldet.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel,
    QAbstractItemView, QComboBox, QHBoxLayout, QPushButton, QSpinBox,
    QGroupBox,
)
from PySide6.QtCore import Qt, Signal

from ...models.building import Areal, GewerkAssignment
from ...models.gewerk import GewerkCatalog
from ..column_utils import fit_columns

# Spalten-Indizes
_COL_FLOOR   = 0
_COL_APT     = 1
_COL_ROOM    = 2
_COL_NUMBER  = 3
_COL_GCODE   = 4
_COL_GNAME   = 5
_COL_COUNT   = 6
_COL_ACTION  = 7
_NUM_COLS    = 8


class GewerkView(QWidget):
    """Gewerke-Übersicht: Welche Gewerke in welchem Raum – editierbar."""

    functions_changed = Signal()   # nach jeder manuellen Änderung

    def __init__(self, parent=None):
        super().__init__(parent)
        self._areal: Areal | None = None
        self._catalog: GewerkCatalog | None = None
        self._project = None
        self._bus = None

        layout = QVBoxLayout(self)

        title = QLabel("Gewerke-Übersicht")
        title.setObjectName("title")
        layout.addWidget(title)

        # Filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Stockwerk:"))
        self._floor_combo = QComboBox()
        self._floor_combo.addItem("Alle", "")
        self._floor_combo.currentIndexChanged.connect(self._on_floor_changed)
        filter_layout.addWidget(self._floor_combo)

        filter_layout.addWidget(QLabel("Wohnung/Zone:"))
        self._zone_combo = QComboBox()
        self._zone_combo.addItem("Alle", "")
        self._zone_combo.currentIndexChanged.connect(self._refresh_table)
        filter_layout.addWidget(self._zone_combo)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Info
        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        # Tabelle
        self._table = QTableWidget()
        self._table.setColumnCount(_NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            "Stockwerk", "Wohnung/Zone", "Raum", "Raumnr.",
            "Gewerk", "Name", "Anzahl", "Aktion",
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        # ── Gewerk hinzufügen ──
        add_group = QGroupBox("Gewerk zu selektiertem Raum hinzufügen")
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("Gewerk:"))
        self._gewerk_combo = QComboBox()
        add_layout.addWidget(self._gewerk_combo, 1)
        add_layout.addWidget(QLabel("Anzahl:"))
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 20)
        self._count_spin.setValue(1)
        add_layout.addWidget(self._count_spin)
        self._btn_add = QPushButton("Hinzufügen")
        self._btn_add.clicked.connect(self._add_gewerk)
        add_layout.addWidget(self._btn_add)
        add_group.setLayout(add_layout)
        layout.addWidget(add_group)

    # ── API ──

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus."""
        self._bus = bus

    def set_project(self, project):
        """Setzt das Projekt und aktualisiert die Ansicht vollständig."""
        self._project = project
        self._gewerk_combo.clear()
        for code in project.gewerk_catalog.all_codes():
            g = project.gewerk_catalog.get(code)
            self._gewerk_combo.addItem(f"{code} – {g.name}", code)
        self.set_data(project.areal, project.gewerk_catalog)

    def set_data(self, areal: Areal, catalog: GewerkCatalog):
        """Aktualisiert Daten (backward-kompatibel mit _update_views)."""
        self._areal = areal
        self._catalog = catalog

        self._floor_combo.blockSignals(True)
        self._floor_combo.clear()
        self._floor_combo.addItem("Alle", "")
        for floor in areal.all_floors:
            self._floor_combo.addItem(
                f"{floor.short_code} – {floor.name}", floor.id
            )
        self._floor_combo.blockSignals(False)

        self._refresh_zone_combo()
        self._refresh_table()

    # ── Interne Helfer ──

    def _on_floor_changed(self):
        self._refresh_zone_combo()
        self._refresh_table()

    def _refresh_zone_combo(self):
        if not self._areal:
            return
        floor_id = self._floor_combo.currentData()
        seen: dict[str, str] = {}
        for floor in self._areal.all_floors:
            if floor_id and floor.id != floor_id:
                continue
            for apt in floor.apartments:
                if apt.name not in seen:
                    seen[apt.name] = apt.id

        self._zone_combo.blockSignals(True)
        self._zone_combo.clear()
        self._zone_combo.addItem("Alle", "")
        for name in seen:
            self._zone_combo.addItem(name, name)
        self._zone_combo.blockSignals(False)

    def _refresh_table(self):
        if not self._areal or not self._catalog:
            return

        floor_id  = self._floor_combo.currentData()
        zone_name = self._zone_combo.currentData()

        rows: list[tuple] = []
        for floor in self._areal.all_floors:
            if floor_id and floor.id != floor_id:
                continue
            for apt in floor.apartments:
                if zone_name and apt.name != zone_name:
                    continue
                for room in apt.rooms:
                    if room.gewerk_assignments:
                        for ga in room.gewerk_assignments:
                            gewerk = self._catalog.get(ga.gewerk_code)
                            rows.append((floor, apt, room, ga, gewerk))
                    else:
                        rows.append((floor, apt, room, None, None))

        self._table.setRowCount(len(rows))
        for i, (floor, apt, room, ga, gewerk) in enumerate(rows):
            floor_item = QTableWidgetItem(floor.short_code)
            floor_item.setData(Qt.UserRole, (floor, apt, room))
            self._table.setItem(i, _COL_FLOOR,  floor_item)
            self._table.setItem(i, _COL_APT,    QTableWidgetItem(apt.name))
            self._table.setItem(i, _COL_ROOM,   QTableWidgetItem(room.name))
            self._table.setItem(i, _COL_NUMBER, QTableWidgetItem(room.number))

            if ga:
                self._table.setItem(i, _COL_GCODE, QTableWidgetItem(ga.gewerk_code))
                self._table.setItem(i, _COL_GNAME, QTableWidgetItem(gewerk.name if gewerk else "?"))

                # Anzahl: SpinBox für Inline-Editing
                spin = QSpinBox()
                spin.setRange(1, 20)
                spin.setValue(ga.count)
                spin.setFrame(False)
                spin.valueChanged.connect(
                    lambda val, g=ga: self._on_count_changed(g, val)
                )
                self._table.setCellWidget(i, _COL_COUNT, spin)

                # Aktion: Entfernen-Button
                btn_del = QPushButton("✕")
                btn_del.setFixedWidth(30)
                btn_del.setObjectName("danger")
                btn_del.setToolTip(f"Gewerk {ga.gewerk_code} aus Raum entfernen")
                btn_del.clicked.connect(
                    lambda checked, r=room, g=ga: self._remove_gewerk(r, g)
                )
                self._table.setCellWidget(i, _COL_ACTION, btn_del)
            else:
                self._table.setItem(i, _COL_GCODE, QTableWidgetItem(""))
                self._table.setItem(i, _COL_GNAME, QTableWidgetItem("(keine Gewerke)"))

        fit_columns(self._table)

        assignments = sum(1 for _, _, _, ga, _ in rows if ga)
        total_ga = sum(
            (
                (self._catalog.get(ga.gewerk_code).ga_count
                 if self._catalog.get(ga.gewerk_code) else 0)
                + len(ga.extra_entries)
            ) * ga.count
            for _, _, _, ga, _ in rows
            if ga
        )
        self._info.setText(
            f"{assignments} Gewerk-Zuweisungen | {total_ga} Gruppenadressen total"
        )

    # ── Mutations ──

    def _on_count_changed(self, ga: GewerkAssignment, value: int):
        ga.count = value
        self._emit_changed()

    def _add_gewerk(self):
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, _COL_FLOOR)
        if not item:
            return
        _, _, room = item.data(Qt.UserRole)
        if not room:
            return
        code  = self._gewerk_combo.currentData()
        count = self._count_spin.value()
        if not code:
            return
        if not any(ga.gewerk_code == code for ga in room.gewerk_assignments):
            if self._bus:
                self._bus.begin_change(f"Gewerk {code} zu »{room.name}« hinzufügen")
            room.gewerk_assignments.append(GewerkAssignment(gewerk_code=code, count=count))
            self._refresh_table()
            self._emit_changed()

    def _remove_gewerk(self, room, ga: GewerkAssignment):
        if self._bus:
            self._bus.begin_change(f"Gewerk {ga.gewerk_code} aus »{room.name}« entfernen")
        if ga in room.gewerk_assignments:
            room.gewerk_assignments.remove(ga)
        self._refresh_table()
        self._emit_changed()

    def _emit_changed(self):
        """Meldet Änderungen lokal und über den Bus."""
        self.functions_changed.emit()
        if self._bus:
            self._bus.emit_functions_changed()
