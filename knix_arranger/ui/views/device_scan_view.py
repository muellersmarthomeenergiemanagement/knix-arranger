"""
Teilnehmer suchen (FA-3108): Linien der Anlage über die Verbindung des
Live-Monitors absuchen und das Gefundene mit dem Projekt vergleichen.
Nur lesend (services/device_scan).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...services import device_scan as ds
from ...services import reconstruction_steps as rs
from ...services.bus_access import BusSendError
from ..styles import COLOR_ERROR, COLOR_INFO, COLOR_OK, COLOR_WARNING, TEXT_MUTED

_STATUS_COLORS = {
    ds.STATUS_OK: COLOR_OK,
    ds.STATUS_DIFFERENT: COLOR_WARNING,
    ds.STATUS_EXTRA: COLOR_INFO,
    ds.STATUS_LOCKED: "#6A1B9A",
    ds.STATUS_MISSING: COLOR_ERROR,
    ds.STATUS_OWN: TEXT_MUTED,
}

FILTER_ALL = "all"
FILTER_PROBLEMS = "problems"


class _Bridge(QObject):
    """Rückrufe aus dem Loop der Busverbindung in den Hauptthread."""
    progress = Signal(object)
    found = Signal(object)
    finished = Signal(object, str)
    link_read = Signal(object)
    links_finished = Signal(object, str)
    couplers_found = Signal(object, str)


class DeviceScanView(QWidget):
    navigate_requested = Signal(str)
    # Geräte ins Projekt übernommen (Topologie geändert)
    adopted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._bus = None
        # Produktkatalog für die Übernahme (None = gemeinsamer Katalog)
        self.catalog = None
        # Live-Monitor: hält die Verbindung (setzt das Hauptfenster)
        self.bus_monitor = None
        self._findings: list[ds.ScanFinding] = []
        self._lines: list[tuple[int, int]] = []
        self._rows: list[ds.ScanRow] = []
        # gelesene GA- und Zuordnungstabellen je Adresse (FA-3108b)
        self._tables: dict[str, ds.LinkTables] = {}
        self._future = None
        self._stop: threading.Event | None = None
        self._bridge = _Bridge()
        self._bridge.progress.connect(self._on_progress)
        self._bridge.found.connect(self._on_found)
        self._bridge.finished.connect(self._on_finished)
        self._bridge.link_read.connect(self._on_link_read)
        self._bridge.links_finished.connect(self._on_links_finished)
        self._bridge.couplers_found.connect(self._on_couplers_found)
        self._finding_lines = False

        layout = QVBoxLayout(self)
        title = QLabel("Teilnehmer suchen")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Sucht auf den angegebenen Linien jede physikalische Adresse (0–255) ab und "
            "liest von den Geräten, die antworten, Hersteller, Seriennummer, Bestellnummer "
            "und Applikation. Nur lesend: an den Geräten ändert sich nichts. Das Ergebnis "
            "wird mit dem Projekt verglichen. Secure-Geräte geben ohne Schlüssel meist "
            "keine Daten preis. Dauer: rund 3 Minuten je Linie. «GAs und Verknüpfungen "
            "lesen» holt danach aus jedem Gerät seine Gruppenadressen und welches KO an "
            "welcher GA hängt (je Gerät einige Sekunden).")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        # Anlage ohne Projektdatei (FA-3105e): Schritte mit Stand, nichts gesperrt
        self._steps_box = QWidget()
        steps_layout = QHBoxLayout(self._steps_box)
        steps_layout.setContentsMargins(0, 4, 0, 4)
        steps_layout.setSpacing(4)
        steps_label = QLabel("Anlage aufnehmen:")
        steps_label.setToolTip("Reihenfolge für eine Anlage ohne Projektdatei. Jeder Schritt "
                               "lässt sich wiederholen; ✓ = erledigt, … = teilweise.")
        steps_layout.addWidget(steps_label)
        self._step_buttons: dict[str, QPushButton] = {}
        for step in rs.steps(None):
            button = QPushButton()
            button.clicked.connect(lambda _c=False, key=step.key: self._run_step(key))
            steps_layout.addWidget(button)
            self._step_buttons[step.key] = button
        steps_layout.addStretch(1)
        layout.addWidget(self._steps_box)

        connection = QHBoxLayout()
        self._connection = QLabel()
        self._monitor_btn = QPushButton("Zum Live-Monitor")
        self._monitor_btn.setObjectName("secondary")
        self._monitor_btn.setToolTip("Verbunden wird im Live-Monitor (KNXnet/IP-Tunnel)")
        self._monitor_btn.clicked.connect(lambda: self.navigate_requested.emit("live_monitor"))
        connection.addWidget(self._connection, 1)
        connection.addWidget(self._monitor_btn)
        layout.addLayout(connection)

        row = QHBoxLayout()
        row.addWidget(QLabel("Linien:"))
        self._lines_edit = QLineEdit()
        self._lines_edit.setPlaceholderText("leer = Linien finden, z.B. 1.1, 1.2")
        self._lines_edit.setToolTip("Bereich.Linie, mehrere mit Komma. Leer: KNiX findet "
                                    "die Linien zuerst selbst.")
        self._lines_edit.returnPressed.connect(self._start)
        self._find_btn = QPushButton("Linien finden…")
        self._find_btn.setObjectName("secondary")
        self._find_btn.setToolTip(
            "Linien der Anlage ermitteln: Linie der Schnittstelle, Absender der "
            "mitgehörten Telegramme und Koppler (B.L.0), die antworten – rund 1–3 Minuten")
        self._find_btn.clicked.connect(self._find_lines)
        self._start_btn = QPushButton("Suchen")
        self._start_btn.clicked.connect(self._start)
        self._links_btn = QPushButton("GAs und Verknüpfungen lesen")
        self._links_btn.setObjectName("secondary")
        self._links_btn.setToolTip(
            "Aus jedem gefundenen Gerät die GA-Tabelle und die Zuordnungstabelle lesen "
            "(nur lesend). Bei Geräten mit Verknüpfungen im Projekt: Vergleich mit der Anlage")
        self._links_btn.clicked.connect(self._read_links)
        self._stop_btn = QPushButton("Abbrechen")
        self._stop_btn.setObjectName("secondary")
        self._stop_btn.clicked.connect(self._cancel)
        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.hide()
        row.addWidget(self._lines_edit, 1)
        row.addWidget(self._find_btn)
        row.addWidget(self._start_btn)
        row.addWidget(self._links_btn)
        row.addWidget(self._stop_btn)
        row.addWidget(self._progress, 1)
        layout.addLayout(row)

        filters = QHBoxLayout()
        self._filter = QComboBox()
        self._filter.addItem("Alle Geräte", FILTER_ALL)
        self._filter.addItem("Nur Abweichungen", FILTER_PROBLEMS)
        self._filter.currentIndexChanged.connect(self._fill_table)
        self._summary = QLabel()
        self._summary.setStyleSheet(f"color: {TEXT_MUTED};")
        self._export_btn = QPushButton("Als CSV speichern…")
        self._export_btn.setObjectName("secondary")
        self._export_btn.clicked.connect(self._export)
        self._adopt_btn = QPushButton("Ins Projekt übernehmen…")
        self._adopt_btn.setToolTip(
            "Gefundene Geräte im Projekt anlegen (Linien, Hersteller, Seriennummer, Produkt "
            "und KOs aus dem Katalog), gelesene GAs und Verknüpfungen dazu; bestehende "
            "Geräte und Verknüpfungen nur ergänzen, nie überschreiben")
        self._adopt_btn.clicked.connect(self._adopt)
        self._products_btn = QPushButton("Herstellerdateien…")
        self._products_btn.setObjectName("secondary")
        self._products_btn.setToolTip(
            "Geräte ohne Produkt aus dem Katalog: welche .knxprod fehlt, Datei hinzufügen "
            "oder aus einem ETS-Projekt herauslösen, Geräte nachführen")
        self._products_btn.clicked.connect(self._open_missing_products)
        self._meaning_btn = QPushButton("Bedeutung ergänzen…")
        self._meaning_btn.setObjectName("secondary")
        self._meaning_btn.setToolTip(
            "Gelesene GAs mit vorläufigem Namen: Gewerk, Funktion und Name nach dem "
            "Namensschema aus den KOs (z.B. «J_1.1.4_03 AUF/AB (Motor C)»), Mittelgruppen "
            "nach Gewerk benennen, Szenen erkennen. Änderbar, mit Rückgängig.")
        self._meaning_btn.clicked.connect(self._add_meaning)
        self._rooms_btn = QPushButton("Räume zuordnen…")
        self._rooms_btn.setObjectName("secondary")
        self._rooms_btn.setToolTip(
            "Taster und Sensoren mit ihren Aktorkanälen einem Raum zuweisen; die GA-Namen "
            "bekommen den Raum an Stelle der Geräteadresse")
        from PySide6.QtWidgets import QMenu
        rooms_menu = QMenu(self._rooms_btn)
        rooms_menu.addAction("Rundgang vor Ort (Raum für Raum)…",
                             lambda: self._assign_rooms(tour=True))
        rooms_menu.addAction("Übersicht…", lambda: self._assign_rooms(tour=False))
        self._rooms_btn.setMenu(rooms_menu)
        filters.addWidget(self._filter)
        filters.addWidget(self._summary, 1)
        filters.addWidget(self._export_btn)
        filters.addWidget(self._adopt_btn)
        filters.addWidget(self._products_btn)
        filters.addWidget(self._meaning_btn)
        filters.addWidget(self._rooms_btn)
        layout.addLayout(filters)

        self._table = QTableWidget(0, len(ds.COLUMNS))
        self._table.setHorizontalHeaderLabels(ds.COLUMNS)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.horizontalHeader().setStretchLastSection(True)
        # Hinweis (letzte Spalte) nimmt den Rest der Breite
        for column, width in enumerate((60, 105, 80, 190, 150, 120, 95, 160)):
            self._table.setColumnWidth(column, width)
        layout.addWidget(self._table, 1)
        from ..column_utils import EmptyHint
        self._hint = EmptyHint(
            self._table,
            "Noch keine Suche. Im Live-Monitor über KNXnet/IP verbinden, Linien angeben "
            "und «Suchen» wählen.")
        self._update_controls()

    # ── Projekt und Verbindung ───────────────────────────────────────────

    def set_project(self, project) -> None:
        if project is not self._project:
            self._cancel()
            self._findings, self._lines, self._rows = [], [], []
            self._tables = {}
            lines = ds.project_lines(project) if project is not None else []
            self._lines_edit.setText(", ".join(ds.line_text(line) for line in lines))
        self._project = project
        self._compare()
        self._update_controls()

    def set_bus_monitor(self, monitor) -> None:
        self.bus_monitor = monitor
        monitor.state_changed.connect(lambda _state: self._update_controls())
        self._update_controls()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_controls()

    @property
    def scanning(self) -> bool:
        return self._future is not None

    def _update_controls(self) -> None:
        monitor = self.bus_monitor
        usable = monitor is not None and monitor.can_access_devices
        if usable:
            self._connection.setText(f"Verbunden: {monitor.connection_label}")
            self._connection.setStyleSheet(f"color: {COLOR_OK};")
        elif monitor is not None and monitor.listening:
            self._connection.setText("Über die USB-Schnittstelle sucht KNiX keine Teilnehmer – "
                                     "im Live-Monitor über KNXnet/IP (Tunnel) verbinden.")
            self._connection.setStyleSheet(f"color: {COLOR_WARNING};")
        else:
            self._connection.setText("Nicht verbunden – im Live-Monitor über KNXnet/IP "
                                     "verbinden, dann hier suchen.")
            self._connection.setStyleSheet(f"color: {TEXT_MUTED};")
        self._monitor_btn.setVisible(not usable)
        self._start_btn.setEnabled(usable and not self.scanning)
        self._find_btn.setEnabled(usable and not self.scanning)
        self._links_btn.setEnabled(usable and not self.scanning
                                   and any(ds.readable_for_links(f) for f in self._findings))
        self._stop_btn.setEnabled(self.scanning)
        self._lines_edit.setEnabled(not self.scanning)
        self._export_btn.setEnabled(bool(self._rows))
        self._adopt_btn.setEnabled(self._project is not None and not self.scanning
                                   and any(f.answered and not f.own for f in self._findings))
        from ...services.ga_meaning import is_provisional
        structure = getattr(self._project, "group_addresses", None)
        self._meaning_btn.setEnabled(
            structure is not None and not self.scanning
            and any(is_provisional(ga) and ga.designation
                    for ga in structure.all_addresses()))
        self._rooms_btn.setEnabled(
            self._project is not None and not self.scanning
            and any(getattr(d, "communication_objects", None)
                    for d in ds.project_devices(self._project)))
        from ...services import missing_products
        without = (missing_products.device_count(self._project)
                   if getattr(self._project, "topology", None) is not None else 0)
        self._products_btn.setVisible(bool(without))
        self._products_btn.setEnabled(not self.scanning)
        self._products_btn.setText(f"Herstellerdateien ({without})…" if without
                                   else "Herstellerdateien…")
        self._refresh_steps(usable)

    # ── Schritte «Anlage aufnehmen» (FA-3105e) ───────────────────────────

    def _refresh_steps(self, connected: bool) -> None:
        if not rs.applies(self._project):
            self._steps_box.hide()
            return
        self._steps_box.show()
        found = sum(1 for f in self._findings if f.answered and not f.own)
        step_list = rs.steps(self._project, connected, found)
        current = rs.current(step_list, connected)
        enabled = {
            rs.CONNECT: True,
            rs.SEARCH: self._start_btn.isEnabled() or not connected,
            rs.ADOPT: self._adopt_btn.isEnabled() or not self._products_btn.isHidden(),
            rs.LINKS: self._links_btn.isEnabled(),
            rs.MEANING: self._meaning_btn.isEnabled(),
            rs.BUILDING: not self.scanning,
            rs.TOUR: self._rooms_btn.isEnabled(),
        }
        for step in step_list:
            button = self._step_buttons[step.key]
            mark = {rs.DONE: " ✓", rs.PARTIAL: " …"}.get(step.state, "")
            button.setText(f"{step.number} {step.title}{mark}")
            tip = step.detail or "noch offen"
            if step.key == current:
                tip = "Nächster Schritt – " + tip
            button.setToolTip(tip)
            button.setEnabled(enabled[step.key])
            button.setObjectName("" if step.key == current else "secondary")
            button.setStyleSheet(
                "font-weight: bold;" if step.key == current
                else f"color: {COLOR_OK};" if step.state == rs.DONE else "")
            button.style().unpolish(button)
            button.style().polish(button)

    def _run_step(self, key: str) -> None:
        connected = self.bus_monitor is not None and self.bus_monitor.can_access_devices
        if key == rs.CONNECT or (key in (rs.SEARCH, rs.LINKS) and not connected):
            self.navigate_requested.emit("live_monitor")
        elif key == rs.SEARCH:
            if self._project is None or not ds.project_devices(self._project):
                self._find_lines()       # unbekannte Anlage: Linien zuerst finden
            else:
                self._start()
        elif key == rs.ADOPT:
            if self._adopt_btn.isEnabled():
                self._adopt()
            else:
                self._open_missing_products()   # übernommen, Herstellerdateien fehlen
        elif key == rs.LINKS:
            self._read_links()
        elif key == rs.MEANING:
            self._add_meaning()
        elif key == rs.BUILDING:
            self.navigate_requested.emit("building")
        elif key == rs.TOUR:
            self._assign_rooms(tour=True)

    def set_bus(self, bus) -> None:
        self._bus = bus

    # ── Suche ────────────────────────────────────────────────────────────

    def _start(self) -> None:
        if self.scanning or self.bus_monitor is None:
            return
        if not self._lines_edit.text().strip():
            self._find_lines()       # unbekannte Anlage: Linien zuerst finden
            return
        try:
            lines = ds.parse_lines(self._lines_edit.text())
        except ValueError as exc:
            QMessageBox.information(self, "Teilnehmer suchen", str(exc))
            return
        stop = threading.Event()
        bridge = self._bridge
        expected = ({d.physical_address for d in ds.project_devices(self._project)}
                    if self._project is not None else set())

        def factory(xknx):
            return ds.scan_line(xknx, lines, on_progress=bridge.progress.emit,
                                on_found=bridge.found.emit, stop=stop, retry=expected)
        try:
            future = self.bus_monitor.run_on_bus(factory)
        except BusSendError as exc:
            QMessageBox.information(self, "Teilnehmer suchen", str(exc))
            return
        self._future, self._stop = future, stop
        self._lines, self._findings = lines, []
        self._compare()
        self._progress.setRange(0, len(lines) * 256)
        self._progress.setValue(0)
        self._progress.setFormat("%v von %m Adressen")
        self._progress.show()

        def done(f) -> None:
            if f.cancelled():
                bridge.finished.emit(None, "abgebrochen")
                return
            exc = f.exception()
            if exc is not None:
                bridge.finished.emit(None, str(exc) or exc.__class__.__name__)
            else:
                bridge.finished.emit(f.result(), "")
        future.add_done_callback(done)
        self._update_controls()

    def _cancel(self) -> None:
        if self._stop is not None:
            self._stop.set()     # laufende Anfragen enden nach ihrer Wartezeit

    def _on_progress(self, progress: ds.ScanProgress) -> None:
        if not self.scanning:
            return
        self._progress.setValue(progress.done)
        what = "Koppler" if self._finding_lines else "Teilnehmer"
        self._summary.setText(f"{what}: {progress.address} … {progress.found} gefunden")

    # ── Linien finden (FA-3108e) ─────────────────────────────────────────

    def _find_lines(self) -> None:
        """Kopplerplätze abfragen, danach mit Schnittstelle und gehörten
        Absendern die Linien zur Auswahl stellen."""
        if self.scanning or self.bus_monitor is None:
            return
        stop = threading.Event()
        bridge = self._bridge

        def factory(xknx):
            return ds.find_couplers(xknx, on_progress=bridge.progress.emit, stop=stop)
        try:
            future = self.bus_monitor.run_on_bus(factory)
        except BusSendError as exc:
            QMessageBox.information(self, "Linien finden", str(exc))
            return
        self._future, self._stop = future, stop
        self._finding_lines = True
        self._progress.setRange(0, 15 * 16)
        self._progress.setValue(0)
        self._progress.setFormat("%v von %m Kopplerplätzen")
        self._progress.show()

        def done(f) -> None:
            if f.cancelled():
                bridge.couplers_found.emit(None, "abgebrochen")
                return
            exc = f.exception()
            if exc is not None:
                bridge.couplers_found.emit(None, str(exc) or exc.__class__.__name__)
            else:
                bridge.couplers_found.emit(f.result(), "")
        future.add_done_callback(done)
        self._update_controls()

    def _on_couplers_found(self, couplers, error: str) -> None:
        stopped = self._stop is not None and self._stop.is_set()
        self._future = self._stop = None
        self._finding_lines = False
        self._progress.hide()
        self._update_controls()
        if stopped:
            self._summary.setText("Linien finden abgebrochen")
            return
        if error:
            QMessageBox.warning(self, "Linien finden", f"Nicht abgeschlossen: {error}")
        candidates = self.line_candidates(couplers or [])
        from ..dialogs.line_choice_dialog import LineChoiceDialog
        dialog = LineChoiceDialog(candidates, couplers_searched=not error, parent=self)
        if dialog.exec() != LineChoiceDialog.Accepted:
            self._summary.setText(f"{len(candidates)} Linien gefunden")
            return
        self._lines_edit.setText(", ".join(ds.line_text(l) for l in dialog.selected_lines()))
        self._start()

    def line_candidates(self, couplers: list) -> list:
        """Linien aus Schnittstelle, mitgehörten Absendern, Kopplern und Projekt."""
        monitor = self.bus_monitor
        own = getattr(monitor, "local_address", "") or ""
        history = monitor.history() if hasattr(monitor, "history") else []
        project = ds.project_lines(self._project) if self._project is not None else []
        return ds.line_candidates(own, ds.senders_per_line(history, own), couplers, project)

    def _on_found(self, finding: ds.ScanFinding) -> None:
        if not self.scanning:
            return
        # zweiter Versuch ersetzt den ersten
        self._findings = [f for f in self._findings if f.address != finding.address]
        self._findings.append(finding)
        self._compare(final=False)

    def _on_finished(self, findings, error: str) -> None:
        stopped = self._stop is not None and self._stop.is_set()
        self._future = self._stop = None
        self._progress.hide()
        if findings is not None:
            self._findings = list(findings)
        self._compare()
        if error and error != "abgebrochen":
            QMessageBox.warning(self, "Teilnehmer suchen",
                                f"Suche nicht abgeschlossen: {error}")
        elif stopped:
            self._summary.setText(self._summary.text() + " – abgebrochen, Ergebnis unvollständig")
        self._update_controls()

    # ── GAs und Verknüpfungen (FA-3108b) ─────────────────────────────────

    def _read_links(self, only=None) -> None:
        """only: nur diese Adressen (z.B. nach dem Nachführen der Herstellerdatei)."""
        if self.scanning or self.bus_monitor is None:
            return
        targets = [f for f in self._findings if ds.readable_for_links(f)
                   and (only is None or f.address in only)]
        if not targets:
            return
        stop = threading.Event()
        bridge = self._bridge
        # Lage der KO-Tabellen aus den Herstellerdateien (liest Dateien,
        # darum hier und nicht im Bus-Loop)
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            hints = ds.object_table_hints(targets, self._project)
        except Exception:
            hints = {}
        finally:
            QApplication.restoreOverrideCursor()

        def factory(xknx):
            return ds.read_all_links(xknx, targets, on_progress=bridge.progress.emit,
                                     on_read=bridge.link_read.emit, stop=stop,
                                     table_hints=hints)
        try:
            future = self.bus_monitor.run_on_bus(factory)
        except BusSendError as exc:
            QMessageBox.information(self, "GAs und Verknüpfungen lesen", str(exc))
            return
        self._future, self._stop = future, stop
        self._progress.setRange(0, len(targets))
        self._progress.setValue(0)
        self._progress.setFormat("%v von %m Geräten")
        self._progress.show()

        def done(f) -> None:
            if f.cancelled():
                bridge.links_finished.emit(None, "abgebrochen")
                return
            exc = f.exception()
            if exc is not None:
                bridge.links_finished.emit(None, str(exc) or exc.__class__.__name__)
            else:
                bridge.links_finished.emit(f.result(), "")
        future.add_done_callback(done)
        self._update_controls()

    def _on_link_read(self, tables: ds.LinkTables) -> None:
        self._tables[tables.address] = tables
        self._compare(final=False)

    def _on_links_finished(self, results, error: str) -> None:
        stopped = self._stop is not None and self._stop.is_set()
        self._future = self._stop = None
        self._progress.hide()
        for tables in results or []:
            self._tables[tables.address] = tables
        self._compare()
        read = [t for t in self._tables.values() if t.ok]
        text = (f"Tabellen gelesen: {len(read)} Geräte, "
                f"{len({ga for t in read for ga in t.group_addresses})} GAs")
        failed = len(self._tables) - len(read)
        if failed:
            text += f", {failed} nicht lesbar"
        self._summary.setText(text + (" – abgebrochen" if stopped else ""))
        if error and error != "abgebrochen":
            QMessageBox.warning(self, "GAs und Verknüpfungen lesen",
                                f"Nicht abgeschlossen: {error}")
        self._update_controls()
        # Gelesen ist noch nicht im Projekt: gleich anbieten (RekChalet1:
        # Geräte vorher übernommen, GAs danach vermisst)
        pending = self._tables_to_adopt()
        if pending and self._project is not None:
            gas = len({ga for t in pending for ga in t.group_addresses})
            answer = QMessageBox.question(
                self, "GAs und Verknüpfungen lesen",
                f"Gelesen: {gas} GAs von {len(pending)} Geräten. Sie stehen erst im Projekt, "
                "wenn sie übernommen werden.\n\nJetzt ins Projekt übernehmen (fehlende "
                "Geräte, GAs, Verknüpfungen und die Flags aus den Geräten)? Verknüpfungen "
                "im Projekt bleiben unverändert.")
            if answer == QMessageBox.Yes:
                self._adopt(confirmed=True)

    def _tables_to_adopt(self) -> list:
        """Gelesene Tabellen, die das Projekt noch nicht hat: Gerät fehlt, hat
        keine Verknüpfungen oder (Rekonstruktion ohne ETS-Projekt) andere Flags
        bei gleichen Verknüpfungen."""
        if self._project is None:
            return []
        devices = {d.physical_address: d for d in ds.project_devices(self._project)}
        from_ets = bool(getattr(self._project, "ets_project_id", ""))
        result = []
        for table in self._tables.values():
            if not table.ok or not table.links:
                continue
            device = devices.get(table.address)
            if device is None or not any(co.connected_gas
                                         for co in device.communication_objects):
                result.append(table)
            elif (not from_ets and table.flags and not ds.differences(device, table)
                  and ds.flag_differences(device, table)):
                result.append(table)
        return result

    # ── Ergebnis ─────────────────────────────────────────────────────────

    def _compare(self, final: bool = True) -> None:
        if not self._lines:
            self._rows = []
        elif final:
            self._rows = ds.compare(self._project, self._findings, self._lines, self._tables)
        else:
            # während der Suche nur Gefundenes, «antwortet nicht» erst am Schluss
            self._rows = [r for r in ds.compare(self._project, self._findings, self._lines,
                                                self._tables)
                          if r.status != ds.STATUS_MISSING]
        if not self.scanning or final:
            self._summary.setText(ds.summary(self._rows) if self._lines else "")
        self._fill_table()

    def _visible_rows(self) -> list[ds.ScanRow]:
        if self._filter.currentData() == FILTER_PROBLEMS:
            return [r for r in self._rows if r.status not in (ds.STATUS_OK, ds.STATUS_OWN)]
        return self._rows

    def _fill_table(self) -> None:
        rows = self._visible_rows()
        self._table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            color = QColor(_STATUS_COLORS.get(row.status, TEXT_MUTED))
            for column, text in enumerate(row.cells()):
                item = QTableWidgetItem(text)
                if column == 1:
                    item.setForeground(color)
                if column == len(ds.COLUMNS) - 1:
                    item.setToolTip(text)
                self._table.setItem(index, column, item)
            if row.link_details:
                more = len(row.link_details) - 30
                self._table.item(index, 7).setToolTip("\n".join(row.link_details[:30]) + (
                    f"\n… und {more} weitere" if more > 0 else ""))
            if row.finding is not None and row.finding.errors:
                self._table.item(index, 1).setToolTip("Nicht lesbar: " + ", ".join(
                    row.finding.errors[:6]))
        self._export_btn.setEnabled(bool(self._rows))

    def _adopt(self, confirmed: bool = False) -> None:
        """Gefundene Geräte ins Projekt (FA-3108a), mit Rückfrage (ausser schon
        bestätigt) und Rückgängig."""
        if self._project is None or self.scanning:
            return
        found = [f for f in self._findings if f.answered and not f.own]
        existing = {d.physical_address for d in ds.project_devices(self._project)}
        new = [f for f in found if f.address not in existing]
        # Geplantes Projekt mit Geräten: bleibt geplant (Richtlinien als Fehler)
        if existing and not self._project.topology.is_imported and QMessageBox.question(
                self, "Ins Projekt übernehmen",
                f"Dieses Projekt ist mit KNiX geplant und hat schon {len(existing)} Geräte. "
                "Die gefundenen Geräte kämen dazu, das Projekt bliebe ein geplantes Projekt: "
                "Abweichungen von den Projektrichtlinien gelten als Fehler, nicht als "
                "Hinweise.\n\nFür eine Anlage ohne Projektdatei ein neues, leeres Projekt "
                "anlegen («Bestehende Anlage aufnehmen»).\n\nTrotzdem übernehmen?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        text = (f"{len(new)} Geräte neu anlegen, {len(found) - len(new)} bestehende "
                "ergänzen (nur leere Seriennummer oder fehlendes Produkt).\n\n"
                "Produkt und Kommunikationsobjekte kommen aus dem Produktkatalog, wenn die "
                "gelesene Applikation dort steht. Bestehende Angaben werden nicht "
                "überschrieben; Abweichungen bleiben in der Liste stehen.")
        tables = list(self._tables.values())
        if tables:
            text += ("\n\nGelesene GAs und Verknüpfungen von "
                     f"{sum(1 for t in tables if t.ok)} Geräten kommen dazu – nur bei Geräten "
                     "ohne Verknüpfungen im Projekt. Die neuen GAs heissen vorläufig nach dem "
                     "KO, das sie empfängt.")
        if not existing:
            text += ("\n\nDas Projekt gilt danach als bestehende Anlage (wie aus der ETS "
                     "eingelesen).")
        if not confirmed and QMessageBox.question(
                self, "Ins Projekt übernehmen", text) != QMessageBox.Yes:
            return
        catalog = self.catalog
        if catalog is None:
            from ...services.product_sync import shared_catalog
            catalog = shared_catalog()
        # neu in den Produktordner gelegte Herstellerdateien zuerst einlesen
        from ...services import missing_products
        try:
            pending = missing_products.read_pending(catalog)
        except Exception:
            pending = missing_products.ReadResult()
        if self._bus is not None:
            self._bus.begin_change("Teilnehmer ins Projekt übernommen")
        result = ds.adopt_findings(self._project, found, catalog)
        links = ds.adopt_links(self._project, tables) if tables else None
        if result.changed or (links is not None and links.changed):
            if self._bus is not None:
                self._bus.emit_topology_changed()
                if links is not None and links.changed:
                    self._bus.emit_addresses_changed()
            self.adopted.emit()
        self._compare()
        self._update_controls()
        message = result.text()
        if pending.products:
            message = (f"{pending.products} Produkte aus neuen Herstellerdateien im "
                       "Produktordner eingelesen.\n" + message)
        if links is not None:
            message += "\n\n" + links.text()
            if links.gas_added:
                message += ("\n\nNächster Schritt: «Bedeutung ergänzen…» gibt den GAs Gewerk "
                            "und Namen nach dem Namensschema.")
        QMessageBox.information(self, "Ins Projekt übernehmen", message)

    def _open_missing_products(self) -> None:
        """Fehlende Herstellerdateien (FA-3108f); danach die Flags der
        nachgeführten Geräte lesen (Lage der KO-Tabelle aus der Datei)."""
        if self._project is None or self.scanning:
            return
        from ..dialogs.missing_products_dialog import MissingProductsDialog
        dialog = MissingProductsDialog(self._project, self._bus, self.catalog, self)
        dialog.exec()
        self._compare()
        self._update_controls()
        done = set(dialog.completed)
        if not done:
            return
        connected = self.bus_monitor is not None and self.bus_monitor.can_access_devices
        readable = [f for f in self._findings if f.address in done and ds.readable_for_links(f)]
        if connected and readable:
            if QMessageBox.question(
                    self, "Herstellerdateien",
                    f"Die Flags von {len(readable)} nachgeführten Geräten jetzt aus den "
                    "Geräten lesen? Bei manchen Geräten steht erst in der Herstellerdatei, "
                    "wo sie liegen.") == QMessageBox.Yes:
                self._read_links(only=done)
        else:
            self._summary.setText(
                f"{len(done)} Geräte nachgeführt – Flags beim nächsten Verbinden mit "
                "«GAs und Verknüpfungen lesen» nachlesen.")

    def _add_meaning(self) -> None:
        """Bedeutung der gelesenen GAs ergänzen (FA-3105b), mit Vorschau,
        Rückfrage und Rückgängig."""
        if self._project is None or self.scanning:
            return
        from ...services import ga_meaning
        proposals = [m for m in ga_meaning.propose(self._project) if m.designation]
        if not proposals:
            QMessageBox.information(self, "Bedeutung ergänzen",
                                    "Keine GAs mit vorläufigem Namen.")
            return
        sample = "\n".join(f"  {m.address}  {m.designation}" for m in proposals[:8])
        counts = ga_meaning.Counter(m.gewerk or "SF" for m in proposals)
        text = (f"{len(proposals)} GAs mit vorläufigem Namen bekommen Gewerk, Funktion und "
                "einen Namen nach dem Namensschema – an Stelle des Raums steht vorerst die "
                f"Geräteadresse. Beispiele:\n\n{sample}\n\nGewerke: "
                + ", ".join(f"{c} {n}" for c, n in counts.most_common())
                + "\n\nDazu: Mittelgruppen nach Gewerk benennen, Szenen erkennen. "
                "Namen aus der ETS bleiben unverändert.")
        if QMessageBox.question(self, "Bedeutung ergänzen", text) != QMessageBox.Yes:
            return
        if self._bus is not None:
            self._bus.begin_change("Bedeutung der GAs ergänzt")
        result = ga_meaning.apply(self._project, proposals)
        if self._bus is not None:
            self._bus.emit_addresses_changed()
        self._update_controls()
        QMessageBox.information(self, "Bedeutung ergänzen", result.text())

    def _assign_rooms(self, tour: bool = True) -> None:
        """Räume aus dem Bus (FA-3105c): Rundgang vor Ort (Raum wählen, Tasten
        drücken, Aktorkanäle bestätigen) bzw. Übersicht zum Korrigieren."""
        if self._project is None or self.scanning:
            return
        if tour and not self._project.areal.all_rooms:
            box = QMessageBox(QMessageBox.Question, "Rundgang",
                              "Das Projekt hat noch keine Räume. Bei mehreren Zonen (z.B. "
                              "Innen/Aussen, Wohnungen), Gebäudeteilen oder Gebäuden zuerst "
                              "das Gebäude erfassen; sonst lassen sich die Räume im "
                              "Rundgang anlegen.", parent=self)
            building = box.addButton("Zuerst Gebäude erfassen", QMessageBox.AcceptRole)
            box.addButton("Räume im Rundgang anlegen", QMessageBox.ActionRole)
            cancel = box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(building)
            box.exec()
            if box.clickedButton() is cancel:
                return
            if box.clickedButton() is building:
                self.navigate_requested.emit("building")
                return
        if tour:
            from ..dialogs.room_tour_dialog import RoomTourDialog
            dialog = RoomTourDialog(self._project, self.bus_monitor, self._bus, self)
        else:
            from ..dialogs.room_assign_dialog import RoomAssignDialog
            dialog = RoomAssignDialog(self._project, self.bus_monitor, self._bus, self)
        dialog.exec()
        self._compare()
        self._update_controls()

    def _export(self) -> None:
        if not self._rows:
            return
        name = (self._project.name if self._project is not None else "Anlage") or "Anlage"
        path, _ = QFileDialog.getSaveFileName(
            self, "Teilnehmer als CSV speichern", f"{name}_Teilnehmer.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            count = ds.export_csv(self._rows, path)
        except OSError as exc:
            QMessageBox.warning(self, "Als CSV speichern", f"Nicht gespeichert: {exc}")
            return
        self._summary.setText(f"{count} Zeilen gespeichert: {path}")

    def shutdown(self) -> None:
        self._cancel()
        if self._future is not None:
            self._future.cancel()
