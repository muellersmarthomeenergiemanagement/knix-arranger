"""
Wizard Schritt 2: Zonen (Wohnungen) definieren

Eine Zone ist eine logische Nutzungseinheit (Wohnung, EFH, Gemeinschaft …)
und wird unabhängig von Stockwerken definiert.  Sie kann über mehrere
Stockwerke gehen (Maisonette, EFH).  Jede Zone entspricht einer KNX-Linie.

Im Datenmodell bleibt floor.apartments erhalten:  Eine Zone mit mehreren
Stockwerken erzeugt für jedes Stockwerk ein Apartment-Objekt mit gleichem
Namen, die TopologyEngine fasst sie über den Namen zur Linie zusammen.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QLineEdit, QFormLayout,
    QGroupBox, QCheckBox, QScrollArea, QMessageBox,
)
from PySide6.QtCore import Qt, QEvent
from ...models.project import KnxProject
from ...models.building import Apartment, Wing


class Step02Apartments(QWidget):
    """Zonen (Wohnungen) gebäudeweit definieren."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._current_zone_name: str = ""  # Name der gerade selektierten Zone

        layout = QVBoxLayout(self)
        info = QLabel(
            "Definieren Sie die Zonen (Wohnungen) des Gebäudes.\n"
            "Eine Zone ist unabhängig von Stockwerken und wird einer KNX-Linie zugewiesen.\n"
            "EFH: Schaltfläche '1 Zone (EFH)' erstellt eine einzige Zone für alle Stockwerke.\n"
            "MFH/Maisonette: Weisen Sie jeder Zone die betreffenden Stockwerke zu."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        content = QHBoxLayout()

        # ── Linke Seite: Zonenliste ────────────────────────────────────────
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Zonen:"))
        self._zone_list = QListWidget()
        self._zone_list.currentItemChanged.connect(self._on_zone_selected)
        self._zone_list.installEventFilter(self)
        left_layout.addWidget(self._zone_list)

        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("+ Zone")
        self._btn_add.setToolTip(
            "Neue Zone (Wohnung) erstellen.\n"
            "Eine Zone = eine KNX-Linie in der Topologie.\n"
            "EFH: 1 Zone für alle Stockwerke reicht.\n"
            "MFH: Eine Zone pro Wohnung anlegen."
        )
        self._btn_add.clicked.connect(self._add_zone)
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("danger")
        self._btn_remove.setToolTip("Zone entfernen (Entf)")
        self._btn_remove.clicked.connect(self._remove_zone)
        self._btn_efh = QPushButton("1 Zone (EFH)")
        self._btn_efh.setToolTip(
            "Erstellt eine einzige Zone für das gesamte Gebäude.\n"
            "Alle Räume aller Stockwerke gehören zur selben Zone und KNX-Linie."
        )
        self._btn_efh.clicked.connect(self._auto_zone_efh)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_remove)
        btn_layout.addWidget(self._btn_efh)
        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)
        content.addLayout(left_layout, 2)

        # ── Rechte Seite: Details ──────────────────────────────────────────
        detail = QGroupBox("Zonen-Details")
        detail_layout = QVBoxLayout()

        form = QFormLayout()
        self._zone_name_edit = QLineEdit()
        self._zone_name_edit.setPlaceholderText("z.B. Wohnung 1")
        form.addRow("Name:", self._zone_name_edit)
        detail_layout.addLayout(form)

        detail_layout.addWidget(QLabel("Stockwerke dieser Zone:"))

        # Scrollbereich für Stockwerk-Checkboxen
        floor_scroll = QScrollArea()
        floor_scroll.setWidgetResizable(True)
        floor_scroll.setMinimumHeight(100)
        floor_scroll.setMaximumHeight(200)
        self._floor_check_container = QWidget()
        self._floor_check_layout = QVBoxLayout(self._floor_check_container)
        self._floor_check_layout.setContentsMargins(4, 4, 4, 4)
        self._floor_check_layout.addStretch()
        floor_scroll.setWidget(self._floor_check_container)
        detail_layout.addWidget(floor_scroll)

        self._room_count_label = QLabel("")
        self._room_count_label.setStyleSheet("color: #666; font-style: italic;")
        detail_layout.addWidget(self._room_count_label)

        self._btn_apply = QPushButton("Übernehmen")
        self._btn_apply.setToolTip("Zonennamen übernehmen")
        self._btn_apply.clicked.connect(self._apply_changes)
        self._zone_name_edit.returnPressed.connect(self._apply_changes)
        detail_layout.addWidget(self._btn_apply)

        detail.setLayout(detail_layout)
        content.addWidget(detail, 1)
        layout.addLayout(content)

        # Interne Zustandsliste der Checkboxen: [(QCheckBox, Floor)]
        self._checkboxes: list[tuple[QCheckBox, object]] = []

    def eventFilter(self, obj, event):
        if obj is self._zone_list and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Delete:
                self._remove_zone()
                return True
            if key == Qt.Key.Key_F2:
                self._zone_name_edit.setFocus()
                self._zone_name_edit.selectAll()
                return True
        return super().eventFilter(obj, event)

    # ── Hilfsmethoden ──────────────────────────────────────────────────────

    def _get_wing(self) -> Wing | None:
        b = self._project.areal.buildings
        if not b or not b[0].wings:
            return None
        return b[0].wings[0]

    def _all_zone_names(self) -> list[str]:
        """Sortierte Liste eindeutiger Zonennamen über alle Stockwerke."""
        wing = self._get_wing()
        if not wing:
            return []
        return sorted({apt.name for floor in wing.floors for apt in floor.apartments})

    def _room_count_for_zone(self, zone_name: str) -> int:
        """Raumanzahl für eine einzelne Zone (für Einzelabfragen)."""
        wing = self._get_wing()
        if not wing:
            return 0
        return sum(
            len(apt.rooms)
            for floor in wing.floors
            for apt in floor.apartments
            if apt.name == zone_name
        )

    def _all_room_counts(self) -> dict[str, int]:
        """Raumanzahlen für alle Zonen in einem einzigen Pass — O(F×A)."""
        wing = self._get_wing()
        if not wing:
            return {}
        counts: dict[str, int] = {}
        for floor in wing.floors:
            for apt in floor.apartments:
                counts[apt.name] = counts.get(apt.name, 0) + len(apt.rooms)
        return counts

    # ── Refresh ────────────────────────────────────────────────────────────

    def on_enter(self):
        self._refresh()

    def _refresh(self):
        current_name = (
            self._zone_list.currentItem().data(Qt.UserRole)
            if self._zone_list.currentItem() else None
        )
        # Einmal alle Raumzahlen berechnen statt pro Zone einzeln (O(F×A) statt O(Z×F×A))
        room_counts = self._all_room_counts()
        self._zone_list.blockSignals(True)
        self._zone_list.clear()
        for name in self._all_zone_names():
            rooms = room_counts.get(name, 0)
            item = QListWidgetItem(f"{name}  ({rooms} Räume)")
            item.setData(Qt.UserRole, name)
            self._zone_list.addItem(item)
            if name == current_name:
                self._zone_list.setCurrentItem(item)
        if not self._zone_list.currentItem() and self._zone_list.count():
            self._zone_list.setCurrentRow(0)
        self._zone_list.blockSignals(False)
        self._on_zone_selected(self._zone_list.currentItem(), None)

    # ── Selektion ──────────────────────────────────────────────────────────

    def _on_zone_selected(self, current, _previous):
        if not current:
            self._zone_name_edit.clear()
            self._room_count_label.clear()
            self._rebuild_floor_checkboxes("")
            return

        zone_name = current.data(Qt.UserRole) or current.text().split("  (")[0]
        self._current_zone_name = zone_name
        self._zone_name_edit.setText(zone_name)
        self._rebuild_floor_checkboxes(zone_name)
        n = self._room_count_for_zone(zone_name)
        self._room_count_label.setText(f"{n} Räume in dieser Zone")

    def _rebuild_floor_checkboxes(self, zone_name: str):
        """Baut Stockwerk-Checkboxen für die aktuelle Zone neu auf."""
        # Alten Inhalt entfernen (ausser dem abschliessenden Stretch)
        while self._floor_check_layout.count() > 1:
            item = self._floor_check_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

        wing = self._get_wing()
        if not wing or not zone_name:
            return

        for floor in wing.floors:
            has_zone = any(apt.name == zone_name for apt in floor.apartments)
            label = f"{floor.short_code} – {floor.name}" if floor.name else floor.short_code
            cb = QCheckBox(label)
            cb.setChecked(has_zone)
            cb.stateChanged.connect(
                lambda state, f=floor, z=zone_name: self._on_floor_toggled(f, z, bool(state))
            )
            self._floor_check_layout.insertWidget(
                self._floor_check_layout.count() - 1, cb
            )
            self._checkboxes.append((cb, floor))

    def _on_floor_toggled(self, floor, zone_name: str, checked: bool):
        """Fügt Zone einem Stockwerk hinzu oder entfernt sie."""
        if checked:
            if not any(apt.name == zone_name for apt in floor.apartments):
                floor.apartments.append(Apartment(name=zone_name))
        else:
            apt = next((a for a in floor.apartments if a.name == zone_name), None)
            if apt and apt.rooms:
                reply = QMessageBox.question(
                    self,
                    "Zone vom Stockwerk entfernen?",
                    f"Die Zone '{zone_name}' hat auf {floor.short_code} "
                    f"{len(apt.rooms)} Raum/Räume.\n"
                    "Diese Räume gehen verloren. Fortfahren?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    # Checkbox wieder ankreuzen
                    for cb, f in self._checkboxes:
                        if f is floor:
                            cb.blockSignals(True)
                            cb.setChecked(True)
                            cb.blockSignals(False)
                    return
            floor.apartments = [a for a in floor.apartments if a.name != zone_name]

        n = self._room_count_for_zone(zone_name)
        self._room_count_label.setText(f"{n} Räume in dieser Zone")
        self._refresh()

    # ── Aktionen ───────────────────────────────────────────────────────────

    def _add_zone(self):
        """Neue Zone anlegen (initial auf erstem Stockwerk)."""
        wing = self._get_wing()
        if not wing or not wing.floors:
            QMessageBox.information(
                self, "Keine Stockwerke",
                "Bitte zuerst in Schritt 1 Stockwerke anlegen.",
            )
            return

        existing = self._all_zone_names()
        idx = len(existing) + 1
        zone_name = f"Zone {idx}"
        while zone_name in existing:
            idx += 1
            zone_name = f"Zone {idx}"

        # Initial auf dem ersten Stockwerk anlegen
        wing.floors[0].apartments.append(Apartment(name=zone_name))

        self._refresh()
        # Neue Zone selektieren
        for i in range(self._zone_list.count()):
            item = self._zone_list.item(i)
            if item.data(Qt.UserRole) == zone_name:
                self._zone_list.setCurrentItem(item)
                break

    def _remove_zone(self):
        """Zone komplett entfernen (aus allen Stockwerken)."""
        item = self._zone_list.currentItem()
        if not item:
            return
        zone_name = item.data(Qt.UserRole) or item.text().split("  (")[0]
        wing = self._get_wing()
        if not wing:
            return

        total_rooms = self._room_count_for_zone(zone_name)
        msg = f"Zone '{zone_name}' aus allen Stockwerken entfernen?"
        if total_rooms > 0:
            msg += f"\n\nAchtung: {total_rooms} Raum/Räume gehen verloren!"

        reply = QMessageBox.question(self, "Zone entfernen", msg,
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        for floor in wing.floors:
            floor.apartments = [a for a in floor.apartments if a.name != zone_name]

        self._current_zone_name = ""
        self._refresh()

    def _auto_zone_efh(self):
        """Eine einzige Zone für das gesamte Gebäude (EFH-Modus)."""
        wing = self._get_wing()
        if not wing or not wing.floors:
            return

        zone_name = self._project.name or "Gebäude"

        reply = QMessageBox.question(
            self,
            "1 Zone (EFH)",
            f"Alle Stockwerke werden der Zone '{zone_name}' zugewiesen.\n"
            "Vorhandene Zonen und ihre Räume werden zusammengeführt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for floor in wing.floors:
            # Alle Räume aus allen Apartments zusammenführen
            all_rooms = [r for apt in floor.apartments for r in apt.rooms]
            new_apt = Apartment(name=zone_name)
            new_apt.rooms = all_rooms
            floor.apartments = [new_apt]

        self._current_zone_name = zone_name
        self._refresh()
        for i in range(self._zone_list.count()):
            item = self._zone_list.item(i)
            if item.data(Qt.UserRole) == zone_name:
                self._zone_list.setCurrentItem(item)
                break

    def _apply_changes(self):
        """Zonennamen übernehmen (umbenennen in allen Stockwerken)."""
        item = self._zone_list.currentItem()
        if not item:
            return

        old_name = self._current_zone_name
        new_name = self._zone_name_edit.text().strip()
        if not new_name or new_name == old_name:
            return

        wing = self._get_wing()
        if not wing:
            return

        # Alle Apartments mit altem Namen umbenennen
        for floor in wing.floors:
            for apt in floor.apartments:
                if apt.name == old_name:
                    apt.name = new_name

        self._current_zone_name = new_name
        self._refresh()
        for i in range(self._zone_list.count()):
            item = self._zone_list.item(i)
            if item.data(Qt.UserRole) == new_name:
                self._zone_list.setCurrentItem(item)
                break
