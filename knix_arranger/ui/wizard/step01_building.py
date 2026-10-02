"""
Wizard Schritt 1: Gebäudestruktur (Gebäude und Stockwerke anlegen)

Frei stehende Nebengebäude werden als eigenes Gebäude erfasst (Auswahl
oben, gilt auch für Schritt 2 und 3). Hauptgruppen sind im ganzen Areal
eindeutig (FA-411).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QLineEdit, QSpinBox, QFormLayout, QGroupBox,
    QListWidgetItem, QMessageBox, QInputDialog, QDialog,
    QDialogButtonBox, QComboBox,
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QBrush, QColor
from ...models.project import KnxProject
from ...models.building import Floor, Wing, STANDARD_FLOOR_NAMES, FLOOR_TO_MAIN_GROUP
from ...services.building_service import BuildingService
from ..styles import COLOR_WARNING
from .building_bar import BuildingBar, BuildingSelection


class Step01Building(QWidget):
    """Stockwerke des Gebäudes anlegen."""

    def __init__(self, project: KnxProject, parent=None,
                 selection: BuildingSelection | None = None):
        super().__init__(parent)
        self._project = project
        self._service = BuildingService()
        self._selection = selection or BuildingSelection(project)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Definieren Sie die Stockwerke Ihres Gebäudes. Frei stehende "
            "Nebengebäude (z.B. Einstellhalle) mit '+ Gebäude' separat anlegen – "
            "die Auswahl gilt auch für Zonen und Räume.\n"
            "Jedes Stockwerk erhält automatisch eine eigene Hauptgruppen-Nummer."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._building_bar = BuildingBar(project, self._selection, editable=True)
        self._building_bar.changed.connect(self._refresh_list)
        layout.addWidget(self._building_bar)

        content = QHBoxLayout()

        # Liste
        list_layout = QVBoxLayout()
        list_layout.addWidget(QLabel("Stockwerke:"))
        self._floor_list = QListWidget()
        self._floor_list.currentRowChanged.connect(self._on_selection_changed)
        self._floor_list.installEventFilter(self)
        list_layout.addWidget(self._floor_list)

        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("Hinzufügen")
        self._btn_add.clicked.connect(self._add_floor)
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("danger")
        self._btn_remove.setToolTip("Stockwerk entfernen (Entf)")
        self._btn_remove.clicked.connect(self._remove_floor)
        self._btn_up = QPushButton("Nach oben")
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down = QPushButton("Nach unten")
        self._btn_down.clicked.connect(self._move_down)
        self._btn_quick = QPushButton("Schnelleingabe...")
        self._btn_quick.setToolTip(
            "Mehrere Stockwerke auf einmal anlegen.\n"
            "Kürzel kommagetrennt eingeben, z.B.: KG, EG, 1.OG, 2.OG, DG"
        )
        self._btn_quick.clicked.connect(self._quick_add_floors)
        self._btn_template = QPushButton("Vorlage laden...")
        self._btn_template.setToolTip(
            "Gebäudestruktur aus einer vorgefertigten Vorlage laden\n"
            "(EFH, MFH, Chalet, Hotel, …)"
        )
        self._btn_template.clicked.connect(self._load_building_template)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_remove)
        btn_layout.addWidget(self._btn_up)
        btn_layout.addWidget(self._btn_down)
        btn_layout.addWidget(self._btn_quick)
        btn_layout.addWidget(self._btn_template)
        list_layout.addLayout(btn_layout)
        content.addLayout(list_layout, 2)

        # Details
        detail_group = QGroupBox("Stockwerk-Details")
        detail_form = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("z.B. Erdgeschoss")
        detail_form.addRow("Name:", self._name_edit)

        self._code_edit = QLineEdit()
        self._code_edit.setPlaceholderText("z.B. EG")
        self._code_edit.setMaxLength(4)
        detail_form.addRow("Kürzel:", self._code_edit)

        self._hg_spin = QSpinBox()
        self._hg_spin.setRange(1, 31)
        detail_form.addRow("Hauptgruppe:", self._hg_spin)

        self._btn_apply = QPushButton("Übernehmen")
        self._btn_apply.clicked.connect(self._apply_changes)
        self._name_edit.returnPressed.connect(self._apply_changes)
        self._code_edit.returnPressed.connect(self._apply_changes)
        detail_form.addRow("", self._btn_apply)

        detail_group.setLayout(detail_form)
        content.addWidget(detail_group, 1)

        layout.addLayout(content)

    def eventFilter(self, obj, event):
        if obj is self._floor_list and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Delete:
                self._remove_floor()
                return True
            if key == Qt.Key.Key_F2:
                self._name_edit.setFocus()
                self._name_edit.selectAll()
                return True
        return super().eventFilter(obj, event)

    def on_enter(self):
        self._building_bar.refresh()
        self._refresh_list()

    def on_leave(self):
        self._ensure_wing()

    def _ensure_wing(self):
        """Stellt sicher, dass Areal/Building/Wing existieren."""
        self._selection.wing()

    def _get_wing(self) -> Wing:
        return self._selection.wing()

    def _next_hg(self, preferred: int = -1, ignore: Floor | None = None) -> int:
        return BuildingService.next_free_main_group(self._project.areal, preferred, ignore)

    def _refresh_list(self):
        self._floor_list.clear()
        wing = self._get_wing()
        shared = BuildingService.shared_main_groups(self._project.areal)
        for floor in wing.floors:
            item = QListWidgetItem(f"HG {floor.main_group_number}: {floor.short_code} - {floor.name}")
            item.setData(Qt.UserRole, floor)
            others = [
                f"{b.name} {f.short_code}"
                for b, f in shared.get(floor.main_group_number, []) if f is not floor
            ]
            if others:
                item.setForeground(QBrush(QColor(COLOR_WARNING)))
                item.setToolTip(
                    f"HG {floor.main_group_number} ist auch vergeben an: "
                    + ", ".join(others)
                )
            self._floor_list.addItem(item)

    def _add_floor(self):
        wing = self._get_wing()
        n = len(wing.floors) + 1
        floor = Floor(name=f"Stockwerk {n}", short_code=f"S{n}",
                      main_group_number=self._next_hg(n))
        wing.floors.append(floor)
        self._refresh_list()

    def _remove_floor(self):
        row = self._floor_list.currentRow()
        if row < 0:
            return
        wing = self._get_wing()
        floor = wing.floors[row]
        reply = QMessageBox.question(
            self,
            "Stockwerk entfernen",
            f'Stockwerk "{floor.name}" wirklich entfernen?\n'
            "Alle darin definierten Räume und Zonen gehen verloren.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        wing.floors.pop(row)
        self._refresh_list()

    def _move_up(self):
        row = self._floor_list.currentRow()
        if row <= 0:
            return
        wing = self._get_wing()
        wing.floors[row], wing.floors[row - 1] = wing.floors[row - 1], wing.floors[row]
        self._refresh_list()
        self._floor_list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self._floor_list.currentRow()
        wing = self._get_wing()
        if row < 0 or row >= len(wing.floors) - 1:
            return
        wing.floors[row], wing.floors[row + 1] = wing.floors[row + 1], wing.floors[row]
        self._refresh_list()
        self._floor_list.setCurrentRow(row + 1)

    def _on_selection_changed(self, row: int):
        if row < 0:
            return
        item = self._floor_list.item(row)
        floor = item.data(Qt.UserRole)
        self._name_edit.setText(floor.name)
        self._code_edit.setText(floor.short_code)
        self._hg_spin.setValue(floor.main_group_number)

    def _quick_add_floors(self):
        """Schnelleingabe: mehrere Stockwerke auf einmal anlegen (FA-3201)."""
        text, ok = QInputDialog.getText(
            self, "Schnelleingabe Stockwerke",
            "Kürzel kommagetrennt eingeben (z.B. KG, EG, 1.OG, 2.OG, DG):",
            text="EG, 1.OG",
        )
        if not ok or not text.strip():
            return

        wing = self._get_wing()
        existing_codes = {f.short_code for f in wing.floors}
        codes = [c.strip() for c in text.split(",") if c.strip()]

        added = 0
        for code in codes:
            if code in existing_codes:
                continue
            name = STANDARD_FLOOR_NAMES.get(code, f"Stockwerk {code}")
            hg = self._next_hg(FLOOR_TO_MAIN_GROUP.get(code, len(wing.floors) + 1))
            wing.floors.append(Floor(name=name, short_code=code, main_group_number=hg))
            existing_codes.add(code)
            added += 1

        self._refresh_list()
        if added:
            self._floor_list.setCurrentRow(self._floor_list.count() - 1)

    def _load_building_template(self):
        """Gebäudestruktur aus Vorlage laden (FA-3210)."""
        templates = self._service.list_templates()
        if not templates:
            QMessageBox.information(self, "Keine Vorlagen", "Keine Gebäudevorlagen gefunden.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Gebäudevorlage laden")
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.addWidget(QLabel("Vorlage auswählen:"))
        combo = QComboBox()
        for tid, name, desc in templates:
            combo.addItem(name, tid)
            combo.setItemData(combo.count() - 1, desc, Qt.ToolTipRole)
        dlg_layout.addWidget(combo)
        self._template_desc = QLabel()
        self._template_desc.setWordWrap(True)
        self._template_desc.setStyleSheet("color: #555; font-style: italic;")
        dlg_layout.addWidget(self._template_desc)

        def _update_desc(idx):
            _, _, desc = templates[idx]
            self._template_desc.setText(desc)
        combo.currentIndexChanged.connect(_update_desc)
        _update_desc(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg_layout.addWidget(buttons)

        if dlg.exec() != QDialog.Accepted:
            return

        template_id = combo.currentData()
        if not template_id:
            return

        wing = self._get_wing()
        if wing.floors:
            reply = QMessageBox.question(
                self, "Vorhandene Stockwerke ersetzen?",
                f"Das Gebäude hat bereits {len(wing.floors)} Stockwerk(e).\n"
                "Diese werden durch die Vorlage ersetzt. Fortfahren?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        areal = self._service.load_template(template_id)
        if not areal:
            QMessageBox.warning(self, "Fehler", "Vorlage konnte nicht geladen werden.")
            return

        # Stockwerke aus Vorlage übernehmen (Gebäude/Wing aus Vorlage)
        new_wing = areal.buildings[0].wings[0] if areal.buildings else None
        if not new_wing:
            return

        # Vorhandene Gebäude-Metadaten behalten, nur Stockwerke ersetzen
        wing.floors = new_wing.floors
        # HG der Vorlage nur behalten, wenn kein anderes Gebäude sie belegt
        for floor in wing.floors:
            floor.main_group_number = self._next_hg(floor.main_group_number, ignore=floor)
        # Wohnungen/Räume aus Vorlage ebenfalls übernehmen
        self._refresh_list()

    def _apply_changes(self):
        row = self._floor_list.currentRow()
        if row < 0:
            return
        wing = self._get_wing()
        floor = wing.floors[row]
        floor.name = self._name_edit.text()
        floor.short_code = self._code_edit.text()
        floor.main_group_number = self._hg_spin.value()
        self._refresh_list()
        self._floor_list.setCurrentRow(row)
        item = self._floor_list.item(row)
        if item and item.toolTip():
            QMessageBox.warning(
                self, "Hauptgruppe mehrfach vergeben",
                item.toolTip() + "\n\nDie Adressen beider Stockwerke landen in "
                "derselben Hauptgruppe. Nächste freie HG: "
                f"{self._next_hg(ignore=floor)}.",
            )
