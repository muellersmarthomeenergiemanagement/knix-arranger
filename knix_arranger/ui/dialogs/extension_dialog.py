"""
Erweiterung im Bestand erfassen (FA-642): Positionen (Raum, Gewerk, Anzahl,
Bezeichnung, Bedienung) und Namensschema; die Vorschau mit Adressen, Namen
und Aktorkanälen rechnet bei jeder Änderung neu (services/extension_service).
"""
from __future__ import annotations
import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...models.extension_plan import (
    NAMING_AUTO, NAMING_PLANT, NAMING_SWISS, ExtensionItem, ExtensionPlan,
)
from ...services.extension_service import evaluate
from ...services.report_sorting import floors_bottom_up

_NAMINGS = [(NAMING_AUTO, "Schema der Anlage, wo erkennbar, sonst KNX Swiss"),
            (NAMING_PLANT, "Schema der Anlage"),
            (NAMING_SWISS, "KNX Swiss")]
_OPERATIONS = ["", "vorhandener Taster", "neuer Taster", "Visualisierung", "Zentral / Automatik"]


class ExtensionDialog(QDialog):
    def __init__(self, project, plan: ExtensionPlan | None = None, parent=None):
        super().__init__(parent)
        self._project = project
        self._plan = copy.deepcopy(plan) if plan else ExtensionPlan()
        self._rooms = [(f"{floor.short_code or floor.name} · {room.number} {room.name}".strip(),
                        room.id)
                       for floor in floors_bottom_up(project.areal.all_floors)
                       for apt in floor.apartments for room in apt.rooms if room.number]
        used = {g.gewerk_code for g in project.group_addresses.all_addresses() if g.gewerk_code}
        gewerke = project.gewerk_catalog.all_gewerke()
        # Gewerke der Anlage zuerst
        self._gewerke = sorted(((g.code, f"{g.code} – {g.name}") for g in gewerke),
                               key=lambda c: (c[0] not in used, c[0]))
        self.setWindowTitle("Erweiterung bearbeiten" if plan else "Erweiterung planen")
        self.resize(1150, 760)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Neue Elemente in der bestehenden Anlage. KNiX schlägt Adressen in der "
            "Mittelgruppe vor, in der die Anlage das Gewerk auf dem Stockwerk führt, Namen "
            "nach ihrem Schema und freie Aktorkanäle. Die Erweiterung verändert das Projekt "
            "nicht; umgesetzt wird sie in der ETS.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self._name = QLineEdit(self._plan.name)
        self._name.setPlaceholderText("z.B. Storen OG")
        self._name.textChanged.connect(lambda *_: self._update())
        form.addRow("Name:", self._name)
        self._naming = QComboBox()
        for code, label in _NAMINGS:
            self._naming.addItem(label, code)
        self._naming.setCurrentIndex(max(self._naming.findData(self._plan.naming), 0))
        self._naming.currentIndexChanged.connect(lambda *_: self._update())
        form.addRow("Namen:", self._naming)
        layout.addLayout(form)

        splitter = QSplitter(Qt.Vertical)
        items_box = QWidget()
        items_layout = QVBoxLayout(items_box)
        items_layout.setContentsMargins(0, 0, 0, 0)
        self._items = QTableWidget(0, 5)
        self._items.setHorizontalHeaderLabels(["Raum", "Gewerk", "Anzahl", "Bezeichnung",
                                               "Bedienung"])
        self._items.verticalHeader().setVisible(False)
        for col, width in enumerate((280, 260, 70, 220, 170)):
            self._items.setColumnWidth(col, width)
        items_layout.addWidget(self._items)
        row = QHBoxLayout()
        add = QPushButton("+ Position")
        add.clicked.connect(lambda: self._add_row(ExtensionItem(count=1)))
        remove = QPushButton("Position entfernen")
        remove.setObjectName("secondary")
        remove.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        items_layout.addLayout(row)
        splitter.addWidget(items_box)

        preview_box = QWidget()
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = QTableWidget(0, 5)
        self._preview.setHorizontalHeaderLabels(["Adresse", "Bezeichnung", "DPT", "Namen",
                                                 "Position"])
        self._preview.verticalHeader().setVisible(False)
        self._preview.setEditTriggers(QTableWidget.NoEditTriggers)
        for col, width in enumerate((80, 460, 100, 90, 300)):
            self._preview.setColumnWidth(col, width)
        preview_layout.addWidget(self._preview)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(Qt.RichText)
        preview_layout.addWidget(self._summary)
        splitter.addWidget(preview_box)
        splitter.setSizes([260, 420])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._loading = True
        for item in self._plan.items:
            self._add_row(item)
        if not self._plan.items:
            self._add_row(ExtensionItem(count=1))
        self._loading = False
        self._update()

    # ── Positionen ───────────────────────────────────────────────────────

    def _combo(self, options: list[tuple[str, str]], value: str) -> QComboBox:
        combo = QComboBox()
        for data, label in options:
            combo.addItem(label, data)
        combo.setCurrentIndex(max(combo.findData(value), 0))
        combo.currentIndexChanged.connect(lambda *_: self._update())
        return combo

    def _add_row(self, item: ExtensionItem) -> None:
        r = self._items.rowCount()
        self._items.insertRow(r)
        self._items.setCellWidget(r, 0, self._combo([(rid, label) for label, rid in self._rooms],
                                                    item.room_id))
        self._items.setCellWidget(r, 1, self._combo(self._gewerke, item.gewerk_code))
        count = QSpinBox()
        count.setRange(1, 20)
        count.setValue(max(item.count, 1))
        count.valueChanged.connect(lambda *_: self._update())
        self._items.setCellWidget(r, 2, count)
        self._items.setItem(r, 3, QTableWidgetItem(item.label))
        operation = QComboBox()
        operation.setEditable(True)
        operation.addItems(_OPERATIONS)
        operation.setCurrentText(item.operation)
        operation.currentTextChanged.connect(lambda *_: self._update())
        self._items.setCellWidget(r, 4, operation)
        if not getattr(self, "_connected", False):
            self._items.itemChanged.connect(lambda *_: self._update())
            self._connected = True
        self._update()

    def _remove_row(self) -> None:
        row = self._items.currentRow()
        if row >= 0:
            self._items.removeRow(row)
            self._update()

    def _read(self) -> ExtensionPlan:
        plan = self._plan
        plan.name = self._name.text().strip()
        plan.naming = self._naming.currentData()
        plan.items = []
        for r in range(self._items.rowCount()):
            label_item = self._items.item(r, 3)
            plan.items.append(ExtensionItem(
                room_id=self._items.cellWidget(r, 0).currentData() or "",
                gewerk_code=self._items.cellWidget(r, 1).currentData() or "",
                count=self._items.cellWidget(r, 2).value(),
                label=label_item.text().strip() if label_item else "",
                operation=self._items.cellWidget(r, 4).currentText().strip()))
        return plan

    # ── Vorschau ─────────────────────────────────────────────────────────

    def _update(self) -> None:
        if getattr(self, "_loading", True):
            return
        result = evaluate(self._project, self._read())
        self._result = result
        gas = result.gas
        self._preview.setRowCount(len(gas))
        for r, ga in enumerate(gas):
            item = result.items[ga.item]
            position = (f"{item.room.name if item.room else '–'} – "
                        f"{item.item.label or (item.gewerk.name if item.gewerk else '')}")
            for c, text in enumerate((ga.address, ga.designation, ga.dpt, ga.naming, position)):
                cell = QTableWidgetItem(text)
                if c == 3 and ga.naming != "Anlage":
                    cell.setForeground(QColor("#1565C0"))
                self._preview.setItem(r, c, cell)
        lines = [f"<b>{len(gas)} neue GA(s)</b>"]
        for r in result.items:
            if not r.room:
                continue
            actors = ", ".join(f"{a.device.physical_address} {a.device.product} "
                               f"({a.channels} Kanal)" for a in r.actors)
            if r.missing_channels:
                actors = ", ".join(p for p in (actors, f"<span style='color:#C62828'>"
                                                       f"{r.missing_channels} Kanal/Kanäle auf "
                                                       "neuem Aktor</span>") if p)
            lines.append(f"{r.room.name} – {r.item.label or (r.gewerk.name if r.gewerk else '')}"
                         f": MG {r.middle_group or '–'}"
                         + (f", Vorlage {r.template}" if r.template else "")
                         + (f" · Aktor: {actors}" if actors else ""))
        lines += [f"<span style='color:#E65100'>{p}</span>" for p in result.problems]
        self._summary.setText("<br>".join(lines))

    def _accept(self) -> None:
        self._read()
        if not self._plan.name:
            self._plan.name = "Erweiterung"
        self.accept()

    @property
    def plan(self) -> ExtensionPlan:
        return self._plan
