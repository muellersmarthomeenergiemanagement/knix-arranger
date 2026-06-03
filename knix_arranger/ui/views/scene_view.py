"""
Szenen-Verwaltung (FA-1801 bis FA-1807)
"""
from __future__ import annotations
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QSpinBox,
    QLineEdit, QGroupBox, QFormLayout, QAbstractItemView,
    QMessageBox, QDoubleSpinBox,
)
from PySide6.QtCore import Qt
from ...models.project import KnxProject
from ...models.scene import Scene, SceneAction
from ..column_utils import fit_columns


class SceneView(QWidget):
    """Szenen-Verwaltung: Erstellen, Bearbeiten, Vorlagen anwenden."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        self._templates: list[dict] = []
        self._load_templates()

        layout = QVBoxLayout(self)

        # Titel
        title = QLabel("Szenen-Verwaltung")
        title.setObjectName("title")
        layout.addWidget(title)

        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        # Hauptbereich: Szenen-Tabelle links, Details rechts
        content = QHBoxLayout()

        # --- Linke Seite: Szenen-Tabelle + Buttons ---
        left = QVBoxLayout()

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Name", "Nr.", "Geltungsbereich", "Auslöser", "Aktionen",
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.currentCellChanged.connect(self._on_selection)
        left.addWidget(self._table)

        # Buttons
        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("+ Neue Szene")
        self._btn_add.clicked.connect(self._add_scene)
        self._btn_from_template = QPushButton("Aus Vorlage")
        self._btn_from_template.clicked.connect(self._add_from_template)
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("danger")
        self._btn_remove.clicked.connect(self._remove_scene)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_from_template)
        btn_layout.addWidget(self._btn_remove)
        btn_layout.addStretch()
        left.addLayout(btn_layout)

        # Vorlagen-Auswahl
        template_layout = QHBoxLayout()
        template_layout.addWidget(QLabel("Vorlage:"))
        self._template_combo = QComboBox()
        self._template_combo.addItem("-- Vorlage wählen --", -1)
        for i, t in enumerate(self._templates):
            self._template_combo.addItem(
                f"{t['name']} - {t['description']}", i
            )
        template_layout.addWidget(self._template_combo)
        template_layout.addStretch()
        left.addLayout(template_layout)

        content.addLayout(left, 2)

        # --- Rechte Seite: Detail-Panel ---
        right = QVBoxLayout()

        # Szenen-Details
        self._detail_group = QGroupBox("Szenen-Details")
        detail_form = QFormLayout()

        self._scene_name = QLineEdit()
        detail_form.addRow("Name:", self._scene_name)

        self._scene_number = QSpinBox()
        self._scene_number.setRange(1, 64)
        detail_form.addRow("Szenen-Nr. (1-64):", self._scene_number)

        self._scene_scope = QComboBox()
        self._scene_scope.addItems(["room", "apartment", "zone", "central"])
        detail_form.addRow("Geltungsbereich:", self._scene_scope)

        self._scene_scope_id = QComboBox()
        detail_form.addRow("Raum/Zone:", self._scene_scope_id)

        self._scene_trigger = QLineEdit()
        self._scene_trigger.setPlaceholderText(
            "z.B. Taster Eingang, Taste 4 lang"
        )
        detail_form.addRow("Auslöser:", self._scene_trigger)

        self._btn_apply = QPushButton("Übernehmen")
        self._btn_apply.clicked.connect(self._apply_changes)
        detail_form.addRow("", self._btn_apply)

        self._detail_group.setLayout(detail_form)
        right.addWidget(self._detail_group)

        # Aktionen-Tabelle
        self._actions_group = QGroupBox("Szenen-Aktionen")
        actions_layout = QVBoxLayout()

        self._actions_table = QTableWidget()
        self._actions_table.setColumnCount(3)
        self._actions_table.setHorizontalHeaderLabels([
            "Gruppenadresse / Gewerk", "Wert", "Verzögerung (s)",
        ])
        self._actions_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._actions_table.horizontalHeader().setStretchLastSection(True)
        actions_layout.addWidget(self._actions_table)

        # Aktion hinzufügen
        add_action_layout = QHBoxLayout()
        self._action_ga = QLineEdit()
        self._action_ga.setPlaceholderText("GA oder Gewerk")
        add_action_layout.addWidget(self._action_ga)

        self._action_value = QLineEdit()
        self._action_value.setPlaceholderText("Wert (z.B. 50%)")
        add_action_layout.addWidget(self._action_value)

        self._action_delay = QDoubleSpinBox()
        self._action_delay.setRange(0, 60)
        self._action_delay.setSuffix(" s")
        add_action_layout.addWidget(self._action_delay)

        self._btn_add_action = QPushButton("+")
        self._btn_add_action.setFixedWidth(30)
        self._btn_add_action.clicked.connect(self._add_action)
        add_action_layout.addWidget(self._btn_add_action)

        self._btn_remove_action = QPushButton("-")
        self._btn_remove_action.setFixedWidth(30)
        self._btn_remove_action.setObjectName("danger")
        self._btn_remove_action.clicked.connect(self._remove_action)
        add_action_layout.addWidget(self._btn_remove_action)

        actions_layout.addLayout(add_action_layout)
        self._actions_group.setLayout(actions_layout)
        right.addWidget(self._actions_group)

        right.addStretch()
        content.addLayout(right, 1)
        layout.addLayout(content)

    def _load_templates(self):
        """Lädt Szenen-Vorlagen aus config/scene_templates.json."""
        config_path = Path(__file__).parent.parent.parent / "config" / "scene_templates.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._templates = data.get("scene_templates", [])

    def set_project(self, project: KnxProject):
        """Setzt das aktive Projekt."""
        self._project = project
        self._update_scope_combos()
        self._refresh_table()

    def _update_scope_combos(self):
        """Füllt die Raum/Zone-Combo mit Projektdaten."""
        self._scene_scope_id.clear()
        if not self._project:
            return

        self._scene_scope_id.addItem("(Zentral / Alle)", "")
        for room in self._project.all_rooms:
            self._scene_scope_id.addItem(
                f"{room.number} - {room.name}", room.id
            )
        for floor in self._project.all_floors:
            for apt in floor.apartments:
                self._scene_scope_id.addItem(
                    f"Zone: {apt.name}", apt.id
                )

    def _refresh_table(self):
        """Aktualisiert die Szenen-Tabelle."""
        if not self._project:
            self._table.setRowCount(0)
            self._info.setText("")
            return

        scenes = self._project.scenes
        self._table.setRowCount(len(scenes))

        scope_labels = {
            "room": "Raum",
            "apartment": "Wohnung/Zone",
            "zone": "Zone",
            "central": "Zentral",
        }

        for i, scene in enumerate(scenes):
            self._table.setItem(i, 0, QTableWidgetItem(scene.name))
            self._table.setItem(i, 1, QTableWidgetItem(str(scene.scene_number)))
            self._table.setItem(
                i, 2,
                QTableWidgetItem(scope_labels.get(scene.scope, scene.scope))
            )
            self._table.setItem(i, 3, QTableWidgetItem(scene.trigger))
            self._table.setItem(
                i, 4, QTableWidgetItem(str(len(scene.actions)))
            )

        fit_columns(self._table)
        self._info.setText(f"{len(scenes)} Szenen definiert")

    def _on_selection(self, row, col, prev_row, prev_col):
        """Zeigt Details der ausgewählten Szene."""
        if not self._project or row < 0 or row >= len(self._project.scenes):
            return

        scene = self._project.scenes[row]
        self._scene_name.setText(scene.name)
        self._scene_number.setValue(scene.scene_number)

        idx = self._scene_scope.findText(scene.scope)
        if idx >= 0:
            self._scene_scope.setCurrentIndex(idx)

        scope_idx = self._scene_scope_id.findData(scene.scope_id)
        if scope_idx >= 0:
            self._scene_scope_id.setCurrentIndex(scope_idx)

        self._scene_trigger.setText(scene.trigger)
        self._refresh_actions(scene)

    def _refresh_actions(self, scene: Scene):
        """Zeigt die Aktionen einer Szene."""
        self._actions_table.setRowCount(len(scene.actions))
        for i, action in enumerate(scene.actions):
            self._actions_table.setItem(
                i, 0, QTableWidgetItem(action.group_address)
            )
            self._actions_table.setItem(
                i, 1, QTableWidgetItem(action.value)
            )
            self._actions_table.setItem(
                i, 2, QTableWidgetItem(str(action.delay_seconds))
            )
        fit_columns(self._actions_table)

    def _get_selected_scene(self) -> Scene | None:
        """Gibt die aktuell ausgewählte Szene zurück."""
        row = self._table.currentRow()
        if not self._project or row < 0 or row >= len(self._project.scenes):
            return None
        return self._project.scenes[row]

    # --- Szenen-Aktionen ---

    def _add_scene(self):
        """Fügt eine neue leere Szene hinzu."""
        if not self._project:
            return

        next_num = 1
        if self._project.scenes:
            next_num = max(s.scene_number for s in self._project.scenes) + 1
            if next_num > 64:
                next_num = 1

        scene = Scene(
            name=f"Neue Szene {len(self._project.scenes) + 1}",
            scene_number=next_num,
            scope="room",
        )
        self._project.scenes.append(scene)
        self._refresh_table()

        # Neue Szene auswählen
        self._table.selectRow(len(self._project.scenes) - 1)

    def _add_from_template(self):
        """Erstellt eine Szene aus einer Vorlage."""
        if not self._project:
            return

        template_idx = self._template_combo.currentData()
        if template_idx is None or template_idx < 0:
            QMessageBox.information(
                self, "Hinweis",
                "Bitte wählen Sie zuerst eine Vorlage aus."
            )
            return

        template = self._templates[template_idx]
        next_num = 1
        if self._project.scenes:
            next_num = max(s.scene_number for s in self._project.scenes) + 1
            if next_num > 64:
                next_num = 1

        actions = []
        for action_def in template.get("actions", []):
            actions.append(SceneAction(
                group_address=action_def.get("gewerk_category", ""),
                value=action_def.get("action", ""),
            ))

        scene = Scene(
            name=template["name"],
            scene_number=next_num,
            scope="room",
            actions=actions,
        )
        self._project.scenes.append(scene)
        self._refresh_table()
        self._table.selectRow(len(self._project.scenes) - 1)

    def _remove_scene(self):
        """Entfernt die ausgewählte Szene."""
        scene = self._get_selected_scene()
        if not scene or not self._project:
            return

        reply = QMessageBox.question(
            self, "Szene entfernen",
            f"Szene '{scene.name}' wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._project.scenes.remove(scene)
            self._refresh_table()
            self._actions_table.setRowCount(0)

    def _apply_changes(self):
        """Übernimmt Änderungen an der ausgewählten Szene."""
        scene = self._get_selected_scene()
        if not scene:
            return

        scene.name = self._scene_name.text()
        scene.scene_number = self._scene_number.value()
        scene.scope = self._scene_scope.currentText()
        scene.scope_id = self._scene_scope_id.currentData() or ""
        scene.trigger = self._scene_trigger.text()

        self._refresh_table()

    # --- Aktionen-Verwaltung ---

    def _add_action(self):
        """Fügt eine Aktion zur ausgewählten Szene hinzu."""
        scene = self._get_selected_scene()
        if not scene:
            return

        ga = self._action_ga.text().strip()
        value = self._action_value.text().strip()
        delay = self._action_delay.value()

        if not ga or not value:
            return

        scene.actions.append(SceneAction(
            group_address=ga,
            value=value,
            delay_seconds=delay,
        ))
        self._refresh_actions(scene)
        self._refresh_table()

        # Felder leeren
        self._action_ga.clear()
        self._action_value.clear()
        self._action_delay.setValue(0)

    def _remove_action(self):
        """Entfernt die ausgewählte Aktion."""
        scene = self._get_selected_scene()
        if not scene:
            return

        row = self._actions_table.currentRow()
        if 0 <= row < len(scene.actions):
            scene.actions.pop(row)
            self._refresh_actions(scene)
            self._refresh_table()
