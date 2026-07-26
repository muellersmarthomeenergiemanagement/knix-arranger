"""
Wizard Schritt 4: Topologie (HV/UV, Linienzuteilung) mit manueller Anpassung
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QGroupBox, QTextEdit,
    QLineEdit, QSpinBox, QFormLayout, QComboBox, QMessageBox,
    QDialog, QDialogButtonBox, QScrollArea, QCheckBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from ...models.project import KnxProject
from ...models.topology import Area, Line, Device
from ...services.topology_engine import TopologyEngine
from ..dialogs.topology_assignment_dialog import TopologyAssignmentDialog
from ..column_utils import fit_columns

# Farben konsistent mit topology_view.py (FA-1007)
_COLOR_COUPLER      = QColor("#1565C0")   # Dunkelblau: Koppler
_COLOR_POWER        = QColor("#2E7D32")   # Dunkelgrün: Speisegerät
_COLOR_ROOM         = QColor("#00838F")   # Dunkelcyan: Räume
_COLOR_ASSIGNED     = QColor("#1B5E20")   # Sehr dunkelgrün: Produkt zugewiesen
_COLOR_PLACEHOLDER  = QColor("#9E9E9E")   # Grau: Platzhalter
_COLOR_MANUAL       = QColor("#E65100")   # Orange: manuell hinzugefügtes Gerät
_COLOR_PROGRAMMED   = QColor("#4527A0")   # Violett: physikalisch programmiert (Adresse fixiert)


_DEVICE_TYPE_OPTIONS = [
    ("Sonstiges",  "other"),
    ("Aktor",      "actor"),
    ("Sensor",     "sensor"),
]


class _AddDeviceDialog(QDialog):
    """Dialog zum manuellen Hinzufügen eines Linienteilnehmers.

    Felder:
    - Bezeichnung (Pflicht)
    - Kategorie  (Aktor / Sensor / Sonstiges)
    - Teilnehmernummer (1–255, 0 = automatisch)
    - Einbauort  (Picker oder Freitext)
    """

    def __init__(
        self,
        location_options: list[tuple[str, str, str]],
        parent=None,
    ):
        """
        Args:
            location_options: Liste von (anzeigetext, installation_location, room_id).
                              Leer → Fallback auf freies Textfeld.
        """
        super().__init__(parent)
        self.setWindowTitle("Gerät manuell hinzufügen")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)

        self._name = QLineEdit()
        self._name.setPlaceholderText("z.B. Taster 4-fach, IP-Schnittstelle")
        layout.addRow("Bezeichnung *:", self._name)

        # Kategorie
        self._cat_combo = QComboBox()
        for label, _ in _DEVICE_TYPE_OPTIONS:
            self._cat_combo.addItem(label)
        layout.addRow("Kategorie:", self._cat_combo)

        # Teilnehmernummer (0 = automatisch vergeben)
        self._participant_spin = QSpinBox()
        self._participant_spin.setRange(0, 255)
        self._participant_spin.setValue(0)
        self._participant_spin.setSpecialValueText("Automatisch")
        self._participant_spin.setToolTip(
            "0 = automatisch vergeben.\n"
            "1–255 = gewünschte Teilnehmernummer auf der Linie."
        )
        layout.addRow("Teilnehmernr.:", self._participant_spin)

        # Einbauort
        self._has_options = bool(location_options)
        if self._has_options:
            self._loc_combo = QComboBox()
            self._loc_combo.addItem("— kein Einbauort —", ("", ""))

            vt_opts = [(l, v, r) for l, v, r in location_options if "/" not in l]
            rm_opts = [(l, v, r) for l, v, r in location_options if "/" in l]

            if vt_opts:
                self._loc_combo.insertSeparator(self._loc_combo.count())
                for label, loc_val, room_id in vt_opts:
                    self._loc_combo.addItem(label, (loc_val, room_id))
            if rm_opts:
                self._loc_combo.insertSeparator(self._loc_combo.count())
                for label, loc_val, room_id in rm_opts:
                    self._loc_combo.addItem(label, (loc_val, room_id))

            layout.addRow("Einbauort:", self._loc_combo)
        else:
            self._loc_text = QLineEdit()
            self._loc_text.setPlaceholderText("z.B. HV (optional)")
            layout.addRow("Einbauort:", self._loc_text)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _validate(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Pflichtfeld", "Bitte eine Bezeichnung eingeben.")
            return
        self.accept()

    @property
    def product_name(self) -> str:
        return self._name.text().strip()

    @property
    def device_type(self) -> str:
        """Interner device_type-String ('actor', 'sensor', 'other')."""
        idx = self._cat_combo.currentIndex()
        return _DEVICE_TYPE_OPTIONS[idx][1]

    @property
    def participant_number(self) -> int:
        """Gewünschte Teilnehmernummer (0 = auto)."""
        return self._participant_spin.value()

    @property
    def installation_location(self) -> str:
        if self._has_options:
            data = self._loc_combo.currentData()
            return data[0] if data else ""
        return self._loc_text.text().strip()

    @property
    def room_id(self) -> str:
        if self._has_options:
            data = self._loc_combo.currentData()
            return data[1] if data else ""
        return ""


class _AssignFunctionsDialog(QDialog):
    """Dialog zum manuellen Zuweisen von KNX-Funktionen (Gewerken) zu einem Gerät.

    Zeigt alle verfügbaren Gewerke als Checkboxen sowie eine spezielle Option
    für Szenensteuerung (SZ).  Vorhandene Zuweisungen werden vorausgewählt.
    """

    # Interner Code für Szenensteuerung (kein echtes Gewerk im Katalog)
    _SZ_CODE = "SZ"
    _SZ_NAME = "Szenensteuerung"

    def __init__(self, gewerk_catalog, current_functions: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Funktionen zuweisen")
        self.setMinimumWidth(400)
        self.setMinimumHeight(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Wählen Sie die Funktionen aus, die dieses Gerät bedienen soll:"
        ))

        # Scrollbarer Bereich mit Checkboxen
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        box_layout = QVBoxLayout(container)
        box_layout.setSpacing(2)

        self._checkboxes: dict[str, QCheckBox] = {}

        # Szenensteuerung immer als erste Option
        cb = QCheckBox(f"[{self._SZ_CODE}]  {self._SZ_NAME}")
        cb.setChecked(self._SZ_CODE in current_functions)
        cb.setStyleSheet("font-weight: bold;")
        box_layout.addWidget(cb)
        self._checkboxes[self._SZ_CODE] = cb

        # Trennlinie
        sep = QLabel()
        sep.setFixedHeight(8)
        box_layout.addWidget(sep)

        # Gewerke nach Kategorie gruppiert
        categories = {
            "licht": "Licht",
            "jalousie": "Jalousie / Beschattung",
            "heizung": "Heizung / Klima",
            "alarm": "Alarm / Sicherheit",
            "allgemein": "Allgemein",
        }
        all_gewerke = sorted(gewerk_catalog.all_gewerke(), key=lambda g: (g.category, g.name))
        current_cat = None
        for gewerk in all_gewerke:
            if gewerk.category != current_cat:
                current_cat = gewerk.category
                cat_label = QLabel(categories.get(current_cat, current_cat))
                cat_label.setStyleSheet("color: #555; font-style: italic; margin-top: 4px;")
                box_layout.addWidget(cat_label)

            cb = QCheckBox(f"[{gewerk.code}]  {gewerk.name}")
            cb.setChecked(gewerk.code in current_functions)
            box_layout.addWidget(cb)
            self._checkboxes[gewerk.code] = cb

        box_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    @property
    def selected_functions(self) -> list[str]:
        """Gibt die Liste der ausgewählten Gewerk-Codes zurück."""
        return [code for code, cb in self._checkboxes.items() if cb.isChecked()]


class Step04Topology(QWidget):
    """HV/UV definieren, Topologie berechnen und manuell anpassen."""

    AREA_ROLE = Qt.UserRole
    LINE_ROLE = Qt.UserRole + 1
    DEVICE_ROLE = Qt.UserRole + 2

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._current_device = None
        self._current_device_item = None

        layout = QVBoxLayout(self)

        info = QLabel(
            "Die Topologie wird automatisch berechnet basierend auf\n"
            "der Gebäudestruktur und den geplanten Geräten.\n"
            "Nach der Berechnung können Sie Bereiche und Linien manuell anpassen."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Änderungs-Banner (sichtbar wenn Räume nicht mehr zur Topologie passen)
        self._change_banner = QLabel()
        self._change_banner.setWordWrap(True)
        self._change_banner.setStyleSheet(
            "background: #FFF8E1; border: 1px solid #FFC107; "
            "border-radius: 4px; padding: 6px; color: #795548;"
        )
        self._change_banner.hide()
        layout.addWidget(self._change_banner)

        # Berechnen-Button
        calc_layout = QHBoxLayout()
        self._btn_calculate = QPushButton("Topologie berechnen")
        self._btn_calculate.clicked.connect(self._calculate)
        calc_layout.addWidget(self._btn_calculate)
        calc_layout.addStretch()
        layout.addLayout(calc_layout)

        # Hauptbereich: Baum links, Details rechts
        content = QHBoxLayout()

        # --- Linke Seite: Baum + Aktions-Buttons ---
        left = QVBoxLayout()
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels(["Element", "Adresse", "Geräte", "Einbauort", "Status"])
        self._tree.currentItemChanged.connect(self._on_selection)
        left.addWidget(self._tree)

        # Aktions-Buttons
        action_layout = QHBoxLayout()
        self._btn_add_area = QPushButton("+ Bereich")
        self._btn_add_area.clicked.connect(self._add_area)
        self._btn_add_line = QPushButton("+ Linie")
        self._btn_add_line.clicked.connect(self._add_line)
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("danger")
        self._btn_remove.clicked.connect(self._remove_selected)
        action_layout.addWidget(self._btn_add_area)
        action_layout.addWidget(self._btn_add_line)
        action_layout.addWidget(self._btn_remove)
        action_layout.addStretch()
        left.addLayout(action_layout)

        legend = QLabel(
            f"<span style='color:{_COLOR_COUPLER.name()};'>&#9679;</span> Koppler&nbsp;&nbsp;"
            f"<span style='color:{_COLOR_POWER.name()};'>&#9679;</span> Speisegerät&nbsp;&nbsp;"
            f"<span style='color:{_COLOR_ROOM.name()};'>&#9679;</span> Raum&nbsp;&nbsp;"
            f"<span style='color:{_COLOR_ASSIGNED.name()};'>&#9679;</span> Produkt zugewiesen&nbsp;&nbsp;"
            f"<span style='color:{_COLOR_PLACEHOLDER.name()};'>&#9679;</span> Platzhalter&nbsp;&nbsp;"
            f"<span style='color:{_COLOR_MANUAL.name()};'>&#9679;</span> manuell hinzugefügt&nbsp;&nbsp;"
            f"<span style='color:{_COLOR_PROGRAMMED.name()};'>&#9679;</span> programmiert (gesperrt)"
        )
        legend.setWordWrap(True)
        legend.setStyleSheet("font-size: 10px; color: #666;")
        left.addWidget(legend)

        content.addLayout(left, 2)

        # --- Rechte Seite: Detail-Panel ---
        right = QVBoxLayout()

        # Bereich-Details
        self._area_group = QGroupBox("Bereich-Details")
        area_form = QFormLayout()
        self._area_name = QLineEdit()
        area_form.addRow("Name:", self._area_name)
        self._area_number = QSpinBox()
        self._area_number.setRange(1, 15)
        area_form.addRow("Bereichsnr.:", self._area_number)
        self._area_backbone = QComboBox()
        self._area_backbone.addItems(["TP", "IP"])
        area_form.addRow("Backbone:", self._area_backbone)
        self._btn_apply_area = QPushButton("Übernehmen")
        self._btn_apply_area.clicked.connect(self._apply_area_changes)
        area_form.addRow("", self._btn_apply_area)
        self._area_group.setLayout(area_form)
        self._area_group.hide()
        right.addWidget(self._area_group)

        # Linien-Details
        self._line_group = QGroupBox("Linien-Details")
        line_form = QFormLayout()
        self._line_name = QLineEdit()
        line_form.addRow("Name:", self._line_name)
        self._line_number = QSpinBox()
        self._line_number.setRange(0, 15)
        line_form.addRow("Liniennr.:", self._line_number)
        self._line_devices = QSpinBox()
        self._line_devices.setRange(0, 256)
        line_form.addRow("Geräteanzahl:", self._line_devices)
        self._line_power_supply = QLabel("")
        self._line_power_supply.setStyleSheet("color: #808080;")
        line_form.addRow("Speisegerät:", self._line_power_supply)
        self._btn_apply_line = QPushButton("Übernehmen")
        self._btn_apply_line.clicked.connect(self._apply_line_changes)
        line_form.addRow("", self._btn_apply_line)
        self._btn_assign_rooms = QPushButton("Etagen / Räume zuordnen...")
        self._btn_assign_rooms.clicked.connect(self._open_assignment_dialog)
        line_form.addRow("", self._btn_assign_rooms)
        self._btn_add_device = QPushButton("+ Gerät hinzufügen\u2026")
        self._btn_add_device.clicked.connect(self._add_device_to_line)
        line_form.addRow("", self._btn_add_device)
        self._line_group.setLayout(line_form)
        self._line_group.hide()
        right.addWidget(self._line_group)

        # Gerät-Details
        self._device_group = QGroupBox("Gerät-Details")
        dev_form = QFormLayout()
        self._device_addr_lbl  = QLabel("")
        self._device_cat_lbl   = QLabel("")
        self._device_type_lbl  = QLabel("")
        self._device_mfr_lbl   = QLabel("")
        self._device_order_lbl = QLabel("")
        dev_form.addRow("Phys. Adresse:", self._device_addr_lbl)
        dev_form.addRow("Kategorie:",     self._device_cat_lbl)
        dev_form.addRow("Typ:",           self._device_type_lbl)
        dev_form.addRow("Hersteller:",    self._device_mfr_lbl)
        dev_form.addRow("Bestellnr.:",    self._device_order_lbl)
        self._device_functions_lbl = QLabel("")
        self._device_functions_lbl.setWordWrap(True)
        self._device_functions_lbl.setStyleSheet("color: #1565C0;")
        dev_form.addRow("Funktionen:", self._device_functions_lbl)
        self._btn_assign_functions = QPushButton("Funktionen zuweisen\u2026")
        self._btn_assign_functions.clicked.connect(self._assign_functions)
        dev_form.addRow("", self._btn_assign_functions)
        self._btn_assign_product = QPushButton("Produkt zuweisen\u2026")
        self._btn_assign_product.clicked.connect(self._assign_product)
        self._btn_clear_product = QPushButton("Zuweisung entfernen")
        self._btn_clear_product.clicked.connect(self._clear_product)
        self._btn_remove_device = QPushButton("Gerät entfernen")
        self._btn_remove_device.setObjectName("danger")
        self._btn_remove_device.clicked.connect(self._remove_device_from_line)
        dev_form.addRow("", self._btn_assign_product)
        dev_form.addRow("", self._btn_clear_product)
        dev_form.addRow("", self._btn_remove_device)
        self._device_group.setLayout(dev_form)
        self._device_group.hide()
        right.addWidget(self._device_group)

        right.addStretch()
        content.addLayout(right, 1)

        layout.addLayout(content)

        # Validierung
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText("Validierungsmeldungen...")
        layout.addWidget(self._log)

    def on_enter(self):
        if self._project.topology.areas:
            if self._project.topology.is_imported:
                # Importierte Topologie (XLSX / knxproj): immer nur anzeigen.
                # populate_devices() würde alle ETS-Geräte löschen (FA-ImportGuard).
                self._change_banner.hide()
                self._display_topology()
                return
            # Wizard-Topologie: Linienteilnehmer aus Gewerk-Zuweisungen ableiten
            # und anzeigen – NICHT neu berechnen.
            # preserve_manual=True: manuell zugewiesene Produkte bleiben erhalten.
            engine = TopologyEngine(self._project.config.topology_mode)
            engine.populate_devices(
                self._project.topology,
                self._project.all_rooms,
                self._project.gewerk_catalog,
                small_project=(self._project.topology.topology_mode == "TP-64"),
                preserve_manual=True,
            )
            self._update_change_banner()
            self._display_topology()
        else:
            # Noch keine Topologie: automatisch berechnen und anzeigen
            self._change_banner.hide()
            self._calculate()

    def _update_change_banner(self):
        """Prüft ob Räume hinzugekommen oder weggefallen sind und zeigt ggf. Banner."""
        topology = self._project.topology
        if not topology.areas:
            self._change_banner.hide()
            return

        # Alle Raum-IDs die aktuell in Linien eingetragen sind
        assigned_ids: set[str] = set()
        for area in topology.areas:
            for line in area.lines:
                assigned_ids.update(line.assigned_room_ids)

        # Alle Raum-IDs die im Projekt existieren
        existing_ids = {r.id for r in self._project.all_rooms}

        orphaned = assigned_ids - existing_ids   # in Linie, aber Raum gelöscht
        unassigned = existing_ids - assigned_ids  # im Projekt, aber in keiner Linie

        if not orphaned and not unassigned:
            self._change_banner.hide()
            return

        parts = []
        if unassigned:
            names = ", ".join(
                r.name for r in self._project.all_rooms if r.id in unassigned
            )
            parts.append(
                f"Neue Räume ohne Linienzuteilung: {names}"
            )
        if orphaned:
            parts.append(
                f"{len(orphaned)} Raum/Räume wurde(n) aus dem Projekt entfernt, "
                f"sind aber noch in einer Linie eingetragen."
            )

        self._change_banner.setText(
            "Hinweis: Die Gebäudestruktur hat sich seit der letzten Topologie-Berechnung "
            "geändert. Klicken Sie auf «Topologie berechnen», um die Linienzuteilung "
            "zu aktualisieren.\n\n" + "\n".join(f"• {p}" for p in parts)
        )
        self._change_banner.show()

    def _calculate(self):
        if self._project.topology.areas:
            # Gibt es programmierte Geräte, die durch die Neuberechnung
            # ihre Linie wechseln würden? → Konflikt-Check zuerst.
            has_programmed = any(
                d.is_programmed
                for area in self._project.topology.areas
                for line in area.lines
                for d in line.devices
                if d.device_type not in ("coupler", "power_supply")
            )
            if has_programmed:
                engine_check = TopologyEngine(self._project.config.topology_mode)
                conflicts = engine_check.check_topology_conflicts(
                    self._project.topology, self._project.areal
                )
                if conflicts:
                    lines = [
                        f"  • {c['device'].product or c['device'].device_type} "
                        f"({c['device'].physical_address})  –  {c['reason']}"
                        for c in conflicts[:10]
                    ]
                    more = f"\n  … und {len(conflicts) - 10} weitere" if len(conflicts) > 10 else ""
                    QMessageBox.critical(
                        self,
                        "Neuberechnung nicht möglich",
                        "Die Topologie kann nicht neu berechnet werden, weil folgende\n"
                        "programmierte Geräte ihre Linie wechseln würden:\n\n"
                        + "\n".join(lines) + more
                        + "\n\nHeben Sie zuerst die Programmierung der betroffenen\n"
                        "Geräte auf (Kontextmenü → «Programmierung aufheben»),\n"
                        "oder passen Sie die Gebäudestruktur manuell an.",
                    )
                    return

            answer = QMessageBox.question(
                self,
                "Topologie neu berechnen?",
                "Es ist bereits eine Topologie vorhanden.\n"
                "Eine Neuberechnung ersetzt die aktuelle Struktur "
                "(Bereiche, Linien, manuelle Anpassungen).\n\n"
                "Wirklich neu berechnen?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        engine = TopologyEngine(self._project.config.topology_mode)

        # Geräteschätzung aus Gewerk-Zuweisungen ableiten, bevor die Topologie
        # berechnet wird (planned_sensors / planned_actors werden nicht mehr
        # manuell in Schritt 3 gepflegt)
        engine.update_device_estimates(
            self._project.all_rooms, self._project.gewerk_catalog
        )

        self._project.topology = engine.calculate_topology(self._project.areal)

        # Aktoren und Sensoren aus Gewerk-Zuweisungen ableiten und Adressen vergeben
        engine.populate_devices(
            self._project.topology,
            self._project.all_rooms,
            self._project.gewerk_catalog,
            small_project=(self._project.topology.topology_mode == "TP-64"),
        )

        self._change_banner.hide()
        self._display_topology()
        self._run_validation()

    def _run_validation(self):
        engine = TopologyEngine(self._project.config.topology_mode)
        issues = engine.validate_topology(self._project.topology)
        cross_warnings = engine.validate_cross_line_functions(
            self._project.topology, self._project.all_rooms
        )

        self._log.clear()
        all_ok = not issues and not cross_warnings
        if all_ok:
            self._log.append("Topologie OK - Keine Probleme gefunden.")
        else:
            for issue in issues:
                level = issue["level"].upper()
                self._log.append(f"[{level}] {issue['rule']}: {issue['message']}")
            for w in cross_warnings:
                self._log.append(
                    f"[HINWEIS] T-CF: Sensor {w['sensor_addr']} ({w['room_name']}) "
                    f"referenziert Funktion «{w['fn_label']}» aus Linie {w['target_line']} – "
                    f"Linienkoppler muss GA durchlassen."
                )

    def _room_lookup(self) -> dict:
        """Erstellt ein Dict {room.id -> room} aus dem gesamten Projekt."""
        return {r.id: r for r in self._project.all_rooms}

    def _save_tree_state(self) -> tuple[set, set, str | None]:
        """Gibt (expanded_area_ids, expanded_line_ids, selected_device_id) zurück."""
        exp_areas: set[str] = set()
        exp_lines: set[str] = set()
        sel_id: str | None = None

        sel = self._tree.currentItem()
        if sel:
            dev = sel.data(0, self.DEVICE_ROLE)
            if dev:
                sel_id = dev.id
            else:
                line = sel.data(0, self.LINE_ROLE)
                if line:
                    sel_id = line.id
                else:
                    area = sel.data(0, self.AREA_ROLE)
                    if area:
                        sel_id = area.id

        root = self._tree.invisibleRootItem()
        for ai in range(root.childCount()):
            ai_item = root.child(ai)
            a = ai_item.data(0, self.AREA_ROLE)
            if a and ai_item.isExpanded():
                exp_areas.add(a.id)
            for li in range(ai_item.childCount()):
                li_item = ai_item.child(li)
                ln = li_item.data(0, self.LINE_ROLE)
                if ln and li_item.isExpanded():
                    exp_lines.add(ln.id)
        return exp_areas, exp_lines, sel_id

    def _restore_tree_state(
        self,
        exp_areas: set[str],
        exp_lines: set[str],
        sel_id: str | None,
    ) -> None:
        """Stellt Expand-Zustand und Selektion nach einem Rebuild wieder her."""
        root = self._tree.invisibleRootItem()
        for ai in range(root.childCount()):
            ai_item = root.child(ai)
            a = ai_item.data(0, self.AREA_ROLE)
            if a:
                ai_item.setExpanded((a.id in exp_areas) or not exp_areas)
                if sel_id and a.id == sel_id:
                    self._tree.setCurrentItem(ai_item)
            for li in range(ai_item.childCount()):
                li_item = ai_item.child(li)
                ln = li_item.data(0, self.LINE_ROLE)
                if ln:
                    li_item.setExpanded((ln.id in exp_lines) or not exp_lines)
                    if sel_id and ln.id == sel_id:
                        self._tree.setCurrentItem(li_item)
                    for di in range(li_item.childCount()):
                        di_item = li_item.child(di)
                        dev = di_item.data(0, self.DEVICE_ROLE)
                        if dev and sel_id and dev.id == sel_id:
                            self._tree.setCurrentItem(di_item)

    def _display_topology(self):
        exp_areas, exp_lines, sel_id = self._save_tree_state()
        vscroll = self._tree.verticalScrollBar().value()

        self._tree.setUpdatesEnabled(False)
        self._tree.clear()
        rooms_by_id = self._room_lookup()
        multi_area = len(self._project.topology.areas) > 1

        for area in self._project.topology.areas:
            area_item = QTreeWidgetItem(self._tree, [
                f"Bereich {area.area_number} - {area.name}",
                area.coupler_address,
                str(sum(l.device_count for l in area.lines)),
                "",
                f"{len(area.lines)} Linien, Backbone: {area.backbone_type}",
            ])
            area_item.setData(0, self.AREA_ROLE, area)
            # Expand-Zustand wird von _restore_tree_state gesetzt

            # FA-1007: Bereichskoppler (B.A.0.0) nur bei mehr als einem Bereich
            if multi_area:
                bk_device = next(
                    (d for d in (area.lines[0].devices if area.lines else [])
                     if d.device_type == "coupler" and d.product == "Bereichskoppler"),
                    None,
                )
                bk_location = bk_device.installation_location if bk_device else ""
                bk_status = "Verbindet Bereichslinie mit Backbone"
                if bk_device and bk_device.manufacturer:
                    bk_status = f"Zugewiesen: {bk_device.manufacturer}"
                    if bk_device.order_number:
                        bk_status += f" {bk_device.order_number}"
                bk_item = QTreeWidgetItem(area_item, [
                    "Bereichskoppler (BK)",
                    area.coupler_address,
                    "", bk_location,
                    bk_status,
                ])
                self._colorize(bk_item, _COLOR_COUPLER)

            # FA-1007: Speisegerät Bereichslinie (B.A.0.-) — nur bei mehreren Bereichen
            if area.backbone_power_supply is not None:
                sv_dev = area.backbone_power_supply
                sv_status = "Spannungsversorgung der Bereichslinie"
                if sv_dev.manufacturer:
                    sv_status = f"Zugewiesen: {sv_dev.manufacturer}"
                    if sv_dev.order_number:
                        sv_status += f" {sv_dev.order_number}"
                sv_area_item = QTreeWidgetItem(area_item, [
                    "Speisegerät Bereichslinie (SV)",
                    f"{area.area_number}.0.-",
                    "", sv_dev.installation_location,
                    sv_status,
                ])
                sv_area_item.setData(0, self.DEVICE_ROLE, sv_dev)
                self._colorize(sv_area_item, _COLOR_POWER)

            for line in area.lines:
                status = ""
                if line.device_count > 100:
                    status = " [ÜBERLAST!]"
                elif line.device_count > 85:
                    status = " [Warnung]"
                line_item = QTreeWidgetItem(area_item, [
                    f"Linie {line.line_number} - {line.name}{status}",
                    line.coupler_address,
                    str(line.device_count),
                    line.uv_location or "",
                    "",
                ])
                line_item.setData(0, self.LINE_ROLE, line)
                # Expand-Zustand wird von _restore_tree_state gesetzt

                # FA-1007: Linienkoppler (B.A.L.0) als eigenständiger Knoten
                if line.coupler_address:
                    lk_device = next(
                        (d for d in line.devices
                         if d.device_type == "coupler" and d.product == "Linienkoppler"),
                        None,
                    )
                    lk_location = lk_device.installation_location if lk_device else ""
                    lk_status = "Verbindet Linie mit Bereichslinie"
                    if lk_device and lk_device.manufacturer:
                        lk_status = f"Zugewiesen: {lk_device.manufacturer}"
                        if lk_device.order_number:
                            lk_status += f" {lk_device.order_number}"
                    lk_item = QTreeWidgetItem(line_item, [
                        "Linienkoppler (LK)",
                        line.coupler_address,
                        "", lk_location,
                        lk_status,
                    ])
                    self._colorize(lk_item, _COLOR_COUPLER)

                # FA-1007: Speisegerät Linie (B.A.L.-) — bei recommended_power_supply
                if line.recommended_power_supply:
                    sv_device = next(
                        (d for d in line.devices if d.device_type == "power_supply"),
                        None,
                    )
                    sv_location = sv_device.installation_location if sv_device else ""
                    sv_status = "Spannungsversorgung der Linie"
                    if sv_device and sv_device.manufacturer:
                        sv_status = f"Zugewiesen: {sv_device.manufacturer}"
                        if sv_device.order_number:
                            sv_status += f" {sv_device.order_number}"
                    sv_line_item = QTreeWidgetItem(line_item, [
                        "Speisegerät (SV)",
                        f"{area.area_number}.{line.line_number}.-",
                        "", sv_location,
                        sv_status,
                    ])
                    self._colorize(sv_line_item, _COLOR_POWER)

                # Zugeordnete Räume anzeigen
                for room_id in line.assigned_room_ids:
                    room = rooms_by_id.get(room_id)
                    if room:
                        room_item = QTreeWidgetItem(line_item, [
                            f"  {room.number}  {room.name}",
                            "",
                            str(room.total_devices()),
                            "",
                            "Raum",
                        ])
                        self._colorize(room_item, _COLOR_ROOM)

                # Linienteilnehmer (Aktoren / Sensoren / manuell hinzugefügte)
                for device in line.devices:
                    if device.device_type not in ("actor", "sensor", "other", "gateway"):
                        continue
                    if device.is_programmed:
                        mfr_suffix = f"  ({device.manufacturer})" if device.manufacturer else ""
                        dev_item = QTreeWidgetItem(line_item, [
                            f"  [P] {device.product}{mfr_suffix}",
                            device.physical_address,
                            "",
                            device.installation_location,
                            "Programmiert",
                        ])
                        dev_item.setData(0, self.DEVICE_ROLE, device)
                        self._colorize(dev_item, _COLOR_PROGRAMMED)
                    elif device.manually_added:
                        dev_item = QTreeWidgetItem(line_item, [
                            f"  {device.product}",
                            device.physical_address,
                            "",
                            device.installation_location,
                            "Manuell",
                        ])
                        dev_item.setData(0, self.DEVICE_ROLE, device)
                        self._colorize(dev_item, _COLOR_MANUAL)
                    else:
                        assigned = bool(device.manufacturer)
                        mfr_suffix = f"  ({device.manufacturer})" if assigned else ""
                        dev_item = QTreeWidgetItem(line_item, [
                            f"  {device.product}{mfr_suffix}",
                            device.physical_address,
                            "",
                            device.installation_location,
                            "Zugewiesen" if assigned else "Platzhalter",
                        ])
                        dev_item.setData(0, self.DEVICE_ROLE, device)
                        self._colorize(dev_item, _COLOR_ASSIGNED if assigned else _COLOR_PLACEHOLDER)

        fit_columns(self._tree)
        self._restore_tree_state(exp_areas, exp_lines, sel_id)
        self._tree.setUpdatesEnabled(True)
        self._tree.verticalScrollBar().setValue(vscroll)

    @staticmethod
    def _colorize(item: QTreeWidgetItem, color: QColor) -> None:
        """Setzt die Vordergrundfarbe aller Spalten eines Knotens."""
        for col in range(item.columnCount()):
            item.setForeground(col, color)

    # --- Selektion ---

    def _on_selection(self, current, previous):
        if not current:
            self._area_group.hide()
            self._line_group.hide()
            self._device_group.hide()
            self._current_device = None
            return

        device = current.data(0, self.DEVICE_ROLE)
        line   = current.data(0, self.LINE_ROLE)
        area   = current.data(0, self.AREA_ROLE)

        if device:
            # Linienteilnehmer ausgewählt
            self._area_group.hide()
            self._line_group.hide()
            self._device_group.show()
            self._current_device = device
            self._current_device_item = current
            self._device_addr_lbl.setText(device.physical_address)
            _cat_display = {
                "actor": "Aktor", "sensor": "Sensor",
                "other": "Sonstiges", "coupler": "Koppler",
                "power_supply": "Speisegerät",
            }
            self._device_cat_lbl.setText(
                _cat_display.get(device.device_type, device.device_type)
            )
            self._device_type_lbl.setText(device.product)
            self._device_mfr_lbl.setText(device.manufacturer or "–")
            self._device_order_lbl.setText(device.order_number or "–")
            self._device_functions_lbl.setText(
                self._format_functions(device.manual_functions)
            )
            # "Funktionen zuweisen" nur für Sensoren und manuell hinzugefügte Geräte
            self._btn_assign_functions.setVisible(
                device.device_type in ("sensor", "other") or device.manually_added
            )
            # "Gerät entfernen" nur für manuell hinzugefügte Geräte anzeigen
            self._btn_remove_device.setVisible(device.manually_added)
        elif line and not area:
            # Linie ausgewählt
            self._area_group.hide()
            self._device_group.hide()
            self._current_device = None
            self._line_group.show()
            self._line_name.setText(line.name)
            self._line_number.setValue(line.line_number)
            self._line_devices.setValue(line.device_count)
            # Speisegeraet-Adresse aus dem Parent-Bereich berechnen
            parent = current.parent()
            if parent:
                parent_area = parent.data(0, self.AREA_ROLE)
                if parent_area:
                    self._line_power_supply.setText(
                        f"{parent_area.area_number}.{line.line_number}.-"
                    )
            else:
                self._line_power_supply.setText(f"?.{line.line_number}.-")
        elif area:
            # Bereich ausgewählt
            self._line_group.hide()
            self._device_group.hide()
            self._current_device = None
            self._area_group.show()
            self._area_name.setText(area.name)
            self._area_number.setValue(area.area_number)
            idx = self._area_backbone.findText(area.backbone_type)
            if idx >= 0:
                self._area_backbone.setCurrentIndex(idx)
        else:
            # Infrastruktur-Knoten (LK, SV, Raum) – nichts anzeigen
            self._area_group.hide()
            self._line_group.hide()
            self._device_group.hide()
            self._current_device = None

    # --- Bereich-Aktionen ---

    def _apply_area_changes(self):
        item = self._tree.currentItem()
        if not item:
            return
        area = item.data(0, self.AREA_ROLE)
        if not area:
            return

        area.name = self._area_name.text()
        area.area_number = self._area_number.value()
        area.coupler_address = f"{area.area_number}.0.0"
        area.backbone_type = self._area_backbone.currentText()

        # Koppleradressen der Linien aktualisieren
        for line in area.lines:
            line.coupler_address = f"{area.area_number}.{line.line_number}.0"

        self._display_topology()
        self._run_validation()

    def _add_area(self):
        topology = self._project.topology
        next_num = max((a.area_number for a in topology.areas), default=0) + 1
        if next_num > 15:
            QMessageBox.warning(self, "Limit", "Maximal 15 Bereiche erlaubt (T-05).")
            return

        area = Area(
            area_number=next_num,
            name=f"Bereich {next_num}",
            coupler_address=f"{next_num}.0.0",
        )
        topology.areas.append(area)
        self._display_topology()
        self._run_validation()

    # --- Linien-Aktionen ---

    def _apply_line_changes(self):
        item = self._tree.currentItem()
        if not item:
            return
        line = item.data(0, self.LINE_ROLE)
        if not line:
            return

        line.name = self._line_name.text()
        line.line_number = self._line_number.value()
        line.device_count = self._line_devices.value()

        # Koppleraddresse aktualisieren: Bereichsnummer vom Parent holen
        parent = item.parent()
        if parent:
            area = parent.data(0, self.AREA_ROLE)
            if area:
                line.coupler_address = f"{area.area_number}.{line.line_number}.0"

        self._display_topology()
        self._run_validation()

    def _add_line(self):
        item = self._tree.currentItem()
        if not item:
            QMessageBox.information(
                self, "Hinweis",
                "Bitte wählen Sie einen Bereich oder eine Linie aus,\n"
                "um eine neue Linie hinzuzufügen."
            )
            return

        # Bereich ermitteln
        area = item.data(0, self.AREA_ROLE)
        if not area:
            # Linie ausgewählt -> Parent ist Bereich
            parent = item.parent()
            if parent:
                area = parent.data(0, self.AREA_ROLE)

        if not area:
            return

        if len(area.lines) >= 15:
            QMessageBox.warning(
                self, "Limit",
                f"Bereich {area.area_number}: Maximal 15 Linien erlaubt (T-04)."
            )
            return

        next_line_num = max((l.line_number for l in area.lines), default=0) + 1
        line = Line(
            line_number=next_line_num,
            name=f"Neue Linie {next_line_num}",
            coupler_address=f"{area.area_number}.{next_line_num}.0",
            device_count=0,
        )
        area.lines.append(line)
        self._display_topology()
        self._run_validation()

    def _open_assignment_dialog(self):
        """Oeffnet den Dialog zum manuellen Zuordnen von Etagen/Raeumen."""
        item = self._tree.currentItem()
        if not item:
            return
        line = item.data(0, self.LINE_ROLE)
        if not line:
            return

        dlg = TopologyAssignmentDialog(
            topology=self._project.topology,
            areal=self._project.areal,
            current_line=line,
            parent=self,
        )
        if dlg.exec():
            # Linienteilnehmer nach geänderter Raumzuweisung neu ableiten.
            # Importierte Topologien bleiben unverändert (FA-ImportGuard).
            if not self._project.topology.is_imported:
                engine = TopologyEngine(self._project.config.topology_mode)
                engine.populate_devices(
                    self._project.topology,
                    self._project.all_rooms,
                    self._project.gewerk_catalog,
                    small_project=(self._project.topology.topology_mode == "TP-64"),
                    preserve_manual=True,
                )
            self._display_topology()
            self._run_validation()

    # --- Hilfsmethoden ---

    def _format_functions(self, functions: list[str]) -> str:
        """Gibt zugewiesene Funktionen als lesbaren String zurück."""
        if not functions:
            return "–"
        catalog = self._project.gewerk_catalog
        parts = []
        for code in functions:
            if code == "SZ":
                parts.append("Szenen")
            else:
                g = catalog.get(code)
                parts.append(g.name if g else code)
        return ", ".join(parts)

    # --- Produktzuweisung ---

    def _assign_product(self):
        """Öffnet Produktkatalog und weist Hersteller-Produkt dem Gerät zu."""
        if not self._current_device:
            return

        from ..dialogs.product_select_dialog import ProductSelectDialog

        dlg = ProductSelectDialog(
            preferred_manufacturers=self._project.config.preferred_manufacturers,
            parent=self,
        )
        if not dlg.exec():
            return

        prod = dlg.selected_product
        if not prod:
            return

        device = self._current_device
        device.manufacturer = prod.manufacturer
        device.order_number = prod.order_number
        device.product_name = prod.product_name

        # Detail-Panel aktualisieren
        self._device_mfr_lbl.setText(device.manufacturer)
        self._device_order_lbl.setText(device.order_number)

        # Tree-Item aktualisieren
        if self._current_device_item:
            label = f"  {device.product}  ({device.manufacturer})"
            self._current_device_item.setText(0, label)
            self._current_device_item.setText(4, "Zugewiesen")
            self._colorize(self._current_device_item, _COLOR_ASSIGNED)

        self._update_material_entry(device)

    def _clear_product(self):
        """Entfernt die Produktzuweisung vom Gerät."""
        if not self._current_device:
            return

        device = self._current_device
        device.manufacturer = ""
        device.order_number = ""
        device.product_name = ""

        self._device_mfr_lbl.setText("–")
        self._device_order_lbl.setText("–")

        if self._current_device_item:
            self._current_device_item.setText(0, f"  {device.product}")
            self._current_device_item.setText(4, "Platzhalter")
            self._colorize(self._current_device_item, _COLOR_PLACEHOLDER)

        self._update_material_entry(device)

    def _assign_functions(self):
        """Öffnet den Funktionszuweisungs-Dialog für das ausgewählte Gerät."""
        if not self._current_device:
            return

        dlg = _AssignFunctionsDialog(
            gewerk_catalog=self._project.gewerk_catalog,
            current_functions=list(self._current_device.manual_functions),
            parent=self,
        )
        if not dlg.exec():
            return

        self._current_device.manual_functions = dlg.selected_functions
        self._device_functions_lbl.setText(
            self._format_functions(self._current_device.manual_functions)
        )

    def _update_material_entry(self, device) -> None:
        """Überträgt Produktzuweisung in den passenden Materiallisten-Eintrag."""
        if not device.physical_address:
            return
        for entry in self._project.material_list.entries:
            if (entry.source == "wizard_auto"
                    and device.physical_address in entry.physical_addresses):
                entry.manufacturer = device.manufacturer
                entry.order_number = device.order_number
                entry.product_name = device.product_name
                break

    # --- Manuelles Gerät hinzufügen / entfernen ---

    def _collect_location_options(self) -> list[tuple[str, str, str]]:
        """Gibt (label, installation_location, room_id) aus der Gebäudestruktur zurück.

        Zuerst alle Verteiler (HV, UV …), dann alle Räume – jeweils mit
        Etagen- und Wohnungspräfix.
        """
        options: list[tuple[str, str, str]] = []
        for building in self._project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    floor_label = floor.name or floor.short_code or "?"
                    for apartment in floor.apartments:
                        apt_label = apartment.name or ""
                        for room in apartment.rooms:
                            # Verteiler in diesem Raum
                            for vt in room.verteiler:
                                vt_name = vt.name or vt.verteiler_type
                                label = f"{vt_name} \u2013 {floor_label}"
                                if apt_label:
                                    label += f" / {apt_label}"
                                options.append((label, vt_name, room.id))
                            # Raum selbst
                            room_display = f"{room.number} {room.name}".strip()
                            path_parts = [p for p in [floor_label, apt_label, room_display] if p]
                            room_label = " / ".join(path_parts)
                            options.append((room_label, room_label, room.id))
        return options

    def _add_device_to_line(self):
        """Fügt ein manuell eingetragenes Gerät zur ausgewählten Linie hinzu."""
        item = self._tree.currentItem()
        if not item:
            return
        line = item.data(0, self.LINE_ROLE)
        if not line:
            return

        # Bereichsnummer aus Parent-Knoten ermitteln (für physikalische Adresse)
        parent_item = item.parent()
        area = (
            parent_item.data(0, self.AREA_ROLE)
            if parent_item else None
        ) or next(
            (a for a in self._project.topology.areas if line in a.lines), None
        )

        location_options = self._collect_location_options()
        dlg = _AddDeviceDialog(location_options, self)
        if not dlg.exec():
            return

        # Teilnehmernummer prüfen: Konflikt mit bestehenden Adressen?
        participant = dlg.participant_number
        if participant > 0 and area:
            wanted_addr = f"{area.area_number}.{line.line_number}.{participant}"
            conflict = any(
                d.physical_address == wanted_addr for d in line.devices
            )
            if conflict:
                QMessageBox.warning(
                    self,
                    "Adresskonflikt",
                    f"Die Teilnehmernummer {participant} "
                    f"(Adresse {wanted_addr}) ist auf dieser Linie bereits vergeben.\n"
                    "Bitte eine andere Nummer wählen oder '0' für automatische Vergabe."
                )
                return

        device = Device(
            device_type=dlg.device_type,
            product=dlg.product_name,
            installation_location=dlg.installation_location,
            room_id=dlg.room_id,
            manually_added=True,
        )

        # Feste Teilnehmernummer direkt setzen, damit sie bei der Auto-Vergabe übersprungen wird
        if participant > 0 and area:
            device.physical_address = (
                f"{area.area_number}.{line.line_number}.{participant}"
            )

        line.devices.append(device)
        line.update_device_count()

        # Physikalische Adressen neu vergeben (bereits gesetzte Adressen werden übersprungen)
        small_project = (self._project.topology.topology_mode == "TP-64")
        engine = TopologyEngine(self._project.config.topology_mode)
        engine.assign_physical_addresses(self._project.topology, small_project)

        self._display_topology()
        self._run_validation()

    def _remove_device_from_line(self):
        """Entfernt ein manuell hinzugefügtes Gerät aus seiner Linie."""
        if not self._current_device or not self._current_device.manually_added:
            return

        device = self._current_device
        for area in self._project.topology.areas:
            for line in area.lines:
                if device in line.devices:
                    line.devices.remove(device)
                    line.update_device_count()
                    break

        self._current_device = None
        self._current_device_item = None
        self._device_group.hide()
        self._display_topology()
        self._run_validation()

    # --- Entfernen ---

    def _remove_selected(self):
        item = self._tree.currentItem()
        if not item:
            return

        area = item.data(0, self.AREA_ROLE)
        line = item.data(0, self.LINE_ROLE)

        if line and not area:
            # Linie entfernen
            parent = item.parent()
            if parent:
                parent_area = parent.data(0, self.AREA_ROLE)
                if parent_area and line in parent_area.lines:
                    parent_area.lines.remove(line)
        elif area:
            # Bereich entfernen
            if area in self._project.topology.areas:
                self._project.topology.areas.remove(area)

        self._display_topology()
        self._run_validation()
        self._area_group.hide()
        self._line_group.hide()
