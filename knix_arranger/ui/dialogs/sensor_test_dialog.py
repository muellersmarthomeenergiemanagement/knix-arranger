"""
Sensorprüfung (FA-3107): mithören, ob die Sensoren senden und ihre
Messwerte plausibel sind (services/sensor_test). Ausgewertet werden auch die
Telegramme, die der Live-Monitor seit dem Verbinden empfangen hat; «Werte
abfragen» liest die GAs ohne Meldung (L-Flag).
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...services.key_test import record_device_proven
from ...services.sensor_test import (
    STATE_BAD, STATE_OK, SensorPoint, SensorSession, record_sensor_result,
)
from ..styles import TEXT_MUTED

_COLUMNS = ["Raum", "Gerät", "Objekt", "GA", "Erwartet", "Wert", "Meldungen", "Ergebnis"]
(_C_ROOM, _C_DEVICE, _C_NAME, _C_GA, _C_EXPECTED, _C_VALUE, _C_COUNT,
 _C_RESULT) = range(8)
_OK, _DEFECT = QColor("#1B5E20"), QColor("#B71C1C")
# Abstand der Leseanfragen (Buslast)
READ_INTERVAL_MS = 300


class SensorTestDialog(QDialog):
    # Ergebnisse in die Checkliste eingetragen
    recorded = Signal()

    def __init__(self, project, monitor, points: list[SensorPoint], visum: str = "",
                 parent=None):
        super().__init__(parent)
        self._project = project
        self._monitor = monitor
        self._visum = visum
        self._session = SensorSession(points)
        self._recorded_state = [""] * len(points)
        self._proven: set[str] = set()
        self._listening = False
        self._reads: list[str] = []

        self.setWindowTitle("Sensorprüfung")
        self.resize(1150, 620)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "KNiX hört mit, ob die Sensoren senden: Messwerte im plausiblen Bereich = OK, "
            "ausserhalb = Mangel; Meldungen (Alarm, Störung, Kontakt, Präsenz) zählen, "
            "sobald sie ankommen. Ausgewertet wird auch, was der Live-Monitor seit dem "
            "Verbinden empfangen hat. Viele Sensoren senden nur bei Änderung oder "
            "zyklisch – «Werte abfragen» liest die übrigen. Niemand muss vor Ort sein; "
            "ohne Meldung bleibt der Prüfpunkt offen.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        self._table = QTableWidget(len(points), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        previous = ("", "")
        for row, point in enumerate(points):
            room = point.room if point.room != previous[0] else ""
            device = point.device if (point.room, point.device) != previous else ""
            previous = (point.room, point.device)
            for column, text in ((_C_ROOM, room), (_C_DEVICE, device),
                                 (_C_NAME, point.name), (_C_GA, point.address),
                                 (_C_EXPECTED, point.expected()), (_C_VALUE, ""),
                                 (_C_COUNT, ""), (_C_RESULT, "keine Meldung")):
                item = QTableWidgetItem(text)
                if column == _C_RESULT:
                    item.setForeground(QColor(TEXT_MUTED))
                self._table.setItem(row, column, item)
        layout.addWidget(self._table, 1)

        self._status = QLabel()
        layout.addWidget(self._status)
        buttons = QHBoxLayout()
        self._read_btn = QPushButton("Werte abfragen")
        self._read_btn.setToolTip("Leseanfrage an jede GA ohne Meldung (mit L-Flag), "
                                  "nacheinander mit kurzer Pause")
        self._read_btn.clicked.connect(self.read_missing)
        close = QPushButton("Schliessen")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        buttons.addWidget(self._read_btn)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._read_timer = QTimer(self)
        self._read_timer.setInterval(READ_INTERVAL_MS)
        self._read_timer.timeout.connect(self._read_next)
        self._update_status()

    # ── Ablauf ───────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._listening:
            return
        history = getattr(self._monitor, "history", None)
        for telegram in (history() if history else []):
            self._on_telegram(telegram)
        self._monitor.add_listener(self._on_telegram)
        self._listening = True
        self._update_status()

    def stop(self) -> None:
        self._read_timer.stop()
        self._reads = []
        if self._listening:
            self._monitor.remove_listener(self._on_telegram)
            self._listening = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start()
        QTimer.singleShot(0, self._fit)

    def done(self, result: int) -> None:
        self.stop()
        super().done(result)

    def _fit(self) -> None:
        from ..column_utils import fit_columns
        fit_columns(self._table, flex=_C_RESULT)

    def _on_telegram(self, telegram) -> None:
        value = self._monitor.value_text(telegram) if telegram.payload else ""
        for row in self._session.on_telegram(telegram, value or ""):
            self._show(row)
        self._update_status()

    def read_missing(self) -> None:
        """Leseanfragen an die GAs ohne Meldung."""
        if not self._monitor.connected:
            self._status.setText("Lesen braucht eine sendefähige Verbindung "
                                 "(nicht im USB-Busmonitor).")
            return
        addresses = []
        for row in self._session.to_read():
            address = self._session.points[row].address
            if address not in addresses:
                addresses.append(address)
        self._reads = addresses
        if addresses:
            self._read_btn.setEnabled(False)
            self._read_timer.start()
        self._update_status()

    def _read_next(self) -> None:
        if not self._reads:
            self._read_timer.stop()
            self._read_btn.setEnabled(True)
            self._update_status()
            return
        address = self._reads.pop(0)
        self._monitor.send_telegram(address, "Read", "", None, lambda _error: None)
        self._update_status()

    # ── Anzeige und Eintrag ──────────────────────────────────────────────

    def _show(self, row: int) -> None:
        point = self._session.points[row]
        reading = self._session.readings[row]
        state = self._session.state[row]
        self._table.item(row, _C_VALUE).setText(reading.value)
        self._table.item(row, _C_COUNT).setText(str(reading.count) if reading.count else "")
        result = self._table.item(row, _C_RESULT)
        others = ", ".join(sorted(reading.others))
        if state in (STATE_OK, STATE_BAD):
            ok = state == STATE_OK
            text = "OK" if ok else f"Mangel · {reading.bad} ausserhalb {point.expected()}"
            if self._recorded_state[row] != state:
                self._recorded_state[row] = state
                count = record_sensor_result(self._project, point, ok,
                                             self._session.note(row), self._visum)
                if point.be_number not in self._proven:
                    self._proven.add(point.be_number)
                    count += record_device_proven(self._project, point, self._visum,
                                                  test="Sensorprüfung")
                if count:
                    self.recorded.emit()
            result.setText(text + (f" · auch von {others}" if others else ""))
            result.setForeground(_OK if ok else _DEFECT)
        elif others:
            result.setText(f"keine Meldung vom Sensor · gesendet von {others}")

    def _update_status(self) -> None:
        ok, bad, missing = self._session.summary()
        text = f"{ok} OK · {bad} unplausibel · {missing} ohne Meldung"
        if self._reads:
            text += f" · frage ab … noch {len(self._reads)}"
        self._status.setText(text)
        self._read_btn.setEnabled(not self._reads and bool(self._session.to_read())
                                  and bool(getattr(self._monitor, "connected", False)))

    def result_text(self, row: int) -> str:
        return self._table.item(row, _C_RESULT).text()
