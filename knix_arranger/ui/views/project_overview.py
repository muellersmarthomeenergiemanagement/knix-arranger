"""
Projektuebersicht / Dashboard (FA-010)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QFrame, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from ..styles import KNX_GREEN, KNX_BLUE, KNX_DARK_GREEN
from ..dialogs.project_properties_dialog import ProjectPropertiesDialog


class StatCard(QFrame):
    """Statistik-Karte für das Dashboard."""

    def __init__(self, title: str, value: str = "0", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: white; border: 1px solid #C0C0C0; "
            "border-radius: 6px; padding: 10px; }"
        )

        layout = QVBoxLayout(self)
        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 11px; color: #808080;")
        layout.addWidget(self._title)

        self._value = QLabel(value)
        self._value.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {KNX_DARK_GREEN};"
        )
        layout.addWidget(self._value)

    def set_value(self, value: str):
        self._value.setText(value)


class ProjectOverview(QWidget):
    """Dashboard mit Projektuebersicht."""

    project_name_changed = Signal(str)  # emitted when name is changed by user

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Titel
        title = QLabel("Projektuebersicht")
        title.setObjectName("title")
        layout.addWidget(title)

        # Statistik-Karten
        stats_layout = QHBoxLayout()
        self._card_floors = StatCard("Stockwerke")
        self._card_rooms = StatCard("Räume")
        self._card_gewerke = StatCard("Gewerke")
        self._card_gas = StatCard("Gruppenadressen")
        self._card_lines = StatCard("Linien")
        self._card_issues = StatCard("Validierungsprobleme")

        stats_layout.addWidget(self._card_floors)
        stats_layout.addWidget(self._card_rooms)
        stats_layout.addWidget(self._card_gewerke)
        stats_layout.addWidget(self._card_gas)
        stats_layout.addWidget(self._card_lines)
        stats_layout.addWidget(self._card_issues)

        layout.addLayout(stats_layout)

        # Projektinfo
        info_group = QGroupBox("Projektinformationen")
        info_layout = QGridLayout()
        self._info_labels = {}

        # Projektname row: label + value + Eigenschaften button
        name_lbl = QLabel("Projektname:")
        name_lbl.setStyleSheet("font-weight: bold;")
        self._name_val = QLabel("-")
        self._info_labels["name"] = self._name_val
        self._btn_properties = QPushButton("Eigenschaften bearbeiten...")
        self._btn_properties.setEnabled(False)
        self._btn_properties.clicked.connect(self._edit_properties)
        name_row = QHBoxLayout()
        name_row.addWidget(self._name_val)
        name_row.addWidget(self._btn_properties)
        name_row.addStretch()
        info_layout.addWidget(name_lbl, 0, 0)
        info_layout.addLayout(name_row, 0, 1)

        for key, label_text, row in [
            ("number",   "Projektnummer:",  1),
            ("variant",  "MG-Variante:",    2),
            ("topo",     "Topologie-Modus:", 3),
            ("backbone", "Backbone-Typ:",   4),
            ("created",  "Erstellt:",       5),
            ("modified", "Geändert:",       6),
        ]:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-weight: bold;")
            val = QLabel("-")
            self._info_labels[key] = val
            info_layout.addWidget(lbl, row, 0)
            info_layout.addWidget(val, row, 1)

        info_layout.setColumnStretch(1, 1)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()

    def update_from_project(self, project):
        """Aktualisiert das Dashboard mit Projektdaten."""
        if not project:
            return

        self._project = project
        self._btn_properties.setEnabled(True)

        self._card_floors.set_value(str(len(project.all_floors)))
        self._card_rooms.set_value(str(len(project.all_rooms)))

        gewerk_count = sum(
            len(r.gewerk_assignments) for r in project.all_rooms
        )
        self._card_gewerke.set_value(str(gewerk_count))

        ga_count = len(project.group_addresses.all_addresses())
        self._card_gas.set_value(str(ga_count))

        line_count = sum(
            len(a.lines) for a in project.topology.areas
        )
        self._card_lines.set_value(str(line_count))

        self._info_labels["name"].setText(project.name or "-")
        self._info_labels["number"].setText(project.project_number or "-")
        self._info_labels["variant"].setText(project.config.mg_variant)
        self._info_labels["topo"].setText(project.config.topology_mode)
        self._info_labels["backbone"].setText(project.config.backbone_type)
        self._info_labels["created"].setText(project.created or "-")
        self._info_labels["modified"].setText(project.modified or "-")

    def _edit_properties(self):
        """Öffnet den Projekteigenschaften-Dialog."""
        if not self._project:
            return
        old_name = self._project.name
        dialog = ProjectPropertiesDialog(self._project, self)
        if dialog.exec():
            # Angezeigte Werte aktualisieren
            self._info_labels["name"].setText(self._project.name or "-")
            self._info_labels["number"].setText(self._project.project_number or "-")
            self._info_labels["variant"].setText(self._project.config.mg_variant)
            self._info_labels["topo"].setText(self._project.config.topology_mode)
            self._info_labels["backbone"].setText(self._project.config.backbone_type)
            if self._project.name != old_name:
                self.project_name_changed.emit(self._project.name)
