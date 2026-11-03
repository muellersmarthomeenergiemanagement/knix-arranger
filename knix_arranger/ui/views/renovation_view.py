"""
Umbau-Varianten (Bestand & Umbau).

Alle geplanten Änderungen an einer bestehenden Anlage an einem Ort: je Linie
Teilnehmer, Busstrom und die gespeicherte Umbau-Variante (FA-609c), die
Erweiterungen im Bestand (FA-642) und die Geräte am Bus, die nicht im
ETS-Projekt stehen (FA-609b). Bearbeitet wird in
den bekannten Dialogen; die Topologie bleibt der Ist-Stand.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...services.bus_current import line_current, shared_catalog_or_none
from ...services.line_plan_service import evaluate, plan_for
from ...services.line_segments import segment_load
from ...services.report_sorting import physical_address_key
from ..column_utils import fit_columns
from ..styles import TEXT_MUTED

_RED, _ORANGE, _GREEN = "#C62828", "#E65100", "#2E7D32"


class RenovationView(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._bus = None
        layout = QVBoxLayout(self)
        title = QLabel("Umbau-Varianten")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Geplante Änderungen an der bestehenden Anlage. Eine Variante verändert die "
            "Topologie nicht: sie wird in der ETS umgesetzt und danach neu eingelesen.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        lines_box = QGroupBox("Linien")
        lines_layout = QVBoxLayout(lines_box)
        self._lines = QTableWidget(0, 5)
        self._lines.setHorizontalHeaderLabels(
            ["Linie", "Teilnehmer", "Busstrom", "Umbau-Variante", "Nach dem Umbau"])
        self._lines.verticalHeader().setVisible(False)
        self._lines.setEditTriggers(QTableWidget.NoEditTriggers)
        self._lines.setSelectionBehavior(QTableWidget.SelectRows)
        self._lines.setSelectionMode(QTableWidget.SingleSelection)
        self._lines.cellDoubleClicked.connect(lambda *_: self._plan())
        self._lines.itemSelectionChanged.connect(self._update_buttons)
        lines_layout.addWidget(self._lines)
        row = QHBoxLayout()
        self._plan_btn = QPushButton("Linie aufteilen / Umbau planen…")
        self._plan_btn.clicked.connect(self._plan)
        self._report_btn = QPushButton("Bericht Linienumbau…")
        self._report_btn.setObjectName("secondary")
        self._report_btn.clicked.connect(self._report)
        row.addWidget(self._plan_btn)
        row.addWidget(self._report_btn)
        row.addStretch()
        lines_layout.addLayout(row)
        layout.addWidget(lines_box, 2)

        ext_plans_box = QGroupBox("Erweiterungen")
        ext_plans_layout = QVBoxLayout(ext_plans_box)
        self._extensions = QTableWidget(0, 5)
        self._extensions.setHorizontalHeaderLabels(
            ["Erweiterung", "Erstellt", "Positionen", "Neue GAs", "Aktorkanäle"])
        self._extensions.verticalHeader().setVisible(False)
        self._extensions.setEditTriggers(QTableWidget.NoEditTriggers)
        self._extensions.setSelectionBehavior(QTableWidget.SelectRows)
        self._extensions.setSelectionMode(QTableWidget.SingleSelection)
        self._extensions.cellDoubleClicked.connect(lambda *_: self._edit_extension())
        self._extensions.itemSelectionChanged.connect(self._update_buttons)
        ext_plans_layout.addWidget(self._extensions)
        row = QHBoxLayout()
        new_btn = QPushButton("Erweiterung planen…")
        new_btn.clicked.connect(lambda: self._edit_extension(new=True))
        self._ext_edit_btn = QPushButton("Bearbeiten…")
        self._ext_edit_btn.setObjectName("secondary")
        self._ext_edit_btn.clicked.connect(lambda: self._edit_extension())
        self._ext_csv_btn = QPushButton("GA-Liste für die ETS…")
        self._ext_csv_btn.setObjectName("secondary")
        self._ext_csv_btn.clicked.connect(self._extension_csv)
        self._ext_report_btn = QPushButton("Bericht…")
        self._ext_report_btn.setObjectName("secondary")
        self._ext_report_btn.clicked.connect(self._extension_report)
        self._ext_delete_btn = QPushButton("Löschen")
        self._ext_delete_btn.setObjectName("secondary")
        self._ext_delete_btn.clicked.connect(self._delete_extension)
        for button in (new_btn, self._ext_edit_btn, self._ext_csv_btn, self._ext_report_btn,
                       self._ext_delete_btn):
            row.addWidget(button)
        row.addStretch()
        ext_plans_layout.addLayout(row)
        layout.addWidget(ext_plans_box, 2)

        ext_box = QGroupBox("Geräte am Bus, nicht im ETS-Projekt")
        ext_layout = QVBoxLayout(ext_box)
        self._external = QTableWidget(0, 4)
        self._external.setHorizontalHeaderLabels(["Adresse", "Bezeichnung", "Art", "Einbauort"])
        self._external.verticalHeader().setVisible(False)
        self._external.setEditTriggers(QTableWidget.NoEditTriggers)
        self._external.setSelectionBehavior(QTableWidget.SelectRows)
        self._external.cellDoubleClicked.connect(self._edit_external)
        ext_layout.addWidget(self._external)
        hint = QLabel("Erfassen: in der Topologie Rechtsklick auf die Linie → «Externes Gerät "
                      "erfassen…». Doppelklick bearbeitet.")
        hint.setStyleSheet(f"color: {TEXT_MUTED};")
        ext_layout.addWidget(hint)
        layout.addWidget(ext_box, 1)

    def set_bus(self, bus) -> None:
        self._bus = bus

    def set_project(self, project) -> None:
        self._project = project
        self._refresh()

    # ── Anzeige ──────────────────────────────────────────────────────────

    def _line_rows(self) -> list[tuple]:
        if self._project is None:
            return []
        rows = []
        for area in sorted(self._project.topology.areas, key=lambda a: a.area_number):
            for line in sorted(area.lines, key=lambda l: l.line_number):
                if line.devices:
                    rows.append((area, line))
        return rows

    def _refresh(self) -> None:
        catalog = shared_catalog_or_none()
        rows = self._line_rows()
        self._lines.setRowCount(len(rows))
        for r, (area, line) in enumerate(rows):
            key = f"{area.area_number}.{line.line_number}"
            load = segment_load(line)
            current = line_current(line, catalog)
            plan = plan_for(self._project, key)
            result = evaluate(self._project, plan, catalog) if plan else None
            cells = [
                (f"Linie {key}" + (f" {line.name}" if line.name and not
                                   line.name.lower().startswith("linie") else ""), None),
                (load.summary(), _RED if load.overloaded else _ORANGE if load.low_reserve
                 else None),
                (current.summary() if current.consumer_count else "–",
                 _RED if current.overloaded else _ORANGE if current.low_reserve else None),
                (self._plan_text(result) if result else "–", None),
                (self._after_text(result) if result else "",
                 None if not result else _GREEN if result.ok else _RED),
            ]
            for c, (text, color) in enumerate(cells):
                item = QTableWidgetItem(text)
                if color:
                    item.setForeground(QColor(color))
                if c == 0:
                    item.setData(Qt.UserRole, key)
                self._lines.setItem(r, c, item)
        fit_columns(self._lines)

        external = sorted((d for a in (self._project.topology.areas if self._project else [])
                           for l in a.lines for d in l.devices if d.external),
                          key=lambda d: physical_address_key(d.physical_address))
        self._external.setRowCount(len(external))
        for r, device in enumerate(external):
            for c, text in enumerate((device.physical_address, device.product,
                                      device.application_program or "–",
                                      device.installation_location or "–")):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(Qt.UserRole, device)
                self._external.setItem(r, c, item)
        fit_columns(self._external)

        from ...services.extension_service import evaluate as evaluate_extension
        plans = self._project.extension_plans if self._project else []
        self._extensions.setRowCount(len(plans))
        for r, plan in enumerate(plans):
            result = evaluate_extension(self._project, plan)
            missing = sum(result.new_actors().values())
            used = sum(a.channels for i in result.items for a in i.actors)
            cells = [plan.name, plan.created, str(len(plan.items)), str(len(result.gas)),
                     f"{used} auf vorhandenen Aktoren"
                     + (f", {missing} auf neuem Aktor" if missing else "")]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(Qt.UserRole, plan.id)
                if c == 4 and missing:
                    item.setForeground(QColor(_ORANGE))
                self._extensions.setItem(r, c, item)
        fit_columns(self._extensions)
        self._update_buttons()

    @staticmethod
    def _plan_text(result) -> str:
        new = next((p for p in result.parts if p.key == "new"), None)
        parts = []
        if new is not None:
            parts.append(f"{new.label.replace(' (neu)', '')}: {len(new.devices)} Geräte")
        main = next((p for p in result.parts if p.key == "main"), None)
        if main is not None:
            parts.append(f"Hauptlinie: {len(main.devices)}")
        if result.plan.main_line:
            parts.append(f"Linienkoppler {result.plan.source}.0")
        return " · ".join(parts) or "ohne Änderung"

    @staticmethod
    def _after_text(result) -> str:
        worst = max(result.parts, key=lambda p: p.worst)
        blocked = sum(1 for c in result.externals if c.blocked)
        text = f"höchstens {worst.worst * 100:.0f} % ({worst.label})"
        if blocked:
            text += f", {blocked} externe(s) Gerät(e) hinter Koppler"
        return text

    def _selected_key(self) -> str:
        row = self._lines.currentRow()
        item = self._lines.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else ""

    def _update_buttons(self) -> None:
        key = self._selected_key()
        has_plan = bool(key and self._project and plan_for(self._project, key))
        self._plan_btn.setEnabled(bool(key))
        self._plan_btn.setText("Umbau-Variante bearbeiten…" if has_plan
                               else "Linie aufteilen / Umbau planen…")
        self._report_btn.setEnabled(has_plan)
        has_extension = self._selected_extension() is not None
        for button in (self._ext_edit_btn, self._ext_csv_btn, self._ext_report_btn,
                       self._ext_delete_btn):
            button.setEnabled(has_extension)

    # ── Aktionen ─────────────────────────────────────────────────────────

    def _company(self):
        from ...services.project_service import ProjectService
        return ProjectService().load_company_profile()

    def _plan(self) -> None:
        key = self._selected_key()
        if not key:
            return
        from ..dialogs.line_plan_dialog import LinePlanDialog
        LinePlanDialog(self._project, key, self._bus, self._company(), self).exec()
        self._refresh()
        self.changed.emit()

    def _report(self) -> None:
        plan = plan_for(self._project, self._selected_key())
        if plan is None:
            return
        from ..dialogs.line_plan_dialog import save_line_plan_report
        save_line_plan_report(self, self._project, plan, self._company())

    # ── Erweiterungen ────────────────────────────────────────────────────

    def _selected_extension(self):
        row = self._extensions.currentRow()
        item = self._extensions.item(row, 0) if row >= 0 else None
        if item is None or self._project is None:
            return None
        return next((p for p in self._project.extension_plans
                     if p.id == item.data(Qt.UserRole)), None)

    def _store_extensions(self, description: str, plans: list) -> None:
        if self._bus:
            self._bus.begin_change(description)
        self._project.extension_plans = plans
        if self._bus:
            self._bus.any_change.emit("extension_plans")
        self._refresh()
        self.changed.emit()

    def _edit_extension(self, new: bool = False) -> None:
        if self._project is None:
            return
        plan = None if new else self._selected_extension()
        if not new and plan is None:
            return
        from ..dialogs.extension_dialog import ExtensionDialog
        dlg = ExtensionDialog(self._project, plan, self)
        if not dlg.exec():
            return
        old = self._project.extension_plans
        index = next((i for i, p in enumerate(old) if p.id == dlg.plan.id), len(old))
        plans = [p for p in old if p.id != dlg.plan.id]
        plans.insert(index, dlg.plan)
        self._store_extensions(f"Erweiterung {dlg.plan.name}", plans)

    def _delete_extension(self) -> None:
        plan = self._selected_extension()
        if plan is None:
            return
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Erweiterung löschen",
                                f"Erweiterung «{plan.name}» löschen?",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self._store_extensions(f"Erweiterung {plan.name} gelöscht",
                               [p for p in self._project.extension_plans if p is not plan])

    def _save_path(self, title: str, name: str, filter_text: str) -> str:
        import os
        from .. import license_gate
        folder = self._project.folder_path
        default = os.path.join(folder, "Berichte", name) if folder else name
        if folder:
            os.makedirs(os.path.join(folder, "Berichte"), exist_ok=True)
        path, _ = license_gate.get_save_file_name(self, title, default, filter_text)
        return path

    def _extension_csv(self) -> None:
        """Nur die neuen GAs als CSV zum Import in die ETS."""
        plan = self._selected_extension()
        if plan is None:
            return
        path = self._save_path("GA-Liste der Erweiterung speichern",
                               f"{self._project.name}_Erweiterung_{plan.name}.csv",
                               "CSV-Dateien (*.csv)")
        if not path:
            return
        from ...services.csv_export_service import CsvExportService
        from ...services.extension_service import evaluate as evaluate_extension
        from ...services.extension_service import new_ga_structure
        CsvExportService().export_csv(
            new_ga_structure(self._project, evaluate_extension(self._project, plan)), path,
            overwrite=True)

    def _extension_report(self) -> None:
        plan = self._selected_extension()
        if plan is None:
            return
        path = self._save_path("Bericht Erweiterung speichern",
                               f"{self._project.name}_Erweiterung_{plan.name}.pdf",
                               "PDF-Dateien (*.pdf)")
        if not path:
            return
        from ..dialogs.reports_dialog import open_report
        from ...services.report_service import ReportService
        ReportService(self._project, company_profile=self._company()).generate_extension_report(
            path, plan)
        open_report(path)

    def _edit_external(self, row: int, _column: int) -> None:
        device = self._external.item(row, 0).data(Qt.UserRole)
        area, line = next(((a, l) for a in self._project.topology.areas for l in a.lines
                           if device in l.devices), (None, None))
        if line is None:
            return
        from ..dialogs.external_device_dialog import ExternalDeviceDialog
        dlg = ExternalDeviceDialog(area.area_number, line, device, self)
        if not dlg.exec():
            return
        if self._bus:
            self._bus.begin_change(f"Externes Gerät {dlg.physical_address} bearbeitet")
        dlg.apply(device)
        if self._bus:
            self._bus.emit_topology_changed()
        self._refresh()
