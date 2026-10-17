"""
GA in Szenen aufnehmen (FA-1816): je Szene ankreuzen und den Wert wählen,
den das Element beim Aufruf annimmt. Aufruf aus der GA-Baumansicht.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QComboBox, QCheckBox, QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import Qt
from ..styles import KNX_PRIMARY
from ...services.scene_membership import scene_slots, value_choices

_COL_IN, _COL_ADDRESS, _COL_NR, _COL_SCENE, _COL_VALUE = range(5)


class GaSceneDialog(QDialog):
    """Szenen ankreuzen, in denen die GA mitschaltet, mit Wert je Szene."""

    def __init__(self, project, ga, parent=None):
        super().__init__(parent)
        self._project = project
        self._ga = ga
        self._slots = scene_slots(project, ga)
        self._choices = value_choices(ga)
        self.setWindowTitle(f"GA {ga.address} in Szenen")
        self.setMinimumSize(680, 420)

        layout = QVBoxLayout(self)
        info = QLabel(
            f"<b>{ga.address}</b> {ga.designation}<br>"
            "Szenen ankreuzen, in denen das Element mitschaltet, und den Wert wählen. "
            "Angezeigt sind die Szenen, deren Szenen-GA den Raum der GA erreicht.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._show_all = QCheckBox("Alle Szenen zeigen (auch anderer Räume und Zonen)")
        self._show_all.toggled.connect(self._apply_filter)
        layout.addWidget(self._show_all)

        self._table = QTableWidget(len(self._slots), 5)
        self._table.setHorizontalHeaderLabels(["", "Szenen-GA", "Nr.", "Szene", "Wert"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_SCENE, QHeaderView.Stretch)
        self._boxes: list[QCheckBox] = []
        self._values: list[QComboBox] = []
        for row, slot in enumerate(self._slots):
            box = QCheckBox()
            box.setChecked(slot.value is not None)
            self._table.setCellWidget(row, _COL_IN, box)
            self._boxes.append(box)
            address = slot.address or "neu (Schritt 10)"
            self._table.setItem(row, _COL_ADDRESS, QTableWidgetItem(
                f"{address}  {slot.address_label}".strip()))
            self._table.setItem(row, _COL_NR, QTableWidgetItem(
                str(slot.scene.scene_number or "")))
            self._table.setItem(row, _COL_SCENE, QTableWidgetItem(slot.scene.name))
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(self._choices)
            combo.setEditText(slot.value if slot.value is not None
                              else (self._choices[0] if self._choices else ""))
            combo.setEnabled(box.isChecked())
            box.toggled.connect(combo.setEnabled)
            self._table.setCellWidget(row, _COL_VALUE, combo)
            self._values.append(combo)
        self._table.resizeColumnsToContents()
        self._table.setColumnWidth(_COL_VALUE, max(self._table.columnWidth(_COL_VALUE), 110))
        layout.addWidget(self._table)

        self._empty = QLabel("Keine Szene erreicht diesen Raum. Szenen legen Sie in der "
                             "Ansicht «Szenen» an.")
        self._empty.setStyleSheet("color: #666666; font-style: italic;")
        layout.addWidget(self._empty)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Übernehmen")
        save.setStyleSheet(f"background-color: {KNX_PRIMARY}; color: white; "
                           f"font-weight: bold; padding: 6px 20px;")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        self._apply_filter()

    def _apply_filter(self) -> None:
        show_all = self._show_all.isChecked()
        visible = 0
        for row, slot in enumerate(self._slots):
            # Szenen, in denen die GA schon steht, bleiben immer sichtbar
            hidden = not (show_all or slot.reaches or slot.value is not None)
            self._table.setRowHidden(row, hidden)
            visible += not hidden
        self._empty.setVisible(visible == 0)

    def values(self) -> dict:
        """Scene.id -> Wert oder None (nicht in der Szene)."""
        result = {}
        for slot, box, combo in zip(self._slots, self._boxes, self._values):
            result[slot.scene.id] = combo.currentText().strip() if box.isChecked() else None
        return result

    def _save(self) -> None:
        # Übernehmen macht der Aufrufer nach seinem Rückgängig-Punkt
        # (services.scene_membership.set_scene_values mit values())
        self.accept()
