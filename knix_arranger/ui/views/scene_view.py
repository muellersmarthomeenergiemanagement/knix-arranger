"""
Szenen-Verwaltung (FA-1801 bis FA-1807, FA-1812)

Gegliedert wie der Szenenreport nach der Szenen-Gruppenadresse
(services/scene_overview): oben die Adresse, darunter ihre Szenennummern.
Geplante Szenen, deren Adresse erst in Schritt 10 entsteht, bilden eine
künftige Adresse je Geltungsbereich. Szenen der Visualisierung und nicht
eindeutig erkannte Adressen stehen in eigenen, zugeklappten Abschnitten.
"""
from __future__ import annotations
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QSpinBox,
    QLineEdit, QGroupBox, QFormLayout, QAbstractItemView,
    QMessageBox, QDoubleSpinBox, QTreeWidget, QTreeWidgetItem, QInputDialog,
    QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from ...models.project import KnxProject
from ...models.scene import Scene, SceneAction
from ...services.dpt_suggestion import dpt_number
from ...services.scene_detection_service import detect_scenes
from ...services.scene_value_linking import (
    link_scene_values, link_scene_triggers, link_scene_names,
)
from ...services.scene_addressing import (
    build_scope_label_lookup, group_named_scenes, is_bound_scene, scene_group_key,
)
from ...services.scene_overview import (
    SCOPE_LABELS, SceneAddress, build_scene_overview, linked_devices, scope_text,
)
from ..column_utils import fit_columns

# Interne Scope-Codes (im Datenmodell gespeichert) -> Anzeigetext.
_SCOPE_LABELS = SCOPE_LABELS

_ROLE = Qt.UserRole
_COLOR_HINT = QColor("#757575")
_COLOR_WARN = QColor("#B26A00")
_SOURCE_LABELS = {
    "dpt": "Import (DPT)",
    "folder": "Import (Ordner)",
    "pattern": "Import (Muster)",
}


class SceneView(QWidget):
    """Szenen-Verwaltung: Szenen-Adressen mit ihren Szenen, Vorlagen, Erkennung."""

    # Wird ausgeloest, wenn der Nutzer im Veraltet-Hinweisbanner auf
    # "Jetzt generieren" klickt -- main_window verbindet dies mit dem
    # Oeffnen des Wizards direkt bei Schritt 10 (Gruppenadressen).
    request_generate_addresses = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        self._templates: list[dict] = []
        self._overview = None
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

        # Hauptbereich: Baum links, Details rechts
        content = QHBoxLayout()

        # --- Linke Seite: Szenen-Adressen mit Szenen + Buttons ---
        left = QVBoxLayout()

        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels([
            "Szenen-Adresse / Szene", "Nr.", "Geltungsbereich / Auslöser",
            "Szenen / Aktionen", "Quelle / DPT",
        ])
        self._tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tree.setAlternatingRowColors(True)
        self._tree.currentItemChanged.connect(self._on_selection)
        left.addWidget(self._tree)

        # Buttons
        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("+ Neue Szenen-Adresse")
        self._btn_add.setToolTip(
            "Neue Szene mit eigenem Geltungsbereich anlegen. Szenen mit gleichem "
            "Geltungsbereich teilen sich eine Szenen-Adresse (Schritt 10)."
        )
        self._btn_add.clicked.connect(self._add_scene)
        self._btn_add_same_ga = QPushButton("+ Szene auf dieser Adresse")
        self._btn_add_same_ga.setToolTip(
            "Legt auf der ausgewählten Szenen-Adresse eine weitere Szene an: "
            "nächste freie Szenennummer, gleicher Geltungsbereich."
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
        for button in (self._btn_add, self._btn_add_same_ga, self._btn_from_template,
                       self._btn_detect, self._btn_remove, self._btn_remove_all):
            btn_layout.addWidget(button)
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

        # --- Rechte Seite: Adress- bzw. Szenen-Details ---
        right = QVBoxLayout()

        # Adress-Details: gelten für alle Szenen der Adresse
        self._address_group = QGroupBox("Szenen-Adresse")
        address_form = QFormLayout()
        self._address_label = QLabel()
        self._address_label.setWordWrap(True)
        self._address_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        address_form.addRow("Adresse:", self._address_label)
        self._address_dpt = QLabel()
        address_form.addRow("Datentyp:", self._address_dpt)
        self._address_comment = QLabel()
        self._address_comment.setWordWrap(True)
        address_form.addRow("Kommentar:", self._address_comment)

        self._scene_scope = QComboBox()
        for code, label in _SCOPE_LABELS.items():
            self._scene_scope.addItem(label, code)
        self._scene_scope.setToolTip(
            "Gilt für alle Szenen dieser Adresse. Szenen mit gleichem "
            "Geltungsbereich (+ Raum/Zone) teilen sich beim Generieren der "
            "Adressen (Schritt 10) eine gemeinsame Szenenaufruf-GA."
        )
        address_form.addRow("Geltungsbereich:", self._scene_scope)
        self._scene_scope_id = QComboBox()
        address_form.addRow("Raum/Zone:", self._scene_scope_id)
        self._btn_apply_address = QPushButton("Geltungsbereich übernehmen")
        self._btn_apply_address.clicked.connect(self._apply_address_changes)
        address_form.addRow("", self._btn_apply_address)

        # Verknüpfte Geräte: Sender (Taster, Sensoren) und Empfänger (Aktoren)
        self._address_devices = QListWidget()
        self._address_devices.setMaximumHeight(130)
        address_form.addRow("Verknüpft:", self._address_devices)
        self._address_group.setLayout(address_form)
        right.addWidget(self._address_group)

        # Szenen-Details
        self._detail_group = QGroupBox("Szene")
        detail_form = QFormLayout()

        self._scene_name = QLineEdit()
        detail_form.addRow("Name:", self._scene_name)

        self._scene_number = QSpinBox()
        self._scene_number.setRange(1, 64)
        self._scene_number.setToolTip(
            "KNX-Konvention (DPT 17/18): Szene 1 = Bus-Wert 0, Szene 2 = "
            "Bus-Wert 1, ... Szene 64 = Bus-Wert 63. Welcher Aktor bei welcher "
            "Nummer was tut, wird in dessen eigenen ETS-Parametern "
            "konfiguriert, nicht hier."
        )
        detail_form.addRow("Szenen-Nr. (1-64):", self._scene_number)

        self._scene_address = QComboBox()
        self._scene_address.setToolTip(
            "Szenen-Adresse, über die die Szene aufgerufen wird. Wechseln "
            "verschiebt die Szene samt Geltungsbereich auf die andere Adresse."
        )
        detail_form.addRow("Szenen-Adresse:", self._scene_address)

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
        self._show_details(None)

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

    # --- Baum ---

    def _refresh_table(self, select=None):
        """Baut den Baum neu auf; select = Szene oder SceneAddress, die danach
        ausgewählt sein soll (Standard: bisherige Auswahl)."""
        if select is None:
            select = self._selected_object()
        self._tree.blockSignals(True)
        self._tree.clear()
        if not self._project:
            self._tree.blockSignals(False)
            self._info.setText("")
            self._show_details(None)
            return

        self._overview = build_scene_overview(self._project)
        labels = build_scope_label_lookup(self._project.areal)
        target_item = None

        def add_address(parent, group: SceneAddress, warn: str = ""):
            nonlocal target_item
            if group.planned:
                text = f"{group.designation}  (wird in Schritt 10 erzeugt)"
            else:
                text = f"{group.ga.address}  {' '.join(group.designation.split())}"
            anchor = group.anchor_scene
            n = len(group.scenes)
            quelle = warn or ("geplant" if group.planned else
                              dpt_number(group.ga.datapoint_type or "") or "DPT fehlt")
            item = QTreeWidgetItem(parent, [
                text, "", scope_text(anchor, labels) if anchor else "Zentral",
                f"{n} {'Szene' if n == 1 else 'Szenen'}", quelle,
            ])
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setData(0, _ROLE, ("address", group))
            if group.planned or warn or not group.dpt_ok:
                item.setForeground(4, _COLOR_WARN)
            if select is group or (isinstance(select, SceneAddress) and select.key == group.key):
                target_item = item
            for scene in group.scenes:
                add_scene(item, scene)
            return item

        def add_scene(parent, scene: Scene):
            nonlocal target_item
            source = _SOURCE_LABELS.get(scene.detection_kind, "")
            if is_bound_scene(scene):
                source = f"Manuell → {', '.join(scene.source_ga_addresses)}"
            item = QTreeWidgetItem(parent, [
                scene.name, str(scene.scene_number or ""), scene.trigger,
                str(len(scene.actions)), source,
            ])
            item.setData(0, _ROLE, ("scene", scene))
            if select is scene:
                target_item = item
            return item

        for group in self._overview.addresses:
            add_address(self._tree, group).setExpanded(True)

        if self._overview.visu:
            section = QTreeWidgetItem(self._tree, [
                f"Szenen der Visualisierung ({len(self._overview.visu)})", "", "",
                "", "keine KNX-Szenenadressen"])
            section.setData(0, _ROLE, ("section", "visu"))
            section.setForeground(0, _COLOR_HINT)
            for scene in self._overview.visu:
                add_scene(section, scene)
        if self._overview.unclear:
            section = QTreeWidgetItem(self._tree, [
                f"Nicht eindeutig ({len(self._overview.unclear)})", "", "", "",
                "prüfen"])
            section.setData(0, _ROLE, ("section", "unclear"))
            section.setForeground(0, _COLOR_WARN)
            for group in self._overview.unclear:
                add_address(section, group, warn="DPT keine Szene")

        self._tree.blockSignals(False)
        fit_columns(self._tree)
        n_scenes = sum(len(g.scenes) for g in self._overview.addresses)
        self._info.setText(
            f"{len(self._overview.addresses)} Szenen-Adressen mit {n_scenes} Szenen"
            + (f" · {len(self._overview.visu)} Szenen der Visualisierung"
               if self._overview.visu else "")
            + (f" · {len(self._overview.unclear)} nicht eindeutig"
               if self._overview.unclear else "")
        )
        self._update_stale_banner()
        if target_item is not None:
            parent = target_item.parent()
            if parent is not None:
                parent.setExpanded(True)
            self._tree.setCurrentItem(target_item)
        else:
            self._show_details(None)

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

    # --- Auswahl und Details ---

    def _selected_data(self):
        item = self._tree.currentItem()
        return item.data(0, _ROLE) if item is not None else None

    def _selected_object(self):
        data = self._selected_data()
        return data[1] if data and data[0] in ("scene", "address") else None

    def _get_selected_scene(self) -> Scene | None:
        """Gibt die aktuell ausgewählte Szene zurück."""
        data = self._selected_data()
        return data[1] if data and data[0] == "scene" else None

    def _get_selected_address(self) -> SceneAddress | None:
        """Ausgewählte Szenen-Adresse – direkt oder über eine ihrer Szenen."""
        data = self._selected_data()
        if not data or self._overview is None:
            return None
        if data[0] == "address":
            return data[1]
        if data[0] == "scene":
            return self._overview.address_of(data[1])
        return None

    def _select_scene(self, scene) -> None:
        """Wählt eine Szene (oder SceneAddress) im Baum aus."""
        self._refresh_table(select=scene)

    def _on_selection(self, current, previous=None):
        data = current.data(0, _ROLE) if current is not None else None
        self._show_details(data)

    def _show_details(self, data):
        kind, obj = data if data else (None, None)
        address = None
        if kind == "address":
            address = obj
        elif kind == "scene" and self._overview is not None:
            address = self._overview.address_of(obj)
        self._address_group.setVisible(address is not None)
        self._detail_group.setVisible(kind == "scene")
        self._actions_group.setVisible(kind == "scene")
        if address is not None:
            self._fill_address(address)
        if kind == "scene":
            self._fill_scene(obj, address)

    def _fill_address(self, group: SceneAddress):
        if group.planned:
            self._address_label.setText(f"{group.designation}\n(wird in Schritt 10 erzeugt)")
            self._address_dpt.setText("–")
            self._address_comment.setText("–")
            self._address_devices.clear()
        else:
            ga = group.ga
            self._address_label.setText(f"{ga.address}  {' '.join(ga.designation.split())}")
            dpt = dpt_number(ga.datapoint_type or "") or "fehlt"
            self._address_dpt.setText(
                dpt if group.dpt_ok else f"{dpt} – für Szenen wird 17.001/18.001 erwartet")
            self._address_comment.setText(ga.comment or "–")
            self._address_devices.clear()
            for link in linked_devices(self._project, ga.address):
                entry = QListWidgetItem(
                    f"{link.device.physical_address}  {link.device.product or ''}  "
                    f"({link.role})")
                entry.setToolTip("\n".join(link.objects))
                self._address_devices.addItem(entry)
            if not self._address_devices.count():
                self._address_devices.addItem("keine Geräte verknüpft")
        anchor = group.anchor_scene
        if anchor is not None:
            idx = self._scene_scope.findData(anchor.scope or "central")
            if idx >= 0:
                self._scene_scope.setCurrentIndex(idx)
            scope_idx = self._scene_scope_id.findData(anchor.scope_id)
            if scope_idx >= 0:
                self._scene_scope_id.setCurrentIndex(scope_idx)

    def _fill_scene(self, scene: Scene, address: SceneAddress | None):
        self._scene_name.setText(scene.name)
        self._scene_number.setValue(max(1, scene.scene_number))
        self._scene_trigger.setText(scene.trigger)

        # Verschieben nur bei selbst angelegten Szenen; erkannte gehören zu
        # ihrer importierten Adresse
        self._scene_address.blockSignals(True)
        self._scene_address.clear()
        for group in self._overview.addresses if self._overview else []:
            label = (f"{group.designation} (geplant)" if group.planned
                     else f"{group.ga.address}  {' '.join(group.designation.split())}")
            self._scene_address.addItem(label, group.key)
        if address is not None:
            idx = self._scene_address.findData(address.key)
            if idx < 0:
                self._scene_address.addItem(address.designation, address.key)
                idx = self._scene_address.count() - 1
            self._scene_address.setCurrentIndex(idx)
        self._scene_address.setEnabled(not scene.is_detected and address is not None)
        self._scene_address.blockSignals(False)
        self._refresh_actions(scene)

    def _refresh_actions(self, scene: Scene):
        """Zeigt die Aktionen einer Szene."""
        # Signale waehrend des Befuellens blockieren, sonst loest jedes
        # setItem() _on_action_item_changed() aus und schreibt die gerade
        # erst angezeigten Werte unnoetig (aber harmlos) zurueck in die Szene.
        self._actions_table.blockSignals(True)
        self._actions_table.setRowCount(len(scene.actions))
        for i, action in enumerate(scene.actions):
            self._actions_table.setItem(i, 0, QTableWidgetItem(action.group_address))
            self._actions_table.setItem(i, 1, QTableWidgetItem(action.ga_address))
            self._actions_table.setItem(i, 2, QTableWidgetItem(action.value))
            self._actions_table.setItem(i, 3, QTableWidgetItem(str(action.delay_seconds)))
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

    # --- Szenen anlegen ---

    def _scope_choices(self) -> list[tuple[str, str, str]]:
        """(Anzeige, scope, scope_id) für die Wahl einer neuen Szenen-Adresse."""
        choices = [("Zentral", "central", "")]
        if self._project:
            choices += [(f"Raum {r.number} {r.name}".strip(), "room", r.id)
                        for r in self._project.all_rooms]
            choices += [(f"Zone {apt.name}", "apartment", apt.id)
                        for floor in self._project.all_floors for apt in floor.apartments]
        return choices

    def _add_scene(self):
        """Neue Szene mit wählbarem Geltungsbereich – gibt es dafür schon eine
        (künftige) Szenen-Adresse, landet sie dort mit der nächsten freien
        Nummer, sonst entsteht eine neue Adresse."""
        if not self._project:
            return
        choices = self._scope_choices()
        label, ok = QInputDialog.getItem(
            self, "Neue Szenen-Adresse", "Geltungsbereich der Szenen-Adresse:",
            [c[0] for c in choices], 0, False)
        if not ok:
            return
        _label, scope, scope_id = next(c for c in choices if c[0] == label)
        self._create_scene(scope, scope_id)

    def _create_scene(self, scope: str, scope_id: str, name: str = "",
                      actions: list | None = None) -> Scene | None:
        probe = Scene(scope=scope, scope_id=scope_id)
        used = {s.scene_number for s in self._project.scenes
                if not s.is_detected and not s.source_ga_addresses
                and scene_group_key(s) == scene_group_key(probe)}
        number = next((n for n in range(1, 65) if n not in used), None)
        if number is None:
            QMessageBox.information(
                self, "Hinweis",
                "Auf dieser Szenen-Adresse sind bereits alle 64 Szenennummern belegt.")
            return None
        scene = Scene(name=name or f"Neue Szene {number}", scene_number=number,
                      scope=scope, scope_id=scope_id, actions=actions or [])
        self._project.scenes.append(scene)
        self._select_scene(scene)
        self._scene_name.setFocus()
        self._scene_name.selectAll()
        return scene

    def _add_scene_on_same_ga(self):
        """Legt eine weitere Szene auf der ausgewählten Szenen-Adresse an
        (nächste freie Nummer, gleicher Geltungsbereich). Ist die Adresse eine
        bestehende GA (erkannt oder selbst gebunden), wird die neue Szene an
        diese GA gebunden -- sonst teilt sie sich über den Geltungsbereich die
        generierte Szenenaufruf-GA."""
        group = self._get_selected_address()
        source = self._get_selected_scene() or (group.anchor_scene if group else None)
        if not self._project or not source:
            QMessageBox.information(
                self, "Hinweis", "Bitte zuerst die Szenen-Adresse oder eine ihrer "
                "Szenen auswählen."
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
        self._select_scene(scene)
        self._scene_name.setFocus()
        self._scene_name.selectAll()

    def _add_from_template(self):
        """Erstellt eine Szene aus einer Vorlage – auf der ausgewählten
        Szenen-Adresse bzw. zentral, wenn keine ausgewählt ist."""
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
        actions = [
            SceneAction(group_address=action_def.get("gewerk_category", ""),
                        value=action_def.get("action", ""))
            for action_def in template.get("actions", [])
        ]
        group = self._get_selected_address()
        anchor = group.anchor_scene if group and group.planned else None
        self._create_scene(anchor.scope if anchor else "central",
                           anchor.scope_id if anchor else "",
                           name=template["name"], actions=actions)

    def _detect_scenes(self):
        """Erkennt Szenen in importierten Gruppenadressen und übernimmt sie
        (FA-1808); ergänzt ausserdem echte Schaltwerte (Aktor-Seite, FA-1809),
        Ausloeser (Sensor-Seite: welche Taste sendet welche Szenennummer,
        FA-1810) und Szenennamen aus dem GA-Kommentar (FA-1810a)."""
        if not self._project:
            return

        added = detect_scenes(self._project)
        if added:
            self._project.scenes.extend(added)

        count_before_linking = len(self._project.scenes)
        linked = link_scene_values(self._project)
        triggers_linked = link_scene_triggers(self._project)
        names_linked = link_scene_names(self._project)
        new_numbered_scenes = self._project.scenes[count_before_linking:]

        if not added and not linked and not triggers_linked and not names_linked:
            QMessageBox.information(
                self, "Szenen erkennen",
                "Keine neuen Szenen oder Schaltwerte gefunden."
            )
            return

        if new_numbered_scenes:
            self._select_scene(new_numbered_scenes[0])
        elif added:
            self._select_scene(added[0])
        else:
            self._refresh_table()

        parts = []
        if added:
            parts.append(f"{len(added)} neue Szene(n) aus Gruppenadressen übernommen")
        if linked:
            parts.append(f"{linked} Aktion(en) aus Gerätedaten ergänzt")
        if triggers_linked:
            parts.append(f"{triggers_linked} Auslöser aus Tastenkonfiguration ergänzt")
        if names_linked:
            parts.append(f"{names_linked} Szene(n) nach GA-Kommentar benannt")
        if new_numbered_scenes:
            parts.append(
                f"{len(new_numbered_scenes)} Szene(n) auf geteilter Szenen-Adresse "
                f"angelegt (siehe Auswahl)"
            )
        QMessageBox.information(self, "Szenen erkennen", " – ".join(parts) + ".")

    # --- Entfernen ---

    def _remove_scene(self):
        """Entfernt die ausgewählte Szene bzw. alle Szenen der ausgewählten
        Szenen-Adresse."""
        if not self._project:
            return
        data = self._selected_data()
        if not data or data[0] not in ("scene", "address"):
            return
        if data[0] == "scene":
            scenes = [data[1]]
            question = f"Szene '{data[1].name}' wirklich entfernen?"
        else:
            scenes = data[1].all_scenes
            question = (f"Alle {len(scenes)} Szene(n) der Adresse "
                        f"'{data[1].designation}' entfernen? Die Gruppenadresse "
                        "selbst bleibt unverändert.")
        reply = QMessageBox.question(
            self, "Entfernen", question, QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for scene in scenes:
                if scene in self._project.scenes:
                    self._project.scenes.remove(scene)
            self._refresh_table(select=False)

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
            self._refresh_table(select=False)

    # --- Übernehmen ---

    def _apply_address_changes(self):
        """Setzt den Geltungsbereich für alle Szenen der ausgewählten Adresse."""
        group = self._get_selected_address()
        if group is None:
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
        if new_scope == "central":
            new_scope_id = ""
        for scene in group.all_scenes:
            scene.scope = new_scope
            scene.scope_id = new_scope_id
        self._refresh_table(select=group.scenes[0] if group.scenes else group.anchor_scene)

    def _apply_changes(self):
        """Übernimmt Änderungen an der ausgewählten Szene (Name, Nummer,
        Auslöser, bei selbst angelegten Szenen auch die Szenen-Adresse)."""
        scene = self._get_selected_scene()
        if not scene or self._overview is None:
            return

        target = self._overview.address_of(scene)
        target_key = self._scene_address.currentData()
        if self._scene_address.isEnabled() and target_key and (
                target is None or target_key != target.key):
            target = next((g for g in self._overview.addresses if g.key == target_key), target)

        number = self._scene_number.value()
        if target is not None and any(
                s is not scene and s.scene_number == number for s in target.scenes):
            QMessageBox.warning(
                self, "Szenennummer belegt",
                f"Auf dieser Szenen-Adresse ist die Nummer {number} bereits vergeben. "
                f"Nächste freie Nummer: {target.free_number() or '–'}.")
            return

        scene.name = self._scene_name.text()
        scene.scene_number = number
        scene.trigger = self._scene_trigger.text()
        if target is not None and self._scene_address.isEnabled():
            anchor = target.anchor_scene
            if anchor is not None and anchor is not scene:
                scene.scope, scene.scope_id = anchor.scope, anchor.scope_id
            scene.source_ga_addresses = [target.ga.address] if target.ga else []
        self._refresh_table(select=scene)

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
        self._refresh_table(select=scene)

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
            self._refresh_table(select=scene)
