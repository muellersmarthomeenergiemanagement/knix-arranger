"""
Busanalyse (FA-640): Busmonitor-Mitschnitt der ETS einlesen und gegen das
Projekt auswerten -- Absender, unbekannte und externe Geräte, Wiederholungen,
Quittungen (ACK, NAK, BUSY), Lastspitzen, häufig sendende Geräte
(services/bus_monitor).
"""
from __future__ import annotations
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from ...services.bus_monitor import (
    PAIR_FILTERS, BusLogError, ack_summary, analyze, line_of, pair_flags, pair_matches,
    parse_log, summarize, text_matches,
)
from ...services.bus_checks import compare
from ..column_utils import fit_columns
from ..styles import TEXT_MUTED
from ..widgets.load_chart import LoadChart

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
            "Wiederholungen, Quittungen, Datenlänge gegen DPT, Lesen und Antworten, "
            "Koppler und Buslast; zwei Mitschnitte lassen sich vergleichen. Der Busmonitor "
            "zeigt auch Wiederholungen und Quittungen (ACK, NAK, BUSY), der Gruppenmonitor "
            "nicht.")
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

        # Filter: Suchtext, Auffälligkeit, Linie des Absenders
        filters = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Suchen: Adresse, GA, Bezeichnung, Gerät (z.B. 1.2.7 1/5 Waschen)")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        self._category = QComboBox()
        for key, label in PAIR_FILTERS:
            self._category.addItem(label, key)
        self._category.currentIndexChanged.connect(self._apply_filter)
        self._line = QComboBox()
        self._line.currentIndexChanged.connect(self._apply_filter)
        self._reset_btn = QPushButton("Filter zurücksetzen")
        self._reset_btn.setObjectName("secondary")
        self._reset_btn.clicked.connect(self._reset_filter)
        self._count = QLabel()
        self._count.setStyleSheet(f"color: {TEXT_MUTED};")
        filters.addWidget(self._search, 3)
        filters.addWidget(self._category, 1)
        filters.addWidget(self._line)
        filters.addWidget(self._reset_btn)
        filters.addWidget(self._count)
        layout.addLayout(filters)

        tabs = self._tabs = QTabWidget()
        self._findings = QTreeWidget()
        self._findings.setHeaderLabels(["Befund", "Einstufung"])
        self._findings.setColumnWidth(0, 760)
        self._findings.itemDoubleClicked.connect(self._finding_jump)
        self._findings.setToolTip("Doppelklick auf eine Zeile «Absender → Ziel»: "
                                  "zugehörige Telegramme zeigen")
        tabs.addTab(self._findings, "Befunde")
        self._senders = self._table(["Absender", "Gerät", "Telegramme", "Wiederholungen",
                                     "Ziele"])
        self._senders.itemSelectionChanged.connect(self._update_buttons)
        self._senders.itemDoubleClicked.connect(self._sender_jump)
        self._senders.setToolTip("Doppelklick: Telegramme dieses Absenders zeigen")
        tabs.addTab(self._senders, "Absender")
        self._pairs = self._table(["Absender", "Ziel", "Bezeichnung", "Dienst", "Anzahl",
                                   "Wiederholungen", "Quittung", "Wert",
                                   "Empfänger in der ETS"])
        tabs.addTab(self._pairs, "Telegramme")

        load_tab = QWidget()
        load_layout = QVBoxLayout(load_tab)
        self._load_info = QLabel()
        self._load_info.setWordWrap(True)
        self._load_chart = LoadChart()
        load_layout.addWidget(self._load_info)
        load_layout.addWidget(self._load_chart, 1)
        tabs.addTab(load_tab, "Buslast")

        compare_tab = QWidget()
        compare_layout = QVBoxLayout(compare_tab)
        compare_row = QHBoxLayout()
        compare_row.addWidget(QLabel("Vergleichen mit:"))
        self._compare_with = QComboBox()
        self._compare_with.currentIndexChanged.connect(self._show_comparison)
        compare_row.addWidget(self._compare_with, 1)
        compare_layout.addLayout(compare_row)
        self._metrics = self._table(["Kennzahl", "Vergleichs-Mitschnitt", "Dieser Mitschnitt"])
        self._metrics.setSortingEnabled(False)
        compare_layout.addWidget(self._metrics, 1)
        self._differences = QTreeWidget()
        self._differences.setHeaderLabels(["Unterschied"])
        compare_layout.addWidget(self._differences, 2)
        tabs.addTab(compare_tab, "Vergleich")
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
        self._flags = {}
        if summary is None:
            self._analysis = None
            self._fill_lines([])
            self._count.setText("")
            self._load_chart.set_points([])
            self._load_info.setText("")
            self._fill_compare()
            self._summary.setText("Noch kein Mitschnitt eingelesen.")
            self._update_buttons()
            return
        a = self._analysis = analyze(self._project, summary)
        self._summary.setText(
            f"<b>{summary['mode'] or 'Mitschnitt'}</b> über {summary['connection'] or '–'} · "
            f"{summary['start'][:19].replace('T', ' ')} bis {summary['stop'][11:19]} · "
            f"{summary['telegrams']} Telegramme ({a.per_minute:.0f} pro Minute), "
            f"{summary['repeats']} Wiederholungen, {ack_summary(summary)}, "
            f"Spitze {summary['peak_per_second']} Rahmen/s. "
            + (f"Messpunkt Linie {a.measuring_line} (aus dem Routing-Zähler). "
               if a.measuring_line else "")
            + "Gezeigt ist, was am Messpunkt ankommt.")

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
                item.setData(Qt.UserRole, s)
                if not s.known:
                    item.setForeground(QColor("#C62828"))
                self._senders.setItem(r, c, item)
        self._senders.setSortingEnabled(True)
        fit_columns(self._senders)

        self._pairs.setSortingEnabled(False)
        self._pairs.setRowCount(len(a.pairs))
        for r, p in enumerate(a.pairs):
            cells = [p.src, p.dst, p.designation, p.service, p.count, p.repeats,
                     p.ack_text, p.value,
                     ", ".join(p.receivers) or "–"]
            for c, value in enumerate(cells):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
                item.setData(Qt.UserRole, p)
                if c == 7 and p.sample:
                    item.setToolTip(f"Hex {p.sample}" + (f", {p.dpt}" if p.dpt else ""))
                self._pairs.setItem(r, c, item)
        self._pairs.setSortingEnabled(True)
        fit_columns(self._pairs)
        self._flags = pair_flags(a)
        self._fill_lines(sorted({line_of(s.address) for s in a.senders} - {""},
                                key=lambda x: tuple(int(n) for n in x.split("."))))
        self._apply_filter()
        self._show_load(a)
        self._fill_compare()
        self._update_buttons()

    # ── Buslast und Vergleich ────────────────────────────────────────────

    def _show_load(self, a) -> None:
        from ...services.bus_checks import LOAD_HINT, LOAD_WARN
        self._load_chart.set_points(a.load)
        if not a.load:
            self._load_info.setText("Dieser Mitschnitt enthält noch keine Busbelegung je "
                                    "Minute; für den Verlauf neu einlesen.")
            return
        top = max(a.load, key=lambda p: p.percent)
        average = sum(p.percent for p in a.load) / len(a.load)
        self._load_info.setText(
            f"Busbelegung je Minute (Rahmen und Quittungen, geschätzt aus der Rahmenlänge bei "
            f"9600 bit/s): Mittel {average:.1f} %, höchste Minute {top.percent:.1f} % um "
            f"{top.minute[11:16]}. Richtwert dauerhaft unter {LOAD_HINT} %, kurzzeitig unter "
            f"{LOAD_WARN} %.")

    def _fill_compare(self) -> None:
        current = self._recordings.currentIndex()
        recordings = self._project.bus_recordings if self._project else []
        self._compare_with.blockSignals(True)
        selected = self._compare_with.currentData()
        self._compare_with.clear()
        self._compare_with.addItem("– kein Vergleich –", -1)
        for i, rec in enumerate(recordings):
            if i != current:
                self._compare_with.addItem(
                    f"{rec['file']} ({rec['start'][:16].replace('T', ' ')})", i)
        index = self._compare_with.findData(selected)
        self._compare_with.setCurrentIndex(max(index, 0))
        self._compare_with.blockSignals(False)
        self._compare_with.setEnabled(len(recordings) > 1)
        self._show_comparison()

    def _comparison_reference(self) -> dict | None:
        index = self._compare_with.currentData()
        if self._project is None or index is None or index < 0 \
                or index >= len(self._project.bus_recordings):
            return None
        return self._project.bus_recordings[index]

    def _show_comparison(self) -> None:
        self._metrics.setRowCount(0)
        self._differences.clear()
        summary, reference = self._current(), self._comparison_reference()
        if summary is None or reference is None:
            hint = ("Zum Vergleichen einen zweiten Mitschnitt einlesen, z.B. vor und nach "
                    "einem Umbau." if summary is not None and self._compare_with.count() < 2
                    else "Vergleichs-Mitschnitt wählen.")
            QTreeWidgetItem(self._differences, [hint])
            return
        c = compare(self._project, summary, reference)
        self._metrics.setRowCount(len(c.metrics))
        for r, row in enumerate(c.metrics):
            for col, value in enumerate(row):
                self._metrics.setItem(r, col, QTableWidgetItem(value))
        fit_columns(self._metrics)
        groups = [
            ("Neue Befunde", c.new_findings),
            ("Behobene Befunde", c.resolved_findings),
            ("Neue Absender", c.new_senders),
            ("Absender nicht mehr gesehen", c.gone_senders),
            ("Neue Ziel-GAs", c.new_targets),
            ("Ziel-GAs nicht mehr gesehen", c.gone_targets),
            ("Häufigkeit verändert (Telegramme je Stunde)",
             [f"{key}: {before:.0f} → {after:.0f}" for key, before, after in c.changed]),
        ]
        for title, lines in groups:
            top = QTreeWidgetItem(self._differences, [f"{title} ({len(lines)})"])
            for line in lines[:200]:
                QTreeWidgetItem(top, [line])
            top.setExpanded(bool(lines) and len(lines) <= 20)

    # ── Filter ───────────────────────────────────────────────────────────

    def _fill_lines(self, lines: list[str]) -> None:
        current = self._line.currentData()
        self._line.blockSignals(True)
        self._line.clear()
        self._line.addItem("Alle Linien", "")
        for line in lines:
            self._line.addItem(f"Linie {line}", line)
        index = self._line.findData(current)
        self._line.setCurrentIndex(max(index, 0))
        self._line.blockSignals(False)
        self._line.setVisible(len(lines) > 1)

    def _reset_filter(self) -> None:
        for widget in (self._search, self._category, self._line):
            widget.blockSignals(True)
        self._search.clear()
        self._category.setCurrentIndex(0)
        self._line.setCurrentIndex(0)
        for widget in (self._search, self._category, self._line):
            widget.blockSignals(False)
        self._apply_filter()

    def _pair_visible(self, p, query: str, category: str, line: str) -> bool:
        return (pair_matches(self._flags.get(id(p), set()), category)
                and (not line or line_of(p.src) == line)
                and text_matches(query, [p.src, p.dst, p.designation, p.service,
                                         p.ack_text, *p.receivers]))

    def _apply_filter(self) -> None:
        a = self._analysis
        if a is None:
            return
        query = self._search.text()
        category = self._category.currentData() or "all"
        line = self._line.currentData() or ""
        visible = {id(p) for p in a.pairs if self._pair_visible(p, query, category, line)}
        shown = 0
        for r in range(self._pairs.rowCount()):
            p = self._pairs.item(r, 0).data(Qt.UserRole)
            hide = id(p) not in visible
            self._pairs.setRowHidden(r, hide)
            shown += not hide
        # Absender: eigene Zeile passt zum Suchtext oder eines seiner Telegramme ist sichtbar
        active = bool(query.strip()) or category != "all"
        senders_with = {p.src for p in a.pairs if id(p) in visible}
        for r in range(self._senders.rowCount()):
            s = self._senders.item(r, 0).data(Qt.UserRole)
            name = self._senders.item(r, 1).text()
            own = text_matches(query, [s.address, name])
            ok = (not line or line_of(s.address) == line) and (
                not active or s.address in senders_with
                or (category == "all" and own)
                or (category == "unknown" and not s.known and own))
            self._senders.setRowHidden(r, not ok)
        # Befunde: Einzelzeilen nach Suchtext, Befund ohne passende Zeile ausblenden
        searching = bool(query.strip())
        for i in range(self._findings.topLevelItemCount()):
            top = self._findings.topLevelItem(i)
            any_child = False
            for c in range(1, top.childCount()):        # Zeile 0 ist die Erläuterung
                child = top.child(c)
                ok = text_matches(query, [child.text(0)])
                child.setHidden(not ok)
                any_child = any_child or ok
            top.setHidden(searching and not any_child and not text_matches(query, [top.text(0)]))
        total = len(a.pairs)
        self._count.setText(f"{shown} von {total} Telegrammen" if shown != total
                            else f"{total} Telegramme")
        self._reset_btn.setEnabled(active or bool(line))

    def _show_pairs(self, query: str) -> None:
        self._category.blockSignals(True)
        self._category.setCurrentIndex(0)
        self._category.blockSignals(False)
        self._search.setText(query)
        self._apply_filter()
        self._tabs.setCurrentWidget(self._pairs)

    def _sender_jump(self, item) -> None:
        s = self._senders.item(item.row(), 0).data(Qt.UserRole)
        self._show_pairs(s.address)

    def _finding_jump(self, item, _column=0) -> None:
        text = item.text(0)
        if "→" not in text:
            return
        src, rest = text.split("→", 1)
        words = rest.split()
        dst = words[0].rstrip(":") if words else ""
        self._show_pairs(f"{src.strip()} {dst}".strip())

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
            .generate_bus_analysis_report(path, summary, self._comparison_reference())
        open_report(path)
