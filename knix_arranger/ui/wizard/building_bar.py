"""
Gebäudeauswahl für Wizard-Schritte 1–3.

Die Schritte Stockwerke, Zonen und Räume bearbeiten jeweils ein Gebäude
(dessen ersten Flügel). Die Auswahl ist schrittübergreifend: wer in
Schritt 1 das Nebengebäude wählt, erfasst in Schritt 2 und 3 dessen Zonen
und Räume. Jedes Gebäude wird in der Topologie ein eigener Bereich.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QComboBox, QPushButton, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Signal
from ...models.building import Building, Wing
from ...models.project import KnxProject


class BuildingSelection:
    """Gemeinsamer Zustand: welches Gebäude die Schritte 1–3 bearbeiten."""

    def __init__(self, project: KnxProject):
        self._project = project
        self.building_id: str = ""

    def building(self) -> Building:
        """Gewähltes Gebäude; legt bei leerem Projekt eines an."""
        buildings = self._project.areal.buildings
        if not buildings:
            buildings.append(Building(name=self._project.name or "Gebäude"))
        found = next((b for b in buildings if b.id == self.building_id), None)
        if found is None:
            found = buildings[0]
            self.building_id = found.id
        return found

    def wing(self) -> Wing:
        """Erster Flügel des gewählten Gebäudes (wird bei Bedarf angelegt)."""
        building = self.building()
        if not building.wings:
            building.wings.append(Wing(name="Hauptgebäude"))
        return building.wings[0]


class BuildingBar(QWidget):
    """Auswahlleiste "Gebäude: [▾]", in Schritt 1 mit Anlegen/Umbenennen/Entfernen."""

    changed = Signal()

    def __init__(self, project: KnxProject, selection: BuildingSelection,
                 editable: bool = False, parent=None):
        super().__init__(parent)
        self._project = project
        self._selection = selection

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Gebäude:"))
        self._combo = QComboBox()
        self._combo.setMinimumWidth(240)
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self._combo)

        if editable:
            btn_add = QPushButton("+ Gebäude")
            btn_add.setToolTip(
                "Frei stehendes Nebengebäude anlegen (z.B. Einstellhalle).\n"
                "Es erhält eigene Stockwerke mit eigenen Hauptgruppen und\n"
                "in der Topologie einen eigenen Bereich."
            )
            btn_add.clicked.connect(self._add_building)
            btn_rename = QPushButton("Umbenennen")
            btn_rename.setObjectName("secondary")
            btn_rename.clicked.connect(self._rename_building)
            self._btn_remove = QPushButton("Gebäude entfernen")
            self._btn_remove.setObjectName("danger")
            self._btn_remove.clicked.connect(self._remove_building)
            for btn in (btn_add, btn_rename, self._btn_remove):
                layout.addWidget(btn)
        else:
            self._btn_remove = None
        layout.addStretch()

    def refresh(self) -> None:
        """Liste neu aufbauen und die gemeinsame Auswahl anzeigen."""
        current = self._selection.building()
        self._combo.blockSignals(True)
        self._combo.clear()
        for building in self._project.areal.buildings:
            self._combo.addItem(building.name or "Gebäude", building.id)
        self._combo.setCurrentIndex(max(0, self._combo.findData(current.id)))
        self._combo.blockSignals(False)
        if self._btn_remove is not None:
            self._btn_remove.setEnabled(len(self._project.areal.buildings) > 1)
        # Bei nur einem Gebäude bleibt die Auswahl sichtbar, aber ohne Wirkung
        self._combo.setEnabled(len(self._project.areal.buildings) > 1)

    def _on_index_changed(self, index: int) -> None:
        building_id = self._combo.itemData(index)
        if building_id and building_id != self._selection.building_id:
            self._selection.building_id = building_id
            self.changed.emit()

    def _select(self, building: Building) -> None:
        self._selection.building_id = building.id
        self.refresh()
        self.changed.emit()

    def _add_building(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Gebäude hinzufügen", "Name des Nebengebäudes (z.B. Einstellhalle):",
        )
        if not (ok and name.strip()):
            return
        building = Building(name=name.strip(), wings=[Wing(name="Hauptgebäude")])
        self._project.areal.buildings.append(building)
        self._select(building)

    def _rename_building(self) -> None:
        building = self._selection.building()
        name, ok = QInputDialog.getText(
            self, "Gebäude umbenennen", "Name:", text=building.name,
        )
        if ok and name.strip():
            building.name = name.strip()
            self._select(building)

    def _remove_building(self) -> None:
        buildings = self._project.areal.buildings
        if len(buildings) <= 1:
            return
        building = self._selection.building()
        n_rooms = len(building.all_rooms)
        msg = f"Gebäude '{building.name}' mit allen Stockwerken und Zonen entfernen?"
        if n_rooms:
            msg += f"\n\nAchtung: {n_rooms} Raum/Räume gehen verloren!"
        reply = QMessageBox.question(
            self, "Gebäude entfernen", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        buildings.remove(building)
        self._select(buildings[0])
