"""
Gewerke-Übersicht pro Raum/Stockwerk (FA-300) – editierbar in der manuellen Phase.

Zeigt alle Räume mit ihren Gewerk-Zuweisungen. Der Integrator kann ohne
den Wizard Gewerke hinzufügen, entfernen und die Anzahl anpassen.
Änderungen werden sofort über den ProjectBus an alle anderen Views gemeldet.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidgetItem, QLabel, QListWidgetItem,
    QAbstractItemView, QComboBox, QHBoxLayout, QPushButton, QSpinBox,
    QGroupBox, QSplitter, QHeaderView, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor

from ...models.building import Areal, GewerkAssignment
from ...models.gewerk import GewerkCatalog
from ...services.structure_move import (
    MAX_GEWERK_COUNT, add_gewerk, can_move_gewerk, move_gewerk,
)
from ..column_utils import fit_columns
from ..dialogs.custom_gewerk_dialog import CustomGewerkDialog
from ..styles import COLOR_WARNING
from ..widgets.drag_drop import DragDropTable, DragSourceList
from ..wizard.step05_gewerke import label_hint

# Spalten-Indizes
_COL_FLOOR   = 0
_COL_APT     = 1
_COL_ROOM    = 2
_COL_NUMBER  = 3
_COL_GCODE   = 4
_COL_GNAME   = 5
_COL_LABEL   = 6   # Klartext je Element (FA-403), wie im Wizard Schritt 5
_COL_COUNT   = 7
_COL_ACTION  = 8
_NUM_COLS    = 9

_LABEL_SEP = ";"
_MAX_NAME_WIDTH = 200   # Gewerk-Name, längere stehen im Tooltip
_MIN_NAME_WIDTH = 120
_MIN_LABEL_WIDTH = 220  # Bezeichnung
_COUNT_WIDTH = 84       # SpinBox Anzahl


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

        header_layout = QHBoxLayout()
        title = QLabel("Gewerke-Übersicht")
        title.setObjectName("title")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self._btn_custom_gewerk = QPushButton("Eigenes Gewerk anlegen…")
        self._btn_custom_gewerk.setToolTip(
            "Für Bedarfe, die der Standard-Katalog nicht abdeckt -- z.B. ein "
            "Fremdsystem-Gateway (Musikanlage, individuelle Wärmepumpe) oder "
            "eine Zusatzfunktion eines Kombigeräts."
        )
        self._btn_custom_gewerk.clicked.connect(self._add_custom_gewerk)
        header_layout.addWidget(self._btn_custom_gewerk)
        layout.addLayout(header_layout)

        # Filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Stockwerk:"))
        self._floor_combo = QComboBox()
        self._floor_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._floor_combo.addItem("Alle", "")
        self._floor_combo.currentIndexChanged.connect(self._on_floor_changed)
        filter_layout.addWidget(self._floor_combo)

        filter_layout.addWidget(QLabel("Wohnung/Zone:"))
        self._zone_combo = QComboBox()
        self._zone_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._zone_combo.addItem("Alle", "")
        self._zone_combo.currentIndexChanged.connect(self._refresh_table)
        filter_layout.addWidget(self._zone_combo)

        filter_layout.addStretch()
        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        filter_layout.addWidget(self._info)
        layout.addLayout(filter_layout)

        # Tabelle; Gewerke aus dem Katalog auf einen Raum ziehen oder eine
        # Zuweisung in einen anderen Raum ziehen (FA-1015 c)
        self._table = DragDropTable()
        self._table.drag_data = self._drag_data
        self._table.target_data = self._row_room
        self._table.can_drop = self._can_drop
        self._table.on_drop = self._on_drop
        self._table.setColumnCount(_NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            "Stockwerk", "Wohnung/Zone", "Raum", "Raumnr.",
            "Gewerk", "Name", "Bezeichnung", "Anzahl", "Aktion",
        ])
        # Nur die Bezeichnung ist editierbar (Doppelklick, F2)
        self._table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self._table.itemChanged.connect(self._on_item_changed)
        self._refreshing = False
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        # KEIN setStretchLastSection: erzwingt sonst eine volle Breite der
        # Aktion-Spalte (der kleine Entfernen-Button wuerde ueber die ganze
        # Zeile gestreckt) und quetscht die uebrigen Spaltenkoepfe unlesbar
        # schmal. Stattdessen inhaltsbasierte Breite aus
        # fit_columns(..., stretch_to_fit=False), siehe address_table_view.py.

        catalog_box = QWidget()
        catalog_layout = QVBoxLayout(catalog_box)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_label = QLabel("Gewerk-Katalog")
        catalog_label.setObjectName("heading")
        catalog_layout.addWidget(catalog_label)
        catalog_hint = QLabel("Auf einen Raum ziehen. Eine Zeile der Tabelle "
                              "auf einen anderen Raum ziehen verschiebt das Gewerk.")
        catalog_hint.setObjectName("hint")
        catalog_hint.setWordWrap(True)
        catalog_layout.addWidget(catalog_hint)
        self._catalog_list = DragSourceList()
        self._catalog_list.drag_data = lambda item: ("code", item.data(Qt.UserRole))
        catalog_layout.addWidget(self._catalog_list)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._table)
        splitter.addWidget(catalog_box)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1000, 230])   # Katalog schmal, Tabelle breit
        splitter.splitterMoved.connect(lambda *_: self._fit_table_columns())
        # Die Tabelle erhält die ganze freie Höhe
        layout.addWidget(splitter, 1)

        # ── Gewerk hinzufügen ──
        add_group = QGroupBox("Gewerk zu selektiertem Raum hinzufügen")
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("Gewerk:"))
        self._gewerk_combo = QComboBox()
        self._gewerk_combo.setMinimumContentsLength(30)
        self._gewerk_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        add_layout.addWidget(self._gewerk_combo)
        add_layout.addWidget(QLabel("Anzahl:"))
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 20)
        self._count_spin.setValue(1)
        add_layout.addWidget(self._count_spin)
        self._btn_add = QPushButton("Hinzufügen")
        self._btn_add.clicked.connect(self._add_gewerk)
        add_layout.addWidget(self._btn_add)
        add_layout.addStretch()
        add_group.setLayout(add_layout)
        add_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(add_group)

    # ── API ──

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus."""
        self._bus = bus

    def set_project(self, project):
        """Setzt das Projekt und aktualisiert die Ansicht vollständig."""
        self._project = project
        self._refresh_gewerk_combo()
        self.set_data(project.areal, project.gewerk_catalog)

    def _refresh_gewerk_combo(self):
        self._gewerk_combo.clear()
        self._catalog_list.clear()
        for code in self._project.gewerk_catalog.all_codes():
            g = self._project.gewerk_catalog.get(code)
            self._gewerk_combo.addItem(f"{code} – {g.name}", code)
            item = QListWidgetItem(f"{code} – {g.name}")
            item.setData(Qt.UserRole, code)
            self._catalog_list.addItem(item)

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

        self._refreshing = True
        self._table.clearContents()
        self._table.setRowCount(len(rows))
        for i, (floor, apt, room, ga, gewerk) in enumerate(rows):
            floor_item = _read_only(floor.short_code)
            floor_item.setData(Qt.UserRole, (floor, apt, room))
            self._table.setItem(i, _COL_FLOOR,  floor_item)
            self._table.setItem(i, _COL_APT,    _read_only(apt.name))
            self._table.setItem(i, _COL_ROOM,   _read_only(room.name))
            self._table.setItem(i, _COL_NUMBER, _read_only(room.number))

            if ga:
                self._table.setItem(i, _COL_GCODE, _read_only(ga.gewerk_code))
                name_item = _read_only(gewerk.name if gewerk else "?")
                name_item.setToolTip(name_item.text())
                self._table.setItem(i, _COL_GNAME, name_item)

                # Bezeichnung – editierbar: Klartext je Element, getrennt mit ";"
                label_item = QTableWidgetItem(f"{_LABEL_SEP} ".join(ga.element_labels))
                label_item.setData(Qt.UserRole, (room, ga))
                self._style_label_item(label_item)
                self._table.setItem(i, _COL_LABEL, label_item)

                # Anzahl: SpinBox für Inline-Editing
                spin = _NoWheelSpinBox()
                spin.setRange(1, 20)
                spin.setValue(ga.count)
                spin.setFrame(False)
                spin.valueChanged.connect(
                    lambda val, g=ga: self._on_count_changed(g, val)
                )
                self._table.setCellWidget(i, _COL_COUNT, spin)

                # Aktion: Entfernen-Button. In ein Container-Widget mit
                # Layout einbetten statt den Button direkt als Cell-Widget
                # zu setzen -- sonst streckt QTableWidget den Button trotz
                # setFixedWidth() auf die volle Zellenbreite/-hoehe (siehe
                # gleiches Muster in step05_gewerke.py).
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(2, 1, 2, 1)

                btn_del = QPushButton("✕")
                btn_del.setFixedWidth(30)
                btn_del.setObjectName("danger")
                # Globales QPushButton-Padding (8px 16px) ist breiter als
                # dieser schmale Button -- ohne Override verschwindet das "✕"
                # spurlos, weil kein Platz fuer den Text bleibt.
                btn_del.setStyleSheet("padding: 2px;")
                btn_del.setToolTip(f"Gewerk {ga.gewerk_code} aus Raum entfernen")
                btn_del.clicked.connect(
                    lambda checked, r=room, g=ga: self._remove_gewerk(r, g)
                )
                action_layout.addWidget(btn_del)
                action_layout.addStretch()
                self._table.setCellWidget(i, _COL_ACTION, action_widget)
            else:
                self._table.setItem(i, _COL_GCODE, _read_only(""))
                self._table.setItem(i, _COL_GNAME, _read_only("(keine Gewerke)"))
                self._table.setItem(i, _COL_LABEL, _read_only(""))
        self._refreshing = False

        self._fit_table_columns()

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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._table.rowCount():
            self._fit_table_columns()

    def _fit_table_columns(self) -> None:
        """Spalten nach Inhalt, aber ohne horizontales Scrollen: Name
        begrenzt, Anzahl/Aktion schmal, die Bezeichnung füllt den Rest
        (lange Texte stehen vollständig im Tooltip)."""
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_LABEL, QHeaderView.Interactive)
        fit_columns(self._table, stretch_to_fit=False)
        self._table.setColumnWidth(_COL_GNAME, min(self._table.columnWidth(_COL_GNAME),
                                                   _MAX_NAME_WIDTH))
        self._table.setColumnWidth(_COL_COUNT, _COUNT_WIDTH)
        # Wenig Platz (z.B. 1366 x 768): Name zugunsten der Bezeichnung kürzen
        others = sum(self._table.columnWidth(c) for c in range(_NUM_COLS) if c != _COL_LABEL)
        missing = _MIN_LABEL_WIDTH - (self._table.viewport().width() - others)
        if missing > 0:
            name_width = self._table.columnWidth(_COL_GNAME)
            self._table.setColumnWidth(_COL_GNAME, max(_MIN_NAME_WIDTH, name_width - missing))
        header.setSectionResizeMode(_COL_LABEL, QHeaderView.Stretch)

    # ── Ziehen und Ablegen (FA-1015 c) ──

    def _row_data(self, item) -> tuple | None:
        """(floor, apt, room) der Tabellenzeile eines Eintrags."""
        cell = self._table.item(item.row(), _COL_FLOOR)
        return cell.data(Qt.UserRole) if cell else None

    def _row_room(self, item):
        data = self._row_data(item)
        return data[2] if data else None

    def _drag_data(self, item):
        data = self._row_data(item)
        code_item = self._table.item(item.row(), _COL_GCODE)
        if not data or not code_item or not code_item.text():
            return None
        room = data[2]
        assignment = next((g for g in room.gewerk_assignments
                           if g.gewerk_code == code_item.text()), None)
        return ("assignment", room, assignment) if assignment else None

    @staticmethod
    def _drop_allowed(entry, room) -> bool:
        if entry[0] == "code":
            existing = next((g for g in room.gewerk_assignments
                             if g.gewerk_code == entry[1]), None)
            return existing is None or existing.count < MAX_GEWERK_COUNT
        _kind, source, assignment = entry
        return can_move_gewerk(source, assignment, room)

    def _can_drop(self, payload: list, room) -> bool:
        return any(self._drop_allowed(entry, room) for entry in payload)

    def _on_drop(self, payload: list, room) -> None:
        entries = [e for e in payload if self._drop_allowed(e, room)]
        if not entries:
            return
        if self._bus:
            codes = ", ".join(e[1] if e[0] == "code" else e[2].gewerk_code for e in entries)
            verb = "hinzufügen" if entries[0][0] == "code" else "verschieben"
            self._bus.begin_change(f"Gewerk {codes} nach »{room.name}« {verb}")
        for entry in entries:
            if entry[0] == "code":
                add_gewerk(room, entry[1])
            else:
                move_gewerk(self._areal, entry[1], entry[2], room)
        self._refresh_table()
        self._emit_changed()

    # ── Mutations ──

    @staticmethod
    def _style_label_item(item: QTableWidgetItem) -> None:
        """Tooltip mit der Zuordnung Text → Element; orange, wenn mehr Texte
        als Elemente erfasst sind (wie im Wizard Schritt 5)."""
        room, ga = item.data(Qt.UserRole)
        tooltip, warning = label_hint(ga, room.number, room.name)
        item.setToolTip(tooltip)
        item.setForeground(QBrush(QColor(COLOR_WARNING)) if warning else QBrush())

    def _on_item_changed(self, item: QTableWidgetItem):
        """Bezeichnung ins Modell übernehmen; die GAs tragen sie im Namen."""
        if self._refreshing or item.column() != _COL_LABEL or not item.data(Qt.UserRole):
            return
        room, ga = item.data(Qt.UserRole)
        old = list(ga.element_labels)
        new = f"{_LABEL_SEP} ".join(old)
        if item.text() != new:
            if self._bus:
                self._bus.begin_change(
                    f"Bezeichnung {ga.gewerk_code} in »{room.name}« bearbeiten")
            ga.set_element_labels(item.text().split(_LABEL_SEP))
        self._refreshing = True
        item.setText(f"{_LABEL_SEP} ".join(ga.element_labels))
        self._style_label_item(item)
        self._refreshing = False
        if ga.element_labels != old:
            # Neuberechnung baut die Tabelle neu auf: nicht im Signal der Zelle
            QTimer.singleShot(0, self._emit_changed)

    def _on_count_changed(self, ga: GewerkAssignment, value: int):
        ga.count = value
        # Zuordnung der Bezeichnungen hängt von der Anzahl ab
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_LABEL)
            data = item.data(Qt.UserRole) if item else None
            if data and data[1] is ga:
                self._refreshing = True
                self._style_label_item(item)
                self._refreshing = False
        self._emit_changed()

    def _add_custom_gewerk(self):
        """Öffnet den Dialog zum Anlegen eines benutzerdefinierten Gewerks (FA-303)."""
        if not self._project:
            return
        dlg = CustomGewerkDialog(self._project.gewerk_catalog, self)
        if not dlg.exec():
            return
        gewerk = dlg.get_gewerk()
        if not gewerk:
            return
        if self._bus:
            self._bus.begin_change(f"Eigenes Gewerk {gewerk.code} anlegen")
        self._project.add_custom_gewerk(gewerk)
        self._refresh_gewerk_combo()
        self.set_data(self._project.areal, self._project.gewerk_catalog)
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


def _read_only(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


class _NoWheelSpinBox(QSpinBox):
    """Anzahl in der Tabelle: das Mausrad ändert den Wert nur, wenn das Feld
    angeklickt ist; sonst scrollt es die Tabelle. Beim Scrollen über die
    Spalte hatte sich die Anzahl sonst unbemerkt geändert (Projekt_23:
    Jalousie COG01 1 -> 19, HG 2 lief über)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()
