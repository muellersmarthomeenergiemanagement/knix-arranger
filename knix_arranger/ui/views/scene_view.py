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
from PySide6.QtCore import Qt, Signal
from ...models.project import KnxProject
from ...models.scene import Scene, SceneAction
from ...services.scene_detection_service import detect_scenes
from ...services.scene_value_linking import link_scene_values, link_scene_triggers
from ...services.scene_addressing import (
    group_named_scenes, is_bound_scene, scene_group_key,
)
from ..column_utils import fit_columns

# Interne Scope-Codes (im Datenmodell gespeichert) -> Anzeigetext.
_SCOPE_LABELS = {
    "room": "Raum",
    "apartment": "Wohnung/Zone",
    "zone": "Zone",
    "central": "Zentral",
}


class SceneView(QWidget):
    """Szenen-Verwaltung: Erstellen, Bearbeiten, Vorlagen anwenden."""

    # Wird ausgeloest, wenn der Nutzer im Veraltet-Hinweisbanner auf
    # "Jetzt generieren" klickt -- main_window verbindet dies mit dem
    # Oeffnen des Wizards direkt bei Schritt 10 (Gruppenadressen).
    request_generate_addresses = Signal()

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

        # Hinweisbanner: Szenen ohne (aktuelle) Gruppenadresse. Szenen sind
        # zunaechst nur Datensaetze -- die eigentliche Szenenaufruf-GA
        # entsteht erst durch "Gruppenadressen generieren" in Schritt 10
        # des Wizards, nicht automatisch beim Anlegen/Aendern einer Szene.
        self._stale_banner = QWidget()
        stale_layout = QHBoxLayout(self._stale_banner)
        stale_layout.setContentsMargins(8, 6, 8, 6)
        self._stale_label = QLabel("")
        self._stale_label.setWordWrap(True)
        stale_layout.addWidget(self._stale_label, 1)
        self._btn_generate_addresses = QPushButton("Jetzt generieren")
        self._btn_generate_addresses.clicked.connect(
            self.request_generate_addresses.emit
        )
        stale_layout.addWidget(self._btn_generate_addresses)
        self._stale_banner.setStyleSheet(
            "background-color: #FFF3CD; color: #856404; border-radius: 4px;"
        )
        self._stale_banner.hide()
        layout.addWidget(self._stale_banner)

        # Hauptbereich: Szenen-Tabelle links, Details rechts
        content = QHBoxLayout()

        # --- Linke Seite: Szenen-Tabelle + Buttons ---
        left = QVBoxLayout()

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Name", "Nr.", "Geltungsbereich", "Auslöser", "Aktionen", "Quelle",
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
        self._btn_add_same_ga = QPushButton("+ Weitere Szene auf dieser GA")
        self._btn_add_same_ga.setToolTip(
            "Legt für die ausgewählte Szene eine weitere Szene auf derselben "
            "Szenen-Gruppenadresse an: nächste freie Szenennummer, gleicher "
            "Geltungsbereich, gleiche GA."
        )
        self._btn_add_same_ga.clicked.connect(self._add_scene_on_same_ga)
        self._btn_from_template = QPushButton("Aus Vorlage")
        self._btn_from_template.clicked.connect(self._add_from_template)
        self._btn_detect = QPushButton("Szenen erkennen")
        self._btn_detect.setToolTip(
            "Durchsucht importierte Gruppenadressen nach Szenen-Funktionen "
            "(Szenennummer-DPTs, Szenen-Ordner, Taster-Lichtstimmungen)."
        )
        self._btn_detect.clicked.connect(self._detect_scenes)
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("danger")
        self._btn_remove.clicked.connect(self._remove_scene)
        self._btn_remove_all = QPushButton("Alle löschen")
        self._btn_remove_all.setObjectName("danger")
        self._btn_remove_all.setToolTip(
            "Entfernt alle Szenen dieses Projekts (manuell angelegte und "
            "automatisch erkannte). Die zugrundeliegenden Gruppenadressen "
            "bleiben unverändert."
        )
        self._btn_remove_all.clicked.connect(self._remove_all_scenes)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_add_same_ga)
        btn_layout.addWidget(self._btn_from_template)
        btn_layout.addWidget(self._btn_detect)
        btn_layout.addWidget(self._btn_remove)
        btn_layout.addWidget(self._btn_remove_all)
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

        content.addLayout(left, 3)

        # --- Rechte Seite: Detail-Panel ---
        right = QVBoxLayout()

        # Szenen-Details
        self._detail_group = QGroupBox("Szenen-Details")
        detail_form = QFormLayout()

        self._scene_name = QLineEdit()
        detail_form.addRow("Name:", self._scene_name)

        self._scene_number = QSpinBox()
        self._scene_number.setRange(1, 64)
        self._scene_number.setToolTip(
            "KNX-Konvention (DPT 17/18): Szenen mit gleichem Geltungsbereich "
            "teilen sich eine gemeinsame Szenenaufruf-GA. Szene 1 = Bus-Wert 0, "
            "Szene 2 = Bus-Wert 1, ... Szene 64 = Bus-Wert 63. Welcher Aktor bei "
            "welcher Nummer was tut, wird in dessen eigenen ETS-Parametern "
            "konfiguriert, nicht hier."
        )
        detail_form.addRow("Szenen-Nr. (1-64):", self._scene_number)

        self._scene_scope = QComboBox()
        for code, label in _SCOPE_LABELS.items():
            self._scene_scope.addItem(label, code)
        self._scene_scope.setToolTip(
            "Szenen mit gleichem Geltungsbereich (+ Raum/Zone) teilen sich beim "
            "Generieren der Adressen (Schritt 10) eine gemeinsame Szenenaufruf-GA."
        )
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
        self._actions_table.setColumnCount(4)
        self._actions_table.setHorizontalHeaderLabels([
            "Gruppenadresse / Gewerk", "Adresse", "Wert", "Verzögerung (s)",
        ])
        self._actions_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self._actions_table.horizontalHeader().setStretchLastSection(True)
        # Standardbreite (100 px) war schmaler als "Gruppenadresse / Gewerk"
        for col in range(self._actions_table.columnCount()):
            self._actions_table.setColumnWidth(
                col, max(100, self._actions_table.horizontalHeader().sectionSizeHint(col) + 16))
        self._actions_table.itemChanged.connect(self._on_action_item_changed)
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

        # Padding-Override: siehe customer_quote_view.py.
        self._btn_add_action = QPushButton("+")
        self._btn_add_action.setFixedWidth(30)
        self._btn_add_action.setStyleSheet("padding: 2px;")
        self._btn_add_action.clicked.connect(self._add_action)
        add_action_layout.addWidget(self._btn_add_action)

        self._btn_remove_action = QPushButton("-")
        self._btn_remove_action.setFixedWidth(30)
        self._btn_remove_action.setObjectName("danger")
        self._btn_remove_action.setStyleSheet("padding: 2px;")
        self._btn_remove_action.clicked.connect(self._remove_action)
        add_action_layout.addWidget(self._btn_remove_action)

        actions_layout.addLayout(add_action_layout)
        self._actions_group.setLayout(actions_layout)
        right.addWidget(self._actions_group)

        right.addStretch()
        # 3:2 statt 2:1 -- sonst sind Aktionstabelle und Eingabefelder rechts
        # bei 1280 px Fensterbreite abgeschnitten
        content.addLayout(right, 2)
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

        source_labels = {
            "dpt": "Import (DPT)",
            "folder": "Import (Ordner)",
            "pattern": "Import (Muster)",
        }

        for i, scene in enumerate(scenes):
            self._table.setItem(i, 0, QTableWidgetItem(scene.name))
            self._table.setItem(i, 1, QTableWidgetItem(str(scene.scene_number or "")))
            self._table.setItem(
                i, 2,
                QTableWidgetItem(_SCOPE_LABELS.get(scene.scope, scene.scope))
            )
            self._table.setItem(i, 3, QTableWidgetItem(scene.trigger))
            self._table.setItem(
                i, 4, QTableWidgetItem(str(len(scene.actions)))
            )
            source_text = source_labels.get(scene.detection_kind, "")
            if is_bound_scene(scene):
                source_text = f"Manuell → {', '.join(scene.source_ga_addresses)}"
            self._table.setItem(i, 5, QTableWidgetItem(source_text))

        fit_columns(self._table)
        self._info.setText(f"{len(scenes)} Szenen definiert")
        self._update_stale_banner()

    def _update_stale_banner(self):
        """
        Zeigt einen Hinweis, wenn fuer benannte, nicht-erkannte Szenen noch
        keine passende Szenenaufruf-GA existiert (weil "Gruppenadressen
        generieren" in Schritt 10 noch nie oder seit der letzten Aenderung
        nicht mehr gelaufen ist). Nutzt dieselbe Gruppierung/Benennung wie
        die tatsaechliche Generierung (services/scene_addressing.py), damit
        der Vergleich exakt zum spaeter erzeugten Ergebnis passt.
        """
        if not self._project:
            self._stale_banner.hide()
            return

        groups = group_named_scenes(self._project.scenes, self._project.areal)
        if not groups:
            self._stale_banner.hide()
            return

        existing_designations = {
            ga.designation for ga in self._project.group_addresses.all_addresses()
            if ga.function_name == "SZENE" and not ga.is_placeholder
        }
        missing = [
            designation for designation, _scenes in groups.values()
            if designation not in existing_designations
        ]
        if not missing:
            self._stale_banner.hide()
            return

        self._stale_label.setText(
            "Für folgende Szenen-Geltungsbereiche fehlt noch die Gruppenadresse "
            "(wird erst durch \"Gruppenadressen generieren\" in Schritt 10 des "
            f"Wizards erzeugt): {', '.join(sorted(missing))}."
        )
        self._stale_banner.show()

    def _on_selection(self, row, col, prev_row, prev_col):
        """Zeigt Details der ausgewählten Szene."""
        if not self._project or row < 0 or row >= len(self._project.scenes):
            return

        scene = self._project.scenes[row]
        self._scene_name.setText(scene.name)
        self._scene_number.setValue(scene.scene_number)

        idx = self._scene_scope.findData(scene.scope)
        if idx >= 0:
            self._scene_scope.setCurrentIndex(idx)

        scope_idx = self._scene_scope_id.findData(scene.scope_id)
        if scope_idx >= 0:
            self._scene_scope_id.setCurrentIndex(scope_idx)

        self._scene_trigger.setText(scene.trigger)
        self._refresh_actions(scene)

    def _refresh_actions(self, scene: Scene):
        """Zeigt die Aktionen einer Szene."""
        # Signale waehrend des Befuellens blockieren, sonst loest jedes
        # setItem() _on_action_item_changed() aus und schreibt die gerade
        # erst angezeigten Werte unnoetig (aber harmlos) zurueck in die Szene.
        self._actions_table.blockSignals(True)
        self._actions_table.setRowCount(len(scene.actions))
        for i, action in enumerate(scene.actions):
            self._actions_table.setItem(
                i, 0, QTableWidgetItem(action.group_address)
            )
            self._actions_table.setItem(
                i, 1, QTableWidgetItem(action.ga_address)
            )
            self._actions_table.setItem(
                i, 2, QTableWidgetItem(action.value)
            )
            self._actions_table.setItem(
                i, 3, QTableWidgetItem(str(action.delay_seconds))
            )
        self._actions_table.blockSignals(False)
        fit_columns(self._actions_table)

    def _on_action_item_changed(self, item: QTableWidgetItem):
        """Schreibt eine per Doppelklick bearbeitete Aktions-Zelle zurueck in
        die Szene (Nachbearbeiten bestehender Aktionen, ohne sie loeschen und
        neu anlegen zu muessen)."""
        scene = self._get_selected_scene()
        if not scene:
            return
        row, col = item.row(), item.column()
        if row >= len(scene.actions):
            return
        action = scene.actions[row]
        text = item.text().strip()
        if col == 0:
            action.group_address = text
        elif col == 1:
            action.ga_address = text
        elif col == 2:
            action.value = text
        elif col == 3:
            try:
                action.delay_seconds = float(text.replace(",", "."))
            except ValueError:
                # Ungueltige Eingabe: Zelle auf den bisherigen Wert zuruecksetzen,
                # statt einen kaputten Zustand in der Szene zu speichern.
                self._actions_table.blockSignals(True)
                item.setText(str(action.delay_seconds))
                self._actions_table.blockSignals(False)

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
            # "central" passt zum ebenfalls leeren scope_id (siehe
            # scene_addressing.scene_group_key: scope_id or "central") --
            # "room" ohne gewaehlten Raum waere ein inkonsistenter Zustand,
            # der die Szene unbemerkt als zentrale Szene behandelt haette.
            scope="central",
        )
        self._project.scenes.append(scene)
        self._refresh_table()

        # Neue Szene auswählen
        self._table.selectRow(len(self._project.scenes) - 1)

    def _add_scene_on_same_ga(self):
        """Legt eine weitere Szene auf der Szenen-GA der ausgewählten Szene an
        (nächste freie Nummer, gleicher Geltungsbereich). Ist die Szene an eine
        bestehende GA gebunden (erkannt oder selbst gebunden), wird auch die
        neue Szene an diese GA gebunden -- sonst teilt sie sich über den
        Geltungsbereich die generierte Szenenaufruf-GA."""
        source = self._get_selected_scene()
        if not self._project or not source:
            QMessageBox.information(
                self, "Hinweis", "Bitte zuerst die Szene auswählen, deren "
                "Gruppenadresse erweitert werden soll."
            )
            return

        bound_addrs = list(source.source_ga_addresses)
        if bound_addrs:
            # Auch von Hand angelegte Szenen, deren Aktion diese GA nennt,
            # belegen ihre Nummer -- sonst entstünde eine doppelte Nummer.
            same_channel = [
                s for s in self._project.scenes
                if set(s.source_ga_addresses) == set(bound_addrs)
                or (not s.source_ga_addresses
                    and any(a.ga_address in bound_addrs for a in s.actions))
            ]
        else:
            same_channel = [
                s for s in self._project.scenes
                if not s.is_detected and not s.source_ga_addresses
                and scene_group_key(s) == scene_group_key(source)
            ]
        used = {s.scene_number for s in same_channel}
        next_num = next((n for n in range(1, 65) if n not in used), None)
        if next_num is None:
            QMessageBox.information(
                self, "Hinweis",
                "Auf dieser Gruppenadresse sind bereits alle 64 Szenennummern belegt."
            )
            return

        actions = []
        if bound_addrs:
            by_addr = {
                ga.address: ga for ga in self._project.group_addresses.all_addresses()
            }
            for addr in bound_addrs:
                ga = by_addr.get(addr)
                actions.append(SceneAction(
                    group_address=ga.designation if ga else addr,
                    ga_address=addr,
                ))

        scene = Scene(
            name=f"Neue Szene {next_num}",
            scene_number=next_num,
            scope=source.scope,
            scope_id=source.scope_id,
            actions=actions,
            source_ga_addresses=bound_addrs,
        )
        # Direkt hinter den bisherigen Szenen dieser GA einfügen
        insert_at = max(self._project.scenes.index(s) for s in same_channel) + 1 \
            if same_channel else len(self._project.scenes)
        self._project.scenes.insert(insert_at, scene)
        self._refresh_table()
        self._table.selectRow(insert_at)
        self._scene_name.setFocus()
        self._scene_name.selectAll()

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
            scope="central",  # siehe Begruendung in _add_scene()
            actions=actions,
        )
        self._project.scenes.append(scene)
        self._refresh_table()
        self._table.selectRow(len(self._project.scenes) - 1)

    def _detect_scenes(self):
        """Erkennt Szenen in importierten Gruppenadressen und übernimmt sie
        (FA-1808); ergänzt ausserdem echte Schaltwerte (Aktor-Seite, FA-1809)
        und Ausloeser (Sensor-Seite: welche Taste sendet welche Szenennummer,
        FA-1810) aus den Geräteparametern, sofern ein Topologie-/Gebäude-
        Report mit erkennbarem Muster importiert wurde."""
        if not self._project:
            return

        added = detect_scenes(self._project)
        if added:
            self._project.scenes.extend(added)

        count_before_linking = len(self._project.scenes)
        linked = link_scene_values(self._project)
        triggers_linked = link_scene_triggers(self._project)
        new_numbered_scenes = self._project.scenes[count_before_linking:]

        if not added and not linked and not triggers_linked:
            QMessageBox.information(
                self, "Szenen erkennen",
                "Keine neuen Szenen oder Schaltwerte gefunden."
            )
            return

        self._refresh_table()
        if new_numbered_scenes:
            # link_scene_values/link_scene_triggers haben eine geteilte
            # "Kanal"-Szene (Nr. 0, z.B. "Anwesendheit Chalet") in separate
            # numerierte Szenen aufgeteilt (z.B. "... – Szene 2") -- dorthin
            # springen, sonst sind die neuen Zeilen am Tabellenende bei
            # vielen Szenen leicht zu uebersehen.
            self._table.selectRow(count_before_linking)
        elif added:
            self._table.selectRow(len(self._project.scenes) - len(added))
        elif linked or triggers_linked:
            selected = self._get_selected_scene()
            if selected:
                self._refresh_actions(selected)

        parts = []
        if added:
            parts.append(f"{len(added)} neue Szene(n) aus Gruppenadressen übernommen")
        if linked:
            parts.append(f"{linked} Aktion(en) aus Gerätedaten ergänzt")
        if triggers_linked:
            parts.append(f"{triggers_linked} Auslöser aus Tastenkonfiguration ergänzt")
        if new_numbered_scenes:
            parts.append(
                f"{len(new_numbered_scenes)} numerierte Szene(n) aus geteiltem "
                f"Recall-Kanal aufgeteilt (siehe markierte Zeile)"
            )
        QMessageBox.information(self, "Szenen erkennen", " – ".join(parts) + ".")

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

    def _remove_all_scenes(self):
        """Entfernt alle Szenen dieses Projekts (manuell + automatisch erkannt)."""
        if not self._project or not self._project.scenes:
            return

        count = len(self._project.scenes)
        reply = QMessageBox.question(
            self, "Alle Szenen löschen",
            f"Alle {count} Szenen wirklich löschen? Das kann nicht rückgängig "
            f"gemacht werden.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._project.scenes.clear()
            self._refresh_table()
            self._actions_table.setRowCount(0)

    def _apply_changes(self):
        """Übernimmt Änderungen an der ausgewählten Szene."""
        scene = self._get_selected_scene()
        if not scene:
            return

        new_scope = self._scene_scope.currentData()
        new_scope_id = self._scene_scope_id.currentData() or ""

        # Ein Geltungsbereich "Raum"/"Wohnung/Zone"/"Zone" ohne konkretes Ziel
        # ist ein inkonsistenter Zustand: scene_addressing.scene_group_key()
        # wertet ausschliesslich scope_id aus (scope_id or "central") -- die
        # Szene wuerde unbemerkt als zentrale Szene behandelt und taucht in
        # der Bedienungsanleitung in keinem Raum-Abschnitt auf
        # (documentation_service.py: scope=="room" and scope_id==room.id).
        if new_scope != "central" and not new_scope_id:
            QMessageBox.warning(
                self, "Geltungsbereich unvollständig",
                "Bitte wählen Sie unter 'Raum/Zone' ein konkretes Ziel aus, "
                "wenn der Geltungsbereich nicht 'Zentral' ist -- sonst kann "
                "die Szene später nicht korrekt zugeordnet werden."
            )
            return

        scene.name = self._scene_name.text()
        scene.scene_number = self._scene_number.value()
        scene.scope = new_scope
        scene.scope_id = new_scope_id
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

        if not ga:
            QMessageBox.information(
                self, "Hinweis",
                "Bitte geben Sie eine Gruppenadresse oder ein Gewerk an."
            )
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
