"""
Topologie-Zuordnungs-Dialog
Ermoeglicht das manuelle Zuweisen von Etagen oder Raeumen zu einer Linie.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QGroupBox, QComboBox,
    QMessageBox, QSplitter,
)
from PySide6.QtCore import Qt

from ...models.topology import Topology, Line
from ...models.building import Areal, Floor, Room


class TopologyAssignmentDialog(QDialog):
    """
    Dialog zum manuellen Zuordnen von Etagen/Raeumen zu Linien.

    Linke Liste:  Raeume, die dieser Linie zugewiesen sind.
    Rechte Liste: Alle anderen verfuegbaren Raeume (noch keiner Linie
                  oder einer anderen Linie zugewiesen).

    Etagen-Schnellzuweisung: Alle Raeume einer Etage auf einmal verschieben.
    """

    def __init__(
        self,
        topology: Topology,
        areal: Areal,
        current_line: Line,
        parent=None,
    ):
        super().__init__(parent)
        self._topology = topology
        self._areal = areal
        self._line = current_line

        # Arbeitskopien der Zuordnungen (room_id -> line)
        self._assignments: dict[str, Line] = {}
        self._build_assignments()

        self.setWindowTitle(
            f"Zuordnung: Linie {current_line.line_number} – {current_line.name}"
        )
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # Etagen-Schnellzuweisung
        floor_bar = QHBoxLayout()
        floor_bar.addWidget(QLabel("Etage zuweisen:"))
        self._floor_combo = QComboBox()
        self._floor_combo.setMinimumWidth(200)
        self._populate_floors()
        floor_bar.addWidget(self._floor_combo)
        btn_floor = QPushButton("Alle Räume dieser Etage →")
        btn_floor.clicked.connect(self._assign_floor)
        floor_bar.addWidget(btn_floor)
        floor_bar.addStretch()
        layout.addLayout(floor_bar)

        # Hauptbereich: zwei Listen nebeneinander
        splitter = QSplitter(Qt.Horizontal)

        # Linke Liste: dieser Linie zugewiesen
        left_box = QGroupBox(
            f"Dieser Linie zugewiesen  (Linie {current_line.line_number})"
        )
        left_layout = QVBoxLayout(left_box)
        self._list_assigned = QListWidget()
        self._list_assigned.setSelectionMode(QListWidget.ExtendedSelection)
        left_layout.addWidget(self._list_assigned)
        btn_remove = QPushButton("← Entfernen")
        btn_remove.clicked.connect(self._remove_from_line)
        left_layout.addWidget(btn_remove)
        splitter.addWidget(left_box)

        # Rechte Liste: verfügbare Räume
        right_box = QGroupBox("Verfügbare Räume (andere / nicht zugewiesen)")
        right_layout = QVBoxLayout(right_box)
        self._list_available = QListWidget()
        self._list_available.setSelectionMode(QListWidget.ExtendedSelection)
        right_layout.addWidget(self._list_available)
        btn_add = QPushButton("→ Dieser Linie zuweisen")
        btn_add.clicked.connect(self._add_to_line)
        right_layout.addWidget(btn_add)
        splitter.addWidget(right_box)

        splitter.setSizes([340, 340])
        layout.addWidget(splitter)

        # Geräteanzahl-Info
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #606060;")
        layout.addWidget(self._info_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("Übernehmen")
        btn_ok.clicked.connect(self._apply)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        self._refresh_lists()

    # ------------------------------------------------------------------
    # Initialisierung
    # ------------------------------------------------------------------

    def _build_assignments(self):
        """Baut ein Dict room_id -> Line aus der aktuellen Topologie."""
        for area in self._topology.areas:
            for line in area.lines:
                for rid in line.assigned_room_ids:
                    self._assignments[rid] = line

    def _populate_floors(self):
        """Füllt die Etagen-Combobox."""
        self._floor_combo.clear()
        for floor in self._areal.all_floors:
            rooms = floor.all_rooms
            if rooms:
                self._floor_combo.addItem(
                    f"{floor.name}  ({len(rooms)} Räume)",
                    userData=floor,
                )

    # ------------------------------------------------------------------
    # Listen aktualisieren
    # ------------------------------------------------------------------

    def _refresh_lists(self):
        self._list_assigned.clear()
        self._list_available.clear()

        all_rooms = {r.id: r for r in self._areal.all_rooms}
        assigned_devices = 0

        for rid, room in all_rooms.items():
            assigned_line = self._assignments.get(rid)
            item = QListWidgetItem(self._room_label(room, assigned_line))
            item.setData(Qt.UserRole, rid)

            if assigned_line is self._line:
                self._list_assigned.addItem(item)
                assigned_devices += room.total_devices()
            else:
                self._list_available.addItem(item)

        self._info_label.setText(
            f"Dieser Linie zugewiesen: {self._list_assigned.count()} Räume, "
            f"{assigned_devices} Geräte"
        )

    @staticmethod
    def _room_label(room: Room, line: Line | None) -> str:
        line_info = f"  [Linie {line.line_number}: {line.name}]" if line else ""
        return f"{room.number}  {room.name}  ({room.total_devices()} Geräte){line_info}"

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _assign_floor(self):
        """Weist alle Räume der gewählten Etage dieser Linie zu."""
        floor: Floor = self._floor_combo.currentData()
        if not floor:
            return
        for room in floor.all_rooms:
            self._assignments[room.id] = self._line
        self._refresh_lists()

    def _add_to_line(self):
        """Verschiebt ausgewählte Räume aus der rechten in die linke Liste."""
        for item in self._list_available.selectedItems():
            rid = item.data(Qt.UserRole)
            self._assignments[rid] = self._line
        self._refresh_lists()

    def _remove_from_line(self):
        """Entfernt ausgewählte Räume aus dieser Linie (keine Zuweisung)."""
        for item in self._list_assigned.selectedItems():
            rid = item.data(Qt.UserRole)
            self._assignments.pop(rid, None)
        self._refresh_lists()

    # ------------------------------------------------------------------
    # Übernehmen
    # ------------------------------------------------------------------

    def _apply(self):
        """Schreibt die neuen Zuordnungen in das Topologie-Modell zurück."""
        # Alle assigned_room_ids leeren
        for area in self._topology.areas:
            for line in area.lines:
                line.assigned_room_ids = []

        # Neu befüllen
        for rid, line in self._assignments.items():
            if rid not in line.assigned_room_ids:
                line.assigned_room_ids.append(rid)

        # Gerätezahlen neu berechnen
        rooms_by_id = {r.id: r for r in self._areal.all_rooms}
        for area in self._topology.areas:
            for line in area.lines:
                line.device_count = sum(
                    rooms_by_id[rid].total_devices()
                    for rid in line.assigned_room_ids
                    if rid in rooms_by_id
                )

        self.accept()
