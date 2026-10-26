"""
Projektuebersicht / Dashboard (FA-010)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QFrame, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from ..styles import (
    COLOR_OK, COLOR_WARNING, KNX_GREEN, KNX_BLUE, KNX_DARK_GREEN, TEXT_MUTED,
)
from ..dialogs.project_properties_dialog import ProjectPropertiesDialog, knx_secure_summary


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
        self._title.setStyleSheet("font-size: 12px; color: #666666;")
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
    # Arbeitsablauf: Seitenleisten-Schlüssel des gewählten Schritts
    navigate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Titel
        title = QLabel("Projektübersicht")
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

        # Arbeitsablauf: Schritte mit Stand, nächster Schritt hervorgehoben
        self._workflow_group = QGroupBox("Arbeitsablauf")
        self._workflow_layout = QGridLayout()
        self._workflow_layout.setColumnStretch(1, 3)
        self._workflow_layout.setColumnStretch(2, 2)
        self._workflow_layout.setHorizontalSpacing(14)
        self._workflow_layout.setVerticalSpacing(6)
        self._workflow_group.setLayout(self._workflow_layout)
        self._workflow_group.setVisible(False)
        layout.addWidget(self._workflow_group)
        self._problem_counts: tuple[int, int] | None = None

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
            ("secure",   "KNX Secure:",     5),
            ("created",  "Erstellt:",       6),
            ("modified", "Geändert:",       7),
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
        self._info_labels["secure"].setText(knx_secure_summary(project.knx_secure))
        self._info_labels["created"].setText(project.created or "-")
        self._info_labels["modified"].setText(project.modified or "-")
        self._show_workflow()

    def set_problem_counts(self, counts: tuple[int, int] | None) -> None:
        """(Fehler, Warnungen) der Sofortprüfung (ProblemMonitor), None ohne
        Prüfung -- für die Karte und den Schritt «Validierung»."""
        self._problem_counts = counts
        self._card_issues.set_value("–" if counts is None else str(sum(counts)))
        if self._project is not None:
            self._show_workflow()

    # «offen» grau: spätere Schritte sind noch nicht fällig, kein Fehler
    _STATE_COLORS = {"erledigt": COLOR_OK, "begonnen": COLOR_WARNING, "offen": TEXT_MUTED}

    def _show_workflow(self) -> None:
        """Arbeitsablauf neu aufbauen (nur geplante Projekte; importierte
        Projekte dokumentieren den ETS-Stand)."""
        from ...services.workflow_status import next_step, workflow_steps
        layout = self._workflow_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # sofort lösen: deleteLater allein liess die alten Zeilen sichtbar
                widget.setParent(None)
                widget.deleteLater()
        project = self._project
        if project is None or project.topology.is_imported:
            self._workflow_group.setVisible(False)
            return
        errors, warnings = self._problem_counts or (None, None)
        steps = workflow_steps(project, errors, warnings)
        upcoming = next_step(steps)
        for row, step in enumerate(steps):
            is_next = step is upcoming
            number = QLabel(f"{step.number}")
            number.setStyleSheet(f"font-weight: bold; color: {COLOR_OK if is_next else TEXT_MUTED};")
            layout.addWidget(number, row, 0, Qt.AlignTop)
            text = QLabel(f"<b>{step.title}</b>"
                          + ("  ← nächster Schritt" if is_next else "")
                          + f"<br><span style='color:{TEXT_MUTED};'>{step.description}</span>")
            text.setWordWrap(True)
            layout.addWidget(text, row, 1)
            state = QLabel(" · ".join(p for p in (step.label, step.detail) if p))
            state.setWordWrap(True)
            color = self._STATE_COLORS.get(step.state, TEXT_MUTED)
            state.setStyleSheet(f"color: {color};" + (" font-weight: bold;" if is_next else ""))
            layout.addWidget(state, row, 2, Qt.AlignTop)
            button = QPushButton("Öffnen")
            button.setObjectName("" if is_next else "secondary")
            button.clicked.connect(lambda _c=False, key=step.nav_key: self.navigate_requested.emit(key))
            layout.addWidget(button, row, 3, Qt.AlignTop)
        self._workflow_group.setVisible(True)

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
            self._info_labels["secure"].setText(knx_secure_summary(self._project.knx_secure))
            if self._project.name != old_name:
                self.project_name_changed.emit(self._project.name)
            if dialog.open_secure_archive:
                self.navigate_requested.emit("knx_secure")
