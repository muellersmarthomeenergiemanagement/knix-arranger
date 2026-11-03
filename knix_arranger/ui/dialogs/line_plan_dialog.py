"""
Linie aufteilen / Umbau planen (FA-609c).

Je Gerät das Ziel wählen (bleibt, neue Linie bzw. neues Segment, Hauptlinie),
gruppiert nach Stockwerk und Einbauort; das Ergebnis -- Teilnehmer und
Busstrom je Teil, neue Hardware, Umadressierung, Filtertabellen und die
Prüfung externer Geräte -- rechnet bei jeder Änderung neu
(services/line_plan_service). Die Variante wird im Projekt gespeichert und
verändert die Topologie nicht.
"""
from __future__ import annotations
import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...models.line_plan import TARGET_MAIN, TARGET_NEW, LinePlan
from ...services.bus_current import device_current, shared_catalog_or_none
from ...services.line_plan_service import (
    SOURCE, device_groups, evaluate, find_line, free_line_number, has_coupler, plan_for,
)

_STATUS_COLOR = {"ok": "#2E7D32", "knapp": "#E65100", "überlastet": "#C62828"}
_MIXED = "mixed"


class LinePlanDialog(QDialog):
    def __init__(self, project, line_key: str, bus=None, company_profile=None, parent=None):
        super().__init__(parent)
        self._project = project
        self._bus = bus
        self._company = company_profile
        self._area, self._line = find_line(project, line_key)
        saved = plan_for(project, line_key)
        self._plan = copy.deepcopy(saved) if saved else LinePlan(
            source=line_key, new_line=free_line_number(self._area),
            main_line=not has_coupler(self._area, self._line))
        self._catalog = shared_catalog_or_none()
        self._updating = False
        self._combos: list[tuple[QTreeWidgetItem, QComboBox]] = []

        self.setWindowTitle(f"Linie {line_key} aufteilen / Umbau planen")
        self.resize(1100, 760)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Je Gerät das Ziel wählen – für ein Stockwerk oder einen Einbauort gilt die "
            "Auswahl für alle Geräte darunter. Die Variante wird im Projekt gespeichert, "
            "die Topologie bleibt unverändert, bis der Umbau in der ETS umgesetzt und neu "
            "eingelesen ist.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addLayout(self._build_options())

        splitter = QSplitter(Qt.Vertical)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Gerät", "Adresse", "mA", "Ziel"])
        self._tree.setColumnWidth(0, 420)
        self._tree.setColumnWidth(1, 80)
        self._tree.setColumnWidth(2, 50)
        splitter.addWidget(self._tree)
        splitter.addWidget(self._build_result())
        splitter.setSizes([430, 300])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox()
        self._report_btn = buttons.addButton("Bericht erstellen…", QDialogButtonBox.ActionRole)
        self._discard_btn = buttons.addButton("Variante verwerfen", QDialogButtonBox.ResetRole)
        buttons.addButton("Speichern", QDialogButtonBox.AcceptRole)
        buttons.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        self._report_btn.clicked.connect(self._report)
        self._discard_btn.clicked.connect(self._discard)
        self._discard_btn.setEnabled(saved is not None)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._fill_tree()
        self._update()

    # ── Aufbau ───────────────────────────────────────────────────────────

    def _build_options(self) -> QVBoxLayout:
        a, l = self._area.area_number, self._line.line_number
        box = QVBoxLayout()
        row = QHBoxLayout()
        self._mode_line = QRadioButton("Neue Linie mit Linienkoppler")
        self._mode_segment = QRadioButton("Neues Segment mit Linienverstärker (Adressen bleiben)")
        group = QButtonGroup(self)
        group.addButton(self._mode_line)
        group.addButton(self._mode_segment)
        (self._mode_segment if self._plan.mode == "segment" else self._mode_line).setChecked(True)
        self._new_line = QSpinBox()
        self._new_line.setRange(1, 15)
        self._new_line.setPrefix(f"Linie {a}.")
        self._new_line.setValue(self._plan.new_line or free_line_number(self._area) or 1)
        self._new_name = QLineEdit(self._plan.new_name)
        self._new_name.setPlaceholderText("Name, z.B. OG + DG")
        row.addWidget(self._mode_line)
        row.addWidget(self._new_line)
        row.addWidget(self._new_name)
        row.addSpacing(20)
        row.addWidget(self._mode_segment)
        row.addStretch()
        box.addLayout(row)

        self._main_line = QCheckBox(
            f"Linienkoppler {a}.{l}.0 einbauen – die Linie hängt heute direkt an der "
            f"Hauptlinie; danach können Geräte wie die Schnittstelle einer Visualisierung "
            f"auf die Hauptlinie {a}.0")
        self._main_line.setChecked(self._plan.main_line)
        self._main_line.setVisible(not has_coupler(self._area, self._line))
        box.addWidget(self._main_line)

        for widget in (self._mode_line, self._mode_segment, self._main_line):
            widget.toggled.connect(lambda *_: self._update())
        self._new_line.valueChanged.connect(lambda *_: self._update())
        self._new_name.textChanged.connect(lambda *_: self._update())
        return box

    def _build_result(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self._parts = QTableWidget(0, 5)
        self._parts.setHorizontalHeaderLabels(
            ["Teil", "Teilnehmer", "Busstrom", "Neu", "Beurteilung"])
        self._parts.verticalHeader().setVisible(False)
        self._parts.setEditTriggers(QTableWidget.NoEditTriggers)
        for col, width in enumerate((260, 110, 180, 260, 100)):
            self._parts.setColumnWidth(col, width)
        layout.addWidget(self._parts)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(Qt.RichText)
        layout.addWidget(self._summary)
        return widget

    def _target_combo(self, value: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem(f"bleibt in Linie {self._plan.source}", SOURCE)
        combo.addItem("neue Linie / neues Segment", TARGET_NEW)
        combo.addItem("Hauptlinie", TARGET_MAIN)
        if value == _MIXED:
            combo.addItem("gemischt", _MIXED)
        combo.setCurrentIndex(max(combo.findData(value), 0))
        return combo

    def _fill_tree(self) -> None:
        self._tree.clear()
        self._combos.clear()
        for floor, locations in device_groups(self._project, self._line):
            floor_item = QTreeWidgetItem(self._tree, [floor])
            self._attach(floor_item)
            for location, devices in locations:
                loc_item = QTreeWidgetItem(floor_item, [location])
                self._attach(loc_item)
                for device in devices:
                    current, from_data = device_current(device, self._catalog)
                    name = device.product or device.device_type
                    if device.external:
                        name += " (nicht im ETS-Projekt)"
                    item = QTreeWidgetItem(loc_item, [
                        name, device.physical_address,
                        f"{current:g}" if from_data else f"({current:g})"])
                    item.setData(0, Qt.UserRole, device)
                    item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                    self._attach(item)
            floor_item.setExpanded(True)
        self._sync_combos()

    def _attach(self, item: QTreeWidgetItem) -> None:
        device = item.data(0, Qt.UserRole)
        combo = self._target_combo(self._plan.targets.get(device.id, SOURCE) if device
                                   else SOURCE)
        combo.currentIndexChanged.connect(lambda _i, it=item, c=combo: self._changed(it, c))
        self._tree.setItemWidget(item, 3, combo)
        self._combos.append((item, combo))

    # ── Änderungen ───────────────────────────────────────────────────────

    def _devices_below(self, item: QTreeWidgetItem) -> list:
        device = item.data(0, Qt.UserRole)
        if device is not None:
            return [device]
        return [d for i in range(item.childCount()) for d in self._devices_below(item.child(i))]

    def _changed(self, item: QTreeWidgetItem, combo: QComboBox) -> None:
        if self._updating:
            return
        value = combo.currentData()
        if value == _MIXED:
            return
        for device in self._devices_below(item):
            if value == SOURCE:
                self._plan.targets.pop(device.id, None)
            else:
                self._plan.targets[device.id] = value
        if value == TARGET_MAIN and not self._main_line.isHidden():
            self._main_line.setChecked(True)
        self._sync_combos()
        self._update()

    def _sync_combos(self) -> None:
        self._updating = True
        try:
            for item, combo in self._combos:
                values = {self._plan.targets.get(d.id, SOURCE) for d in self._devices_below(item)}
                value = values.pop() if len(values) == 1 else _MIXED
                if value == _MIXED and combo.findData(_MIXED) < 0:
                    combo.addItem("gemischt", _MIXED)
                elif value != _MIXED and combo.findData(_MIXED) >= 0:
                    combo.removeItem(combo.findData(_MIXED))
                combo.setCurrentIndex(combo.findData(value))
        finally:
            self._updating = False

    def _read_options(self) -> None:
        self._plan.mode = "segment" if self._mode_segment.isChecked() else "line"
        self._plan.new_line = self._new_line.value()
        self._plan.new_name = self._new_name.text().strip()
        self._plan.main_line = not self._main_line.isHidden() and self._main_line.isChecked()
        self._new_line.setEnabled(self._plan.mode == "line")
        self._new_name.setEnabled(self._plan.mode == "line")

    def _update(self) -> None:
        self._read_options()
        result = evaluate(self._project, self._plan, self._catalog)
        self._result = result
        rows = [result.before] + result.parts
        self._parts.setRowCount(len(rows))
        for r, part in enumerate(rows):
            label = "Heute: " + part.label if r == 0 else part.label
            current = (f"{part.current_ma:.0f} / {part.supply_ma} mA "
                       f"({part.load * 100:.0f} %)" if part.load is not None
                       else f"{part.current_ma:.0f} mA")
            new = ", ".join(part.added + (["Spannungsversorgung"] if part.new_supply else []))
            cells = [label, f"{part.count} / {part.capacity}", current, new or "–", part.status]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c == 4:
                    cell.setForeground(QColor(_STATUS_COLOR[part.status]))
                self._parts.setItem(r, c, cell)
        self._summary.setText(self._summary_html(result))

    @staticmethod
    def _summary_html(result) -> str:
        lines = []
        if result.readdress:
            lines.append(f"<b>Umadressierung:</b> {len(result.readdress)} Gerät(e) erhalten eine "
                         "neue physikalische Adresse (Liste im Bericht).")
        if result.crossing:
            lines.append(f"<b>Zwischen den Linien:</b> {result.crossing} GA(s) sind in beiden "
                         "Linien verknüpft und laufen künftig über die Koppler.")
        tables = ", ".join(f"{f.coupler}: {f.ga_count} GAs{' (neu)' if f.new else ''}"
                           for f in result.filters if f.new or f.changed)
        if tables:
            lines.append(f"<b>Filtertabellen neu laden:</b> {tables}")
        for check in result.externals:
            name = check.device.product or check.device.physical_address
            if check.blocked:
                measured = (f" Laut Busmonitor sendet es auf {len(check.confirmed)} davon."
                            if check.confirmed else "")
                lines.append(
                    f"<span style='color:#C62828'><b>{name}:</b> in {check.where} hinter dem "
                    f"Koppler – erreicht {len(check.blocked)} GA(s) nicht, die nur in anderen "
                    f"Linien verknüpft sind.{measured} Auf die Hauptlinie setzen oder einen "
                    "Dummy mit diesen GAs verknüpfen.</span>")
            else:
                lines.append(f"<span style='color:#2E7D32'><b>{name}:</b> in {check.where} – "
                             "erreicht alle verknüpften GAs, kein Dummy nötig.</span>")
        lines += result.hints
        return "<br>".join(lines)

    # ── Speichern, Bericht ───────────────────────────────────────────────

    def _store(self) -> None:
        if self._bus:
            self._bus.begin_change(f"Umbau-Variante Linie {self._plan.source}")
        self._project.line_plans = [p for p in self._project.line_plans
                                    if p.source != self._plan.source] + [copy.deepcopy(self._plan)]
        if self._bus:
            self._bus.any_change.emit("line_plan")
        self._discard_btn.setEnabled(True)

    def _save(self) -> None:
        self._store()
        self.accept()

    def _discard(self) -> None:
        if self._bus:
            self._bus.begin_change(f"Umbau-Variante Linie {self._plan.source} verworfen")
        self._project.line_plans = [p for p in self._project.line_plans
                                    if p.source != self._plan.source]
        if self._bus:
            self._bus.any_change.emit("line_plan")
        self.reject()

    def _report(self) -> None:
        save_line_plan_report(self, self._project, self._plan, self._company,
                              before_write=self._store)


def save_line_plan_report(parent, project, plan, company_profile=None,
                          before_write=None) -> str:
    """Bericht Linienumbau speichern und öffnen; gibt den Pfad zurück
    ("" = abgebrochen). Vorschlag im Ordner Berichte des Projekts."""
    import os
    from .. import license_gate
    from .reports_dialog import open_report
    folder = project.folder_path
    name = f"{project.name}_Linienumbau_{plan.source.replace('.', '_')}.pdf"
    default = os.path.join(folder, "Berichte", name) if folder else name
    if folder:
        os.makedirs(os.path.join(folder, "Berichte"), exist_ok=True)
    path, _ = license_gate.get_save_file_name(
        parent, "Bericht Linienumbau speichern", default, "PDF-Dateien (*.pdf)")
    if not path:
        return ""
    if before_write is not None:
        before_write()
    from ...services.report_service import ReportService
    ReportService(project, company_profile=company_profile).generate_line_plan_report(path, plan)
    open_report(path)
    return path
