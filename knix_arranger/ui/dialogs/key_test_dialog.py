"""
Tastentest (FA-3106): der Tester drückt im Raum die Tasten, KNiX hört über
den Live-Monitor mit und hakt die Prüfpunkte ab (services/key_test). Ohne
Status vom Aktor entscheidet der Tester mit «OK» bzw. «Mangel».
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ...services.key_test import (
    STATE_CONFIRM, STATE_DEFECT, STATE_OK, STATE_OPEN, STATE_SENT, KeyCheck, KeySession,
    record_device_proven, record_key_result,
)
from ..styles import TEXT_MUTED

_COLUMNS = ["Taster", "Taste", "Funktion", "GA", "Aktor", "Ergebnis"]
_C_BE, _C_KEY, _C_FUNCTION, _C_GA, _C_ACTUATOR, _C_RESULT = range(6)
_OK, _DEFECT, _RUNNING, _ASK = (QColor("#1B5E20"), QColor("#B71C1C"), QColor("#1565C0"),
                                QColor("#E65100"))


class KeyTestDialog(QDialog):
    # Ergebnisse in die Checkliste eingetragen
    recorded = Signal()

    def __init__(self, project, monitor, room_name: str, checks: list[KeyCheck],
                 visum: str = "", room_addresses=None, parent=None):
        super().__init__(parent)
        self._project = project
        self._monitor = monitor
        self._visum = visum
        self._session = KeySession(checks, room_addresses=room_addresses)
        self._proven: set[str] = set()      # Taster mit belegter Grundprüfung
        self._listening = False

        self.setWindowTitle(f"Tastentest – {room_name}")
        self.resize(1100, 620)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tasten in beliebiger Reihenfolge drücken. KNiX hört am Bus mit: Telegramm "
            "vom richtigen Taster auf der geplanten GA = gesendet; meldet danach der "
            "Aktor seinen Status = OK. Ohne Status entscheiden Sie vor Ort mit «OK» "
            "oder «Mangel». Ergebnisse kommen auf die Prüfpunkte der Tasten, dazu "
            "Physik. Adresse, Applikation und Kommunikation des Tasters. KNiX sendet "
            "nichts.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)
        if not project.checklists:
            hint = QLabel("Noch keine Checkliste: Die Ergebnisse stehen nur hier. "
                          "Vorher «Checkliste erstellen» wählen, damit sie eingetragen werden.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #E65100;")
            layout.addWidget(hint)

        self._next = QLabel()
        self._next.setStyleSheet("font-weight: 600; font-size: 14px;")
        self._next.setWordWrap(True)
        layout.addWidget(self._next)

        self._table = QTableWidget(len(checks), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        previous = ""
        for row, check in enumerate(checks):
            be = check.be_title if check.be_title != previous else ""
            previous = check.be_title
            actuator = ", ".join(check.actuators) or "–"
            for column, text in ((_C_BE, be), (_C_KEY, check.instruction()),
                                 (_C_FUNCTION, check.function()), (_C_GA, check.address),
                                 (_C_ACTUATOR, actuator), (_C_RESULT, "offen")):
                item = QTableWidgetItem(text)
                if column == _C_RESULT:
                    item.setForeground(QColor(TEXT_MUTED))
                self._table.setItem(row, column, item)
        self._table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        self._ok_btn = QPushButton("Reagiert – OK")
        self._ok_btn.clicked.connect(lambda: self.decide(True))
        self._defect_btn = QPushButton("Mangel")
        self._defect_btn.setObjectName("secondary")
        self._defect_btn.clicked.connect(lambda: self.decide(False))
        self._confirm_box = QCheckBox("Reaktion immer vor Ort bestätigen")
        self._confirm_box.setToolTip(
            "Auch mit Status vom Aktor fragen – der Status zeigt nur, dass der Kanal "
            "geschaltet hat.")
        self._confirm_box.toggled.connect(self._set_confirm)
        close = QPushButton("Schliessen")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        for widget in (self._ok_btn, self._defect_btn):
            buttons.addWidget(widget)
        buttons.addStretch()
        buttons.addWidget(self._confirm_box)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        findings_label = QLabel("Befunde (unerwartete Telegramme)")
        findings_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(findings_label)
        self._findings = QListWidget()
        self._findings.setMaximumHeight(90)
        layout.addWidget(self._findings)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._update_next()
        self._update_buttons()

    # ── Ablauf ───────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._listening:
            self._monitor.add_listener(self._on_telegram)
            self._listening = True
            self._timer.start()

    def stop(self) -> None:
        if self._listening:
            self._monitor.remove_listener(self._on_telegram)
            self._listening = False
            self._timer.stop()

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

    def _set_confirm(self, checked: bool) -> None:
        self._session.confirm = checked

    def _on_telegram(self, telegram) -> None:
        value = self._monitor.value_text(telegram) if telegram.service == "Write" else ""
        event = self._session.on_telegram(telegram, time.monotonic(), value or "")
        for row in event.rows:
            self._show(row)
        if event.finding:
            self._findings.addItem(f"{time.strftime('%H:%M:%S')}  {event.finding}")
            self._findings.scrollToBottom()
        if event.rows:
            self._update_next()

    def _tick(self) -> None:
        for row in self._session.tick(time.monotonic()):
            self._show(row)

    def decide(self, ok: bool) -> None:
        """«OK»/«Mangel» für die markierten Prüfpunkte."""
        rows = sorted({i.row() for i in self._table.selectedIndexes()})
        for row in rows:
            self._session.decide(row, ok)
            self._show(row)
        self._update_next()

    # ── Anzeige und Eintrag ──────────────────────────────────────────────

    def _show(self, row: int) -> None:
        state = self._session.state[row]
        check = self._session.checks[row]
        note = self._session.note[row]
        detail = note.split(": ", 1)[1] if ": " in note else note
        if state != STATE_OPEN and check.be_number not in self._proven:
            self._proven.add(check.be_number)
            if record_device_proven(self._project, check, self._visum):
                self.recorded.emit()
        if state == STATE_SENT:
            value = self._session.value[row]
            self._set_result(row, f"gesendet{' = ' + value if value else ''} – "
                                  "warte auf Aktor …", _RUNNING)
        elif state == STATE_CONFIRM:
            self._set_result(row, f"{detail} – reagiert? OK oder Mangel", _ASK)
            self._table.selectRow(row)
            self._update_next()
        elif state in (STATE_OK, STATE_DEFECT):
            ok = state == STATE_OK
            count = record_key_result(self._project, check, ok, note, self._visum)
            if count:
                self.recorded.emit()
            text = ("OK" if ok else "Mangel") + " · " + detail
            text += " · in der Checkliste" if count else " · nicht in der Checkliste"
            self._set_result(row, text, _OK if ok else _DEFECT)
        self._update_buttons()

    def _set_result(self, row: int, text: str, color: QColor) -> None:
        item = self._table.item(row, _C_RESULT)
        item.setText(text)
        item.setForeground(color)

    def _update_next(self) -> None:
        ask = next((i for i, s in enumerate(self._session.state) if s == STATE_CONFIRM), None)
        if ask is not None:
            check = self._session.checks[ask]
            self._next.setText(f"Hat «{check.function() or check.address}» reagiert? "
                               "«Reagiert – OK» oder «Mangel».")
            return
        row = self._session.next_open()
        if row is None:
            done = sum(s in (STATE_OK, STATE_DEFECT) for s in self._session.state)
            self._next.setText(f"Alle Tasten gedrückt – {done} von "
                               f"{len(self._session.checks)} Prüfpunkten erledigt.")
            return
        check = self._session.checks[row]
        self._next.setText(f"Als Nächstes: Taster {check.be_number} – "
                           f"{check.instruction()} ({check.function() or check.address})")

    def _update_buttons(self) -> None:
        has = bool(self._table.selectedIndexes())
        self._ok_btn.setEnabled(has)
        self._defect_btn.setEnabled(has)

    def result_text(self, row: int) -> str:
        return self._table.item(row, _C_RESULT).text()
