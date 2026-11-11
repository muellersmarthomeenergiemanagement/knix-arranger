"""
Live-Monitor (FA-3102a, FA-3103): Gruppentelegramme der Anlage in Echtzeit,
mit Bezeichnung, Wert nach DPT, Gewerk, Raum und Stockwerk aus dem Projekt;
filtern, anhalten, als CSV speichern. Liest nur (services/bus_access).
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QObject, QSortFilterProxyModel, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableView, QVBoxLayout, QWidget,
)

from ...services.bus_access import (
    COLUMNS, MAX_ROWS, STATE_CONNECTED, STATE_CONNECTING, STATE_DISCONNECTED, STATE_ERROR,
    BusConnection, ConnectionSettings, MonitorContext, MonitorRow, export_csv, row_matches,
)
from ..styles import TEXT_MUTED

# rohe Rahmen für die Busanalyse: so viele höchstens (rund ein Tag in einem
# Einfamilienhaus), ältere fallen weg
MAX_RAW_FRAMES = 500_000

_UNKNOWN_COLOR = QColor("#E65100")     # GA nicht im Projekt


class _Bridge(QObject):
    """Rückrufe aus dem Verbindungs-Thread in den Hauptthread."""
    telegram = Signal(object)
    state = Signal(str, str)
    raw = Signal(str, object)


class MonitorModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[MonitorRow] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        row = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return row.cells()[index.column()]
        if role == Qt.ForegroundRole and not row.known and index.column() in (2, 3):
            return _UNKNOWN_COLOR
        if role == Qt.ToolTipRole and not row.known and index.column() in (2, 3):
            return "GA nicht im Projekt"
        if role == Qt.ToolTipRole and index.column() == 5 and row.dpt:
            return f"{row.dpt} · Daten {row.telegram.payload or '–'}"
        return None

    def append(self, rows: list[MonitorRow]) -> None:
        if not rows:
            return
        overflow = len(self.rows) + len(rows) - MAX_ROWS
        if overflow > 0:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            del self.rows[:overflow]
            self.endRemoveRows()
        start = len(self.rows)
        self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
        self.rows.extend(rows)
        self.endInsertRows()

    def refresh_tail(self, rows: int = 50) -> None:
        """Letzte Zeilen neu zeichnen: die Quittung (Busmonitor) trifft erst
        nach ihrem Telegramm ein und wird dort nachgetragen."""
        if self.rows:
            last = len(self.rows) - 1
            column = len(COLUMNS) - 1
            self.dataChanged.emit(self.index(max(0, last - rows), column),
                                  self.index(last, column))

    def clear(self) -> None:
        self.beginResetModel()
        self.rows = []
        self.endResetModel()


class MonitorFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = self.gewerk = self.floor = ""

    def set_filter(self, query: str, gewerk: str, floor: str) -> None:
        # Qt ab 6.10: begin/endFilterChange statt des veralteten invalidateFilter
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            self.query, self.gewerk, self.floor = query, gewerk, floor
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.query, self.gewerk, self.floor = query, gewerk, floor
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        row = self.sourceModel().rows[source_row]
        return row_matches(row, self.query, self.gewerk, self.floor)


class LiveMonitorView(QWidget):
    # Verbindungseinstellungen geändert (Projekt ungespeichert)
    settings_changed = Signal()
    # Aufzeichnung als Mitschnitt in die Busanalyse übernommen
    recording_added = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._bus = None
        self._context: MonitorContext | None = None
        self._pending: list = []
        # rohe Rahmen (Hex, Zeit) für die Busanalyse, unabhängig von Filter
        # und Anhalten; Verbindung, über die sie kamen
        self._raw: list[tuple[str, object]] = []
        self._connection_label = ""
        self._paused = False
        self._held: list = []
        self._state = STATE_DISCONNECTED
        self._bridge = _Bridge()
        # gebundene Methoden: Qt stellt die Signale aus dem Verbindungs-
        # Thread in den Hauptthread zu (Queued Connection)
        self._bridge.telegram.connect(self._on_telegram)
        self._bridge.state.connect(self._on_state)
        self._bridge.raw.connect(self._on_raw)
        self._connection = BusConnection(self._bridge.telegram.emit, self._bridge.state.emit,
                                         self._bridge.raw.emit)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._flush)

        layout = QVBoxLayout(self)
        title = QLabel("Live-Monitor")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Gruppentelegramme der Anlage in Echtzeit, mit Bezeichnung, Wert, Gewerk, Raum "
            "und Stockwerk aus dem Projekt. KNiX verbindet sich über KNXnet/IP (Tunnel, "
            "Secure-Tunnel, Routing) oder eine USB-Schnittstelle und sendet nichts. Der "
            "USB-Busmonitor zeigt zusätzlich Quittungen und Wiederholungen. Orange: GA "
            "nicht im Projekt.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._connect_btn = QPushButton("Verbinden…")
        self._connect_btn.clicked.connect(self._connect)
        self._disconnect_btn = QPushButton("Trennen")
        self._disconnect_btn.setObjectName("secondary")
        self._disconnect_btn.clicked.connect(self._disconnect)
        self._status = QLabel()
        self._analysis_btn = QPushButton("In Busanalyse übernehmen")
        self._analysis_btn.setObjectName("secondary")
        self._analysis_btn.setToolTip(
            "Die ganze Aufzeichnung (ohne Filter) als Mitschnitt in die Busanalyse: "
            "Absender, fehlende Verknüpfungen, unbekannte GAs, Datenlänge, Buslast usw. "
            "Wiederholungen und Quittungen enthält nur ein Busmonitor-Mitschnitt.")
        self._analysis_btn.clicked.connect(self._to_analysis)
        row.addWidget(self._connect_btn)
        row.addWidget(self._disconnect_btn)
        row.addWidget(self._status, 1)
        row.addWidget(self._analysis_btn)
        layout.addLayout(row)
        # Zähler der Verbindung: wohin die Rahmen gingen (fehlende Telegramme)
        self._stats = QLabel()
        self._stats.setStyleSheet(f"color: {TEXT_MUTED};")
        self._stats.setToolTip(
            "Rahmen von der Schnittstelle und was daraus wurde. Gerätezugriffe (z.B. "
            "ETS programmiert) zeigt der Gruppenmonitor nicht. Gesichert ohne Schlüssel: "
            "Schlüsseldatei der ETS beim Verbinden angeben. Verloren (Folgenummer) und "
            "Neuverbindungen: Pakete auf dem Weg verloren, typisch über Internet/VPN. "
            "Telegramme anderer Linien sieht die Schnittstelle nur, wenn der "
            "Linienkoppler sie durchlässt.")
        layout.addWidget(self._stats)
        # GAs, die über diese Schnittstelle nie ankommen (Koppler sperrt)
        hidden_row = QHBoxLayout()
        self._hidden = QLabel()
        self._hidden.setWordWrap(True)
        self._hidden.setStyleSheet("color: #1565C0;")
        self._hidden_btn = QPushButton("Liste…")
        self._hidden_btn.setObjectName("secondary")
        self._hidden_btn.clicked.connect(self._show_hidden)
        hidden_row.addWidget(self._hidden, 1)
        hidden_row.addWidget(self._hidden_btn)
        layout.addLayout(hidden_row)
        self._visibility = None
        self._hidden.hide()
        self._hidden_btn.hide()

        filters = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Suchen: GA, Adresse, Bezeichnung, Raum, Wert "
                                        "(z.B. 1/2 Küche)")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        self._gewerk = QComboBox()
        self._gewerk.setToolTip("Gewerk")
        self._gewerk.currentIndexChanged.connect(self._apply_filter)
        self._floor = QComboBox()
        self._floor.setToolTip("Stockwerk")
        self._floor.currentIndexChanged.connect(self._apply_filter)
        self._pause_btn = QPushButton("Anhalten")
        self._pause_btn.setObjectName("secondary")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setToolTip("Anzeige anhalten; Telegramme werden weiter aufgezeichnet")
        self._pause_btn.toggled.connect(self._toggle_pause)
        self._clear_btn = QPushButton("Leeren")
        self._clear_btn.setObjectName("secondary")
        self._clear_btn.clicked.connect(self._clear)
        self._export_btn = QPushButton("Als CSV speichern…")
        self._export_btn.setObjectName("secondary")
        self._export_btn.clicked.connect(self._export)
        self._count = QLabel()
        self._count.setStyleSheet(f"color: {TEXT_MUTED};")
        filters.addWidget(self._search, 3)
        filters.addWidget(self._gewerk, 1)
        filters.addWidget(self._floor, 1)
        for widget in (self._pause_btn, self._clear_btn, self._export_btn, self._count):
            filters.addWidget(widget)
        layout.addLayout(filters)

        self._model = MonitorModel(self)
        self._proxy = MonitorFilter(self)
        self._proxy.setSourceModel(self._model)
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((95, 220, 70, 300, 100, 110, 170, 140, 120)):
            self._table.setColumnWidth(column, width)
        layout.addWidget(self._table, 1)
        self._update_controls()

    # ── Projekt ──────────────────────────────────────────────────────────

    def set_bus(self, bus) -> None:
        self._bus = bus

    def set_project(self, project) -> None:
        if project is not self._project and self._connection.running:
            self._connection.stop()       # anderes Projekt = andere Anlage
        self._project = project
        self._context = MonitorContext(project) if project is not None else None
        self._fill_filters()
        self._update_controls()

    def showEvent(self, event) -> None:
        """Zuordnung zum Projekt beim Anzeigen auffrischen (GAs, Räume und
        Topologie können sich inzwischen geändert haben)."""
        super().showEvent(event)
        if self._project is not None:
            self._context = MonitorContext(self._project)
            self._fill_filters()

    def _fill_filters(self) -> None:
        context = self._context
        for combo, values, empty in (
                (self._gewerk, context.gewerk.values() if context else [], "Alle Gewerke"),
                (self._floor, context.floor.values() if context else [], "Alle Stockwerke")):
            current = combo.currentData()
            items = sorted({part.strip() for v in values for part in v.split(",") if part})
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(empty, "")
            for item in items:
                combo.addItem(item, item.split(" ")[0] if combo is self._gewerk else item)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)
            from ..column_utils import widen_popup
            widen_popup(combo)

    # ── Verbindung ───────────────────────────────────────────────────────

    def _connect(self) -> None:
        if self._project is None:
            return
        from ..dialogs.bus_connection_dialog import BusConnectionDialog
        settings = ConnectionSettings.from_dict(self._project.bus_connection)
        dialog = BusConnectionDialog(settings, self)
        if dialog.exec() != BusConnectionDialog.Accepted:
            return
        settings = dialog.settings()
        if settings.to_dict() != self._project.bus_connection:
            self._project.bus_connection = settings.to_dict()
            self.settings_changed.emit()
        self._connection_label = settings.label()
        try:
            self._connection.start(settings, dialog.secrets())
        except Exception as exc:     # z.B. Schlüsseldatei fehlt
            QMessageBox.warning(self, "Verbinden", f"Verbindung nicht möglich:\n{exc}")
            return
        self._timer.start()
        self._update_controls()

    def _disconnect(self) -> None:
        self._connection.stop()
        self._on_state(STATE_DISCONNECTED, "")

    def shutdown(self) -> None:
        """Beim Schliessen des Programms."""
        self._connection.stop(timeout=2.0)

    def _on_state(self, state: str, text: str) -> None:
        if state == STATE_DISCONNECTED and self._state == STATE_ERROR:
            return          # Fehlermeldung stehen lassen
        if state == STATE_CONNECTED:
            self._update_visibility(self._connection.local_address)
        self._state = state
        labels = {STATE_CONNECTING: ("Verbinde mit {} …", "#1565C0"),
                  STATE_CONNECTED: ("Verbunden: {}", "#2E7D32"),
                  STATE_DISCONNECTED: ("Nicht verbunden", TEXT_MUTED),
                  STATE_ERROR: ("Fehler: {}", "#C62828")}
        label, color = labels.get(state, ("{}", TEXT_MUTED))
        self._status.setText(label.format(text))
        self._status.setStyleSheet(f"color: {color};")
        if state in (STATE_DISCONNECTED, STATE_ERROR) and not self._connection.running:
            self._flush()
            self._timer.stop()
        self._update_controls()

    def _update_controls(self) -> None:
        running = self._connection.running
        self._connect_btn.setEnabled(self._project is not None and not running)
        self._disconnect_btn.setEnabled(running)
        self._export_btn.setEnabled(bool(self._model.rows))
        self._analysis_btn.setEnabled(bool(self._raw))
        if not self._status.text():
            self._status.setText("Nicht verbunden")
            self._status.setStyleSheet(f"color: {TEXT_MUTED};")

    # ── Anzeige ──────────────────────────────────────────────────────────

    def _on_telegram(self, telegram) -> None:
        self._pending.append(telegram)

    def _on_raw(self, raw: str, when) -> None:
        self._raw.append((raw, when))
        if len(self._raw) > MAX_RAW_FRAMES:
            del self._raw[:len(self._raw) - MAX_RAW_FRAMES]

    def _show_stats(self) -> None:
        stats = self._connection.stats
        if not stats.frames and not stats.reconnects:
            return
        self._stats.setText(stats.text())
        self._stats.setStyleSheet(f"color: {'#E65100' if stats.lossy else TEXT_MUTED};")

    def _flush(self) -> None:
        self._show_stats()
        self._model.refresh_tail()
        if not self._pending or self._context is None:
            return
        telegrams, self._pending = self._pending, []
        rows = [self._context.row(t) for t in telegrams]
        if self._paused:
            self._held.extend(rows)
        else:
            self._add(rows)
        self._update_count()

    def _add(self, rows: list[MonitorRow]) -> None:
        bar = self._table.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        self._model.append(rows)
        if at_end:
            self._table.scrollToBottom()
        self._update_controls()

    def _toggle_pause(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("Fortsetzen" if paused else "Anhalten")
        if not paused and self._held:
            held, self._held = self._held, []
            self._add(held)
        self._update_count()

    def _clear(self) -> None:
        self._model.clear()
        self._held = []
        self._raw = []
        self._update_count()
        self._update_controls()

    def _apply_filter(self) -> None:
        self._proxy.set_filter(self._search.text(), self._gewerk.currentData() or "",
                               self._floor.currentData() or "")
        self._update_count()

    def _update_count(self) -> None:
        total = len(self._model.rows)
        shown = self._proxy.rowCount()
        text = f"{shown} von {total}" if shown != total else f"{total} Telegramme"
        if self._held:
            text += f" · {len(self._held)} angehalten"
        self._count.setText(text)

    def _export(self) -> None:
        from ..license_gate import get_save_file_name
        path, _ = get_save_file_name(self, "Aufzeichnung speichern", "Live-Monitor.csv",
                                     "CSV (*.csv)")
        if not path:
            return
        rows = [self._model.rows[self._proxy.mapToSource(self._proxy.index(r, 0)).row()]
                for r in range(self._proxy.rowCount())]
        try:
            count = export_csv(rows, path)
        except OSError as exc:
            QMessageBox.warning(self, "Speichern", f"Datei nicht speicherbar:\n{exc}")
            return
        QMessageBox.information(self, "Gespeichert", f"{count} Telegramme gespeichert.")

    def _to_analysis(self) -> None:
        """Aufzeichnung als Mitschnitt in die Busanalyse (FA-640)."""
        if self._project is None or not self._raw:
            return
        from ...services.bus_access import live_recording
        from ...services.bus_monitor import BusLogError
        try:
            summary = live_recording(list(self._raw), connection=self._connection_label)
        except BusLogError as exc:
            QMessageBox.warning(self, "In Busanalyse übernehmen", str(exc))
            return
        if self._bus:
            self._bus.begin_change(f"Live-Aufzeichnung {summary['file']} in die Busanalyse")
        self._project.bus_recordings.append(summary)
        if self._bus:
            self._bus.any_change.emit("bus_recordings")
        self.recording_added.emit()
        QMessageBox.information(
            self, "In Busanalyse übernommen",
            f"{summary['telegrams']} Telegramme als Mitschnitt «{summary['file']}» übernommen. "
            "Die Auswertung steht unter Bestand & Umbau › Busanalyse.")

    # ── Nicht sichtbare GAs ──────────────────────────────────────────────

    def _update_visibility(self, address: str) -> None:
        from ...services.bus_access import visibility
        try:
            self._visibility = visibility(self._project, address)
        except Exception:
            self._visibility = None
        text = self._visibility.text() if self._visibility else ""
        self._hidden.setText(text)
        self._hidden.setToolTip(
            "Die ETS trägt eine GA nur in die Filtertabelle eines Kopplers ein, wenn sie "
            "auch ausserhalb seiner Linie verknüpft ist. Sehen: Schnittstelle auf der "
            "anderen Linie verwenden, den Koppler für die Fehlersuche auf «weiterleiten» "
            "stellen oder die GAs auf dieser Linie mit einem Dummy verknüpfen.")
        self._hidden.setVisible(bool(text))
        self._hidden_btn.setVisible(bool(text))

    def _show_hidden(self) -> None:
        if not self._visibility or not self._visibility.hidden:
            return
        gas = self._context.gas if self._context else {}
        lines = []
        for couplers, addresses in self._visibility.by_coupler().items():
            lines.append(f"Gesperrt durch {couplers}:")
            for address in addresses:
                ga = gas.get(address)
                name = " ".join((ga.designation or "").split()) if ga else ""
                lines.append(f"  {address}  {name}".rstrip())
        box = QMessageBox(self)
        box.setWindowTitle(f"Nicht sichtbar auf Linie {self._visibility.line}")
        box.setText(self._visibility.text())
        box.setDetailedText("\n".join(lines))
        box.exec()

