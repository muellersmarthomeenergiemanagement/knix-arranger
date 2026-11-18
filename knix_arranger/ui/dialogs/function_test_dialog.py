"""
Geführter Funktionstest (FA-3104): die geplanten Schritte (services/
function_test) nacheinander über den Live-Monitor ausführen, auf die
Rückmeldung warten und das Ergebnis in die Inbetriebnahme-Checkliste
eintragen. Jederzeit anhaltbar; gesendet wird erst nach der Rückfrage.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ...services.function_test import (
    STEP_PAUSE, Action, TestStep, feedback_matches, record_result,
)
from ..styles import TEXT_MUTED

_COLUMNS = ["", "Raum", "Objekt", "Element", "Aktor", "Prüfung", "Rückmeldung", "Ergebnis"]
(_C_CHECK, _C_ROOM, _C_PLACE, _C_LABEL, _C_ACTUATOR, _C_WHAT, _C_FEEDBACK,
 _C_RESULT) = range(8)
_OK, _DEFECT, _RUNNING = QColor("#1B5E20"), QColor("#B71C1C"), QColor("#1565C0")
# nach «keine Rückmeldung» so lange auf die Antwort einer Leseanfrage warten
READ_WAIT = 2.0


class FunctionTestDialog(QDialog):
    # Ergebnisse in die Checkliste eingetragen
    recorded = Signal()

    def __init__(self, project, monitor, steps: list[TestStep], visum: str = "",
                 parent=None):
        super().__init__(parent)
        self._project = project
        self._monitor = monitor
        self._steps = steps
        self._visum = visum
        self._running = False
        self._stop_requested = False
        self._queue: list[int] = []
        self._index = -1
        self._actions: list = []
        self._feedback = ""            # beobachtete Rückmelde-GA des laufenden Schritts
        self._expect = ""
        self._seen = ""                # Wert der passenden Rückmeldung
        self._read_sent = False
        self._answer: bool | None = None
        self._interrupted = False
        self._deadline = 0.0
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._check_feedback)

        self.setWindowTitle("Funktionstest")
        self.resize(1100, 560)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "KNiX löst jedes markierte Element aus und wartet auf die Rückmeldung des "
            "Aktors: Licht Ein – Aus, Dimmer 50 % – 0 %, Storen Ab – 2 s – Stopp und "
            "wieder Auf – 2 s – Stopp. «Objekt» und «Aktor» zeigen, was vor Ort "
            "reagieren muss und an welchem Kanal es hängt. Ohne Rückmelde-GA fragt "
            "KNiX immer, ob das Objekt reagiert hat. Das Ergebnis kommt mit Datum und Visum in die Checkliste, "
            "Gruppe «Aktorkanäle» des Raums (die Tasten prüft man am Taster). "
            "Alarm, Wetterstation, Tor, Türe und Fenster löst KNiX nie aus.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)
        if not project.checklists:
            hint = QLabel("Noch keine Checkliste: Die Ergebnisse stehen nur hier. "
                          "Vorher «Checkliste erstellen» wählen, damit sie eingetragen werden.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #E65100;")
            layout.addWidget(hint)

        self._table = QTableWidget(len(steps), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        for row, step in enumerate(steps):
            check = QTableWidgetItem()
            if step.testable:
                check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check.setCheckState(Qt.Checked)
            else:
                check.setFlags(Qt.NoItemFlags)
            self._table.setItem(row, _C_CHECK, check)
            feedback = step.feedback or ("vor Ort bestätigen" if step.testable else "")
            for column, text in ((_C_ROOM, step.room), (_C_PLACE, step.place),
                                 (_C_LABEL, step.code), (_C_ACTUATOR, step.actuator),
                                 (_C_WHAT, step.what()), (_C_FEEDBACK, feedback),
                                 (_C_RESULT, "")):
                item = QTableWidgetItem(text)
                if not step.testable:
                    item.setForeground(QColor(TEXT_MUTED))
                self._table.setItem(row, column, item)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        layout.addWidget(self._table, 1)

        self._confirm_box = QCheckBox("Jedes Objekt vor Ort bestätigen (auch mit Rückmeldung)")
        self._confirm_box.setChecked(True)
        self._confirm_box.setToolTip(
            "Die Rückmeldung zeigt nur, dass der Aktorkanal geschaltet hat. Ob das "
            "richtige Objekt reagiert (Lasten nicht vertauscht), sieht man nur vor Ort.")
        layout.addWidget(self._confirm_box)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._all_btn = QPushButton("Alle")
        self._all_btn.setObjectName("secondary")
        self._all_btn.clicked.connect(lambda: self._check_all(True))
        self._none_btn = QPushButton("Keine")
        self._none_btn.setObjectName("secondary")
        self._none_btn.clicked.connect(lambda: self._check_all(False))
        self._start_btn = QPushButton("Test starten")
        self._start_btn.clicked.connect(self.start)
        self._stop_btn = QPushButton("Anhalten")
        self._stop_btn.setObjectName("secondary")
        self._stop_btn.clicked.connect(self.stop)
        self._close_btn = QPushButton("Schliessen")
        self._close_btn.setObjectName("secondary")
        self._close_btn.clicked.connect(self.reject)
        buttons.addWidget(self._all_btn)
        buttons.addWidget(self._none_btn)
        buttons.addStretch()
        for button in (self._start_btn, self._stop_btn, self._close_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._update_controls()
        testable = sum(s.testable for s in steps)
        self._status.setText(f"{testable} von {len(steps)} Elementen automatisch prüfbar.")

    def _fit(self) -> None:
        """Spalten nach Inhalt, «Ergebnis» nimmt den Rest der Breite."""
        from ..column_utils import fit_columns
        fit_columns(self._table, flex=_C_RESULT)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._fit)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    # ── Auswahl ──────────────────────────────────────────────────────────

    def _check_all(self, checked: bool) -> None:
        for row, step in enumerate(self._steps):
            if step.testable:
                self._table.item(row, _C_CHECK).setCheckState(
                    Qt.Checked if checked else Qt.Unchecked)

    def selected_rows(self) -> list[int]:
        return [row for row, step in enumerate(self._steps) if step.testable
                and self._table.item(row, _C_CHECK).checkState() == Qt.Checked]

    def _update_controls(self) -> None:
        self._start_btn.setEnabled(not self._running)
        self._stop_btn.setEnabled(self._running)
        self._close_btn.setEnabled(not self._running)
        self._all_btn.setEnabled(not self._running)
        self._none_btn.setEnabled(not self._running)

    # ── Ablauf ───────────────────────────────────────────────────────────

    def start(self, confirmed: bool = False) -> bool:
        rows = self.selected_rows()
        if not rows:
            QMessageBox.information(self, "Funktionstest", "Kein Element markiert.")
            return False
        if not self._monitor.connected:
            QMessageBox.information(
                self, "Funktionstest",
                "Nicht mit der Anlage verbunden – im Live-Monitor «Verbinden…» wählen "
                "(USB: als Gruppenmonitor, der Busmonitor sendet nicht).")
            return False
        if not confirmed:
            rooms = len({self._steps[r].room_id for r in rows})
            answer = QMessageBox.warning(
                self, "Funktionstest starten",
                f"{len(rows)} Elemente in {rooms} Räumen werden über den Bus ausgelöst: "
                "Licht geht an und wieder aus, Storen fahren kurz ab und wieder auf.\n\n"
                "Bewohner und Personen vor Ort informieren. Test starten?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return False
        self._queue = rows
        self._running, self._stop_requested = True, False
        self._monitor.add_listener(self._on_telegram)
        self._update_controls()
        self._next_step()
        return True

    def stop(self) -> None:
        """Anhalten: das laufende Element wird noch zurückgesetzt (Aus,
        Storen gestoppt), dann endet der Test."""
        if self._running:
            self._stop_requested = True
            self._status.setText("Wird angehalten – das laufende Element wird noch "
                                 "zurückgesetzt …")

    def _finish(self, text: str) -> None:
        self._running = False
        self._poll.stop()
        self._monitor.remove_listener(self._on_telegram)
        self._status.setText(text)
        self._update_controls()

    def _next_step(self) -> None:
        if self._stop_requested or not self._queue:
            done = sum(1 for r in range(len(self._steps))
                       if self._table.item(r, _C_RESULT).data(Qt.UserRole) is not None)
            self._finish(("Angehalten. " if self._stop_requested else "Fertig. ")
                         + f"{done} Elemente geprüft.")
            return
        self._index = self._queue.pop(0)
        step = self._steps[self._index]
        self._actions = step.actions()
        self._confirm = bool(step.feedback) and self._confirm_box.isChecked()
        if self._confirm:
            # nach dem Warten auf die Rückmeldung vor Ort fragen, dann zurücksetzen
            at = next(i for i, a in enumerate(self._actions) if a.kind == "feedback")
            self._actions.insert(at + 1, Action("ask"))
        self._feedback, self._expect, self._seen = step.feedback, "", ""
        self._read_sent, self._answer, self._interrupted = False, None, False
        self._set_result(self._index, "läuft …", _RUNNING)
        self._table.scrollToItem(self._table.item(self._index, _C_ROOM))
        actuator = f" · Aktor {step.actuator}" if step.actuator else ""
        self._status.setText(f"{step.room} · {step.title()}{actuator}: {step.what()}")
        self._next_action()

    def _next_action(self) -> None:
        if not self._running:
            return
        if not self._actions:
            self._step_done()
            return
        action = self._actions.pop(0)
        if self._stop_requested and action.kind in ("feedback", "ask"):
            # angehalten: nicht mehr prüfen, aber zurücksetzen (Aus, Stopp)
            self._interrupted = True
            self._next_action()
            return
        if action.kind == "send":
            self._monitor.send_telegram(action.address, "Write", action.payload, action.size,
                                        lambda error: self._sent(error))
        elif action.kind == "wait":
            QTimer.singleShot(int(action.seconds * 1000), self._next_action)
        elif action.kind == "feedback":
            self._expect = action.expect
            self._deadline = time.monotonic() + action.seconds
            self._poll.start()
            self._check_feedback()
        elif action.kind == "ask":
            self._ask()

    def _sent(self, error: str) -> None:
        if not error:
            self._next_action()
            return
        self._set_result(self._index, f"nicht gesendet: {error}", _DEFECT)
        self._finish(f"Abgebrochen: {error}")

    def _on_telegram(self, telegram) -> None:
        if (self._running and self._feedback and not self._seen
                and telegram.destination == self._feedback
                and feedback_matches(self._expect or "", telegram)):
            self._seen = self._monitor.value_text(telegram) or "Meldung"

    def _check_feedback(self) -> None:
        if self._seen:
            self._poll.stop()
            self._next_action()
            return
        if self._stop_requested:
            # angehalten: Warten abbrechen, kein Ergebnis eintragen
            self._interrupted = True
            self._poll.stop()
            self._next_action()
            return
        if time.monotonic() < self._deadline:
            return
        if not self._read_sent:
            # keine Meldung (z.B. Zustand schon so): Rückmelde-GA lesen
            self._read_sent = True
            self._deadline = time.monotonic() + READ_WAIT
            self._monitor.send_telegram(self._feedback, "Read", "", None, lambda _e: None)
            return
        self._poll.stop()
        self._next_action()

    def _ask(self) -> None:
        step = self._steps[self._index]
        box = QMessageBox(self)
        box.setWindowTitle("Funktionstest")
        box.setText(f"Hat «{step.place or step.code}» in {step.room} reagiert?")
        details = [f"Element {step.code}: {step.what()}"]
        if step.actuator:
            details.append(f"Aktor {step.actuator}")
        details.append("Hat ein anderes Objekt reagiert: «Nein» – Kanäle vertauscht.")
        box.setInformativeText("\n".join(details))
        yes = box.addButton("Ja", QMessageBox.YesRole)
        box.addButton("Nein", QMessageBox.NoRole)
        stop = box.addButton("Anhalten", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is stop:
            self._stop_requested = True
            self._answer = None
        else:
            self._answer = clicked is yes
        self._next_action()

    def _step_done(self) -> None:
        step = self._steps[self._index]
        asked = self._confirm or not step.feedback
        if self._interrupted or (asked and self._answer is None):
            self._set_result(self._index, "angehalten – nicht eingetragen", None)
            QTimer.singleShot(0, self._next_step)
            return
        on_site = ("vor Ort bestätigt" if self._answer
                   else "vor Ort falsches oder kein Objekt")
        if not step.feedback:
            ok, note = self._answer, f"Funktionstest: {on_site}"
        elif self._seen:
            ok = self._answer if self._confirm else True
            note = f"Funktionstest: Rückmeldung {step.feedback} = {self._seen}"
            if self._confirm:
                note += f", {on_site}"
        else:
            ok = False
            note = f"Funktionstest: keine Rückmeldung auf {step.feedback}"
            if self._confirm:
                note += f", {on_site}"
        count = record_result(self._project, step, ok, note, self._visum)
        if count:
            self.recorded.emit()
        text = ("OK" if ok else "Mangel") + " · " + note.split(": ", 1)[1]
        text += " · in der Checkliste" if count else " · ohne Checkliste, nicht eingetragen"
        self._set_result(self._index, text, _OK if ok else _DEFECT, ok)
        QTimer.singleShot(int(STEP_PAUSE * 1000), self._next_step)

    def _set_result(self, row: int, text: str, color: QColor | None,
                    ok: bool | None = None) -> None:
        item = self._table.item(row, _C_RESULT)
        item.setText(text)
        item.setForeground(color or QColor(TEXT_MUTED))
        item.setData(Qt.UserRole, ok)

    def result_of(self, row: int) -> bool | None:
        return self._table.item(row, _C_RESULT).data(Qt.UserRole)

    def reject(self) -> None:
        if self._running:
            self.stop()
            return
        super().reject()
