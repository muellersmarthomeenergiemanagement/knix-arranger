"""
Busanalyse (FA-640): Busmonitor-Mitschnitt der ETS einlesen und gegen das
Projekt auswerten -- Absender, unbekannte und externe Geräte, Wiederholungen,
Lastspitzen, häufig sendende Geräte (services/bus_monitor).
"""
from __future__ import annotations
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...services.bus_monitor import BusLogError, analyze, parse_log, summarize
from ..column_utils import fit_columns
from ..styles import TEXT_MUTED

_LEVEL = {"error": ("Fehler", "#C62828"), "warning": ("Warnung", "#E65100"),
          "info": ("Hinweis", "#1565C0")}


class BusAnalysisView(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._bus = None
        self._analysis = None
        layout = QVBoxLayout(self)
        title = QLabel("Busanalyse")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Mitschnitt aus dem Bus- oder Gruppenmonitor der ETS (XML) einlesen. KNiX "
            "gleicht die Telegramme mit dem Projekt ab: wer sendet, wer fehlt in der ETS, "
            "Wiederholungen, Lastspitzen. Der Busmonitor zeigt auch Wiederholungen und "
            "Quittungen, der Gruppenmonitor nicht.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._import_btn = QPushButton("Mitschnitt einlesen…")
        self._import_btn.clicked.connect(self._import)
        self._recordings = QComboBox()
        self._recordings.currentIndexChanged.connect(self._show)
        self._remove_btn = QPushButton("Mitschnitt entfernen")
        self._remove_btn.setObjectName("secondary")
        self._remove_btn.clicked.connect(self._remove)
        self._external_btn = QPushButton("Als externes Gerät erfassen…")
        self._external_btn.setObjectName("secondary")
        self._external_btn.clicked.connect(self._add_external)
        self._report_btn = QPushButton("Bericht Busanalyse…")
        self._report_btn.setObjectName("secondary")
        self._report_btn.clicked.connect(self._report)
        for widget in (self._import_btn, self._recordings, self._remove_btn,
                       self._external_btn, self._report_btn):
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        tabs = QTabWidget()
        self._findings = QTreeWidget()
        self._findings.setHeaderLabels(["Befund", "Einstufung"])
        self._findings.setColumnWidth(0, 760)
        tabs.addTab(self._findings, "Befunde")
        self._senders = self._table(["Absender", "Gerät", "Telegramme", "Wiederholungen",
                                     "Ziele"])
        self._senders.itemSelectionChanged.connect(self._update_buttons)
        tabs.addTab(self._senders, "Absender")
        self._pairs = self._table(["Absender", "Ziel", "Bezeichnung", "Dienst", "Anzahl",
                                   "Wiederholungen", "Wert", "Empfänger in der ETS"])
        tabs.addTab(self._pairs, "Telegramme")
        layout.addWidget(tabs, 1)
        self._update_buttons()

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSortingEnabled(True)
        return table

    def set_bus(self, bus) -> None:
        self._bus = bus

    def set_project(self, project) -> None:
        self._project = project
        self._fill_recordings()

    def _fill_recordings(self, select: int = -1) -> None:
        self._recordings.blockSignals(True)
        self._recordings.clear()
        for rec in (self._project.bus_recordings if self._project else []):
            self._recordings.addItem(f"{rec['file']} ({rec['start'][:16].replace('T', ' ')})")
        if self._recordings.count():
            self._recordings.setCurrentIndex(select if select >= 0 else self._recordings.count() - 1)
        self._recordings.blockSignals(False)
        self._show()

    def _current(self) -> dict | None:
        index = self._recordings.currentIndex()
        if self._project is None or index < 0 or index >= len(self._project.bus_recordings):
            return None
        return self._project.bus_recordings[index]

    # ── Anzeige ──────────────────────────────────────────────────────────

    def _show(self) -> None:
        summary = self._current()
        self._findings.clear()
        for table in (self._senders, self._pairs):
            table.setRowCount(0)
        if summary is None:
            self._analysis = None
            self._summary.setText("Noch kein Mitschnitt eingelesen.")
            self._update_buttons()
            return
        a = self._analysis = analyze(self._project, summary)
        self._summary.setText(
            f"<b>{summary['mode'] or 'Mitschnitt'}</b> über {summary['connection'] or '–'} · "
            f"{summary['start'][:19].replace('T', ' ')} bis {summary['stop'][11:19]} · "
            f"{summary['telegrams']} Telegramme ({a.per_minute:.0f} pro Minute), "
            f"{summary['repeats']} Wiederholungen, Spitze {summary['peak_per_second']} "
            "Rahmen/s. Gezeigt ist, was am Messpunkt ankommt.")

        for finding in a.findings:
            label, color = _LEVEL[finding.level]
            item = QTreeWidgetItem(self._findings, [finding.title, label])
            item.setForeground(1, QColor(color))
            item.setToolTip(0, finding.detail)
            QTreeWidgetItem(item, [finding.detail]).setForeground(0, QColor(TEXT_MUTED))
            for line in finding.items:
                QTreeWidgetItem(item, [line])
        self._findings.expandToDepth(0)

        self._senders.setSortingEnabled(False)
        self._senders.setRowCount(len(a.senders))
        for r, s in enumerate(a.senders):
            name = (s.device.product + (" (nicht im ETS-Projekt)" if s.device.external else "")
                    if s.device else "nicht im Projekt")
            cells = [s.address, name, s.telegrams, s.repeats, s.targets]
            for c, value in enumerate(cells):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
                if not s.known:
                    item.setForeground(QColor("#C62828"))
                self._senders.setItem(r, c, item)
        self._senders.setSortingEnabled(True)
        fit_columns(self._senders)

        self._pairs.setSortingEnabled(False)
        self._pairs.setRowCount(len(a.pairs))
        for r, p in enumerate(a.pairs):
            cells = [p.src, p.dst, p.designation, p.service, p.count, p.repeats, p.sample,
                     ", ".join(p.receivers) or "–"]
            for c, value in enumerate(cells):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
                self._pairs.setItem(r, c, item)
        self._pairs.setSortingEnabled(True)
        fit_columns(self._pairs)
        self._update_buttons()

    def _selected_unknown(self) -> str:
        row = self._senders.currentRow()
        if row < 0 or self._analysis is None:
            return ""
        address = self._senders.item(row, 0).text()
        return address if any(s.address == address for s in self._analysis.unknown) else ""

    def _update_buttons(self) -> None:
        has = self._current() is not None
        self._remove_btn.setEnabled(has)
        self._report_btn.setEnabled(has)
        self._recordings.setVisible(self._recordings.count() > 0)
        self._external_btn.setEnabled(bool(self._selected_unknown()))

    # ── Aktionen ─────────────────────────────────────────────────────────

    def _import(self) -> None:
        if self._project is None:
            return
        folder = self._project.folder_path or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Busmonitor-Mitschnitt einlesen", folder, "ETS-Mitschnitt (*.xml)")
        if not path:
            return
        try:
            summary = summarize(parse_log(path))
        except BusLogError as exc:
            QMessageBox.warning(self, "Mitschnitt einlesen", str(exc))
            return
        if self._bus:
            self._bus.begin_change(f"Busmonitor-Mitschnitt {os.path.basename(path)} eingelesen")
        self._project.bus_recordings.append(summary)
        self._changed()
        self._fill_recordings()

    def _remove(self) -> None:
        index = self._recordings.currentIndex()
        if index < 0:
            return
        if self._bus:
            self._bus.begin_change("Busmonitor-Mitschnitt entfernt")
        del self._project.bus_recordings[index]
        self._changed()
        self._fill_recordings()

    def _changed(self) -> None:
        if self._bus:
            self._bus.any_change.emit("bus_recordings")
        self.changed.emit()

    def _add_external(self) -> None:
        """Unbekannten Absender als externes Gerät in seiner Linie erfassen."""
        address = self._selected_unknown()
        if not address:
            return
        a, l, _t = (int(x) for x in address.split("."))
        area = next((x for x in self._project.topology.areas if x.area_number == a), None)
        line = next((y for y in (area.lines if area else []) if y.line_number == l), None)
        if line is None:
            QMessageBox.information(
                self, "Externes Gerät",
                f"Linie {a}.{l} gibt es im Projekt nicht. Bitte zuerst in der ETS anlegen.")
            return
        from ..dialogs.external_device_dialog import ExternalDeviceDialog
        dlg = ExternalDeviceDialog(a, line, None, self)
        dlg._participant.setValue(int(address.rsplit(".", 1)[1]))
        if not dlg.exec():
            return
        if self._bus:
            self._bus.begin_change(f"Externes Gerät {dlg.physical_address} erfasst")
        line.devices.append(dlg.apply())
        line.update_device_count()
        if self._bus:
            self._bus.emit_topology_changed()
        self._show()

    def _report(self) -> None:
        summary = self._current()
        if summary is None:
            return
        from .. import license_gate
        from ..dialogs.reports_dialog import open_report
        from ...services.project_service import ProjectService
        from ...services.report_service import ReportService
        folder = self._project.folder_path
        name = f"{self._project.name}_Busanalyse.pdf"
        default = os.path.join(folder, "Berichte", name) if folder else name
        if folder:
            os.makedirs(os.path.join(folder, "Berichte"), exist_ok=True)
        path, _ = license_gate.get_save_file_name(
            self, "Bericht Busanalyse speichern", default, "PDF-Dateien (*.pdf)")
        if not path:
            return
        ReportService(self._project, company_profile=ProjectService().load_company_profile()) \
            .generate_bus_analysis_report(path, summary)
        open_report(path)
