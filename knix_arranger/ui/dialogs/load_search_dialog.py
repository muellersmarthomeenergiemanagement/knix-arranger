"""
«Lasten suchen» im Rundgang (FA-3105c): Aktorkanäle ohne Raum einzeln kurz
schalten (wie der Funktionstest FA-3104) und vor Ort fragen, ob in diesem
Raum etwas reagiert hat. Für Kanäle, die kein Taster auslöst (nur zentral,
Visualisierung, Logik). Gesendet wird erst nach der Rückfrage; Anhalten setzt
den laufenden Kanal noch zurück.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)

from ...services import room_from_bus as rb
from ..styles import TEXT_MUTED

_OK, _NO, _RUNNING = QColor("#1B5E20"), QColor(TEXT_MUTED), QColor("#1565C0")
_C_CHANNEL, _C_WHAT, _C_RESULT = range(3)
# Pause zwischen zwei Kanälen
STEP_PAUSE = 0.5


class LoadSearchDialog(QDialog):

    # Wartezeiten (Storen-Fahrt, Pause) -- Tests setzen 0
    time_scale = 1.0

    def __init__(self, project, monitor, channels: list, room_label: str,
                 preferred=(), parent=None):
        super().__init__(parent)
        self._project = project
        self._monitor = monitor
        self._room_label = room_label
        self._steps = {c.key: rb.load_probe(project, c) for c in channels}
        self._items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self.found: list[tuple[str, str]] = []
        self._running = False
        self._stop_requested = False
        self._queue: list[tuple[str, str]] = []
        self._key: tuple[str, str] | None = None
        self._actions: list = []
        self._answer: bool | None = None

        self.setWindowTitle(f"Lasten suchen – {room_label}")
        self.resize(820, 560)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Für Aktorkanäle ohne Raum, die kein Taster auslöst: KNiX schaltet jeden "
            f"markierten Kanal kurz (Licht Ein – Aus, Dimmer 50 % – 0 %, Storen Ab – Stopp "
            f"und wieder Auf – Stopp) und fragt, ob in {room_label} etwas reagiert hat. "
            "Alarm, Wetter, Tor, Türe und Fenster schaltet KNiX nie. Angehakt sind die "
            "Gewerke, die im Raum schon vorkommen.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Aktorkanal", "Ablauf", "Ergebnis"])
        self._tree.setColumnWidth(_C_CHANNEL, 330)
        self._tree.setColumnWidth(_C_WHAT, 260)
        layout.addWidget(self._tree, 1)
        self._fill(channels, set(preferred))

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._start_btn = QPushButton("Suche starten")
        self._start_btn.clicked.connect(lambda: self.start())
        self._stop_btn = QPushButton("Anhalten")
        self._stop_btn.setObjectName("secondary")
        self._stop_btn.clicked.connect(self.stop)
        self._done_btn = QPushButton("Fertig")
        self._done_btn.setObjectName("secondary")
        self._done_btn.clicked.connect(self.accept)
        buttons.addStretch(1)
        for button in (self._start_btn, self._stop_btn, self._done_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        testable = sum(1 for s in self._steps.values() if s.testable)
        self._status.setText(f"{testable} von {len(self._steps)} Kanälen ohne Raum "
                             "lassen sich schalten.")
        self._update_controls()

    def _fill(self, channels: list, preferred: set[str]) -> None:
        catalog = getattr(self._project, "gewerk_catalog", None)
        by_gewerk: dict[str, list] = {}
        for channel in channels:
            by_gewerk.setdefault(channel.gewerk or "SF", []).append(channel)
        for code in sorted(by_gewerk, key=lambda c: (c not in preferred, c)):
            gewerk = catalog.get(code) if hasattr(catalog, "get") else None
            name = (getattr(gewerk, "name", "") or code).split(" (")[0]
            parent = QTreeWidgetItem([f"{code} – {name}"])
            parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            self._tree.addTopLevelItem(parent)
            any_testable = False
            for channel in by_gewerk[code]:
                step = self._steps[channel.key]
                item = QTreeWidgetItem([channel.label, step.what(), ""])
                item.setData(0, Qt.UserRole, channel.key)
                if step.testable:
                    any_testable = True
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.Checked if code in preferred else Qt.Unchecked)
                else:
                    item.setFlags(Qt.ItemIsEnabled)
                    for column in range(3):
                        item.setForeground(column, QColor(TEXT_MUTED))
                parent.addChild(item)
                self._items[channel.key] = item
            if not any_testable:
                parent.setFlags(Qt.ItemIsEnabled)
                parent.setForeground(0, QColor(TEXT_MUTED))
            parent.setExpanded(code in preferred)

    # ── Auswahl ──────────────────────────────────────────────────────────

    def selected(self) -> list[tuple[str, str]]:
        return [key for key, item in self._items.items() if self._steps[key].testable
                and item.checkState(0) == Qt.Checked]

    def set_checked(self, keys) -> None:
        wanted = set(keys)
        for key, item in self._items.items():
            if self._steps[key].testable:
                item.setCheckState(0, Qt.Checked if key in wanted else Qt.Unchecked)

    def _update_controls(self) -> None:
        self._start_btn.setEnabled(not self._running)
        self._stop_btn.setEnabled(self._running)
        self._done_btn.setEnabled(not self._running)
        self._tree.setEnabled(not self._running)

    # ── Ablauf ───────────────────────────────────────────────────────────

    def start(self, confirmed: bool = False) -> bool:
        keys = self.selected()
        if not keys:
            QMessageBox.information(self, "Lasten suchen", "Kein Kanal markiert.")
            return False
        if not getattr(self._monitor, "connected", False):
            QMessageBox.information(
                self, "Lasten suchen",
                "Nicht mit der Anlage verbunden – im Live-Monitor «Verbinden…» wählen "
                "(USB: als Gruppenmonitor, der Busmonitor sendet nicht).")
            return False
        if not confirmed and QMessageBox.warning(
                self, "Lasten suchen",
                f"{len(keys)} Aktorkanäle werden nacheinander über den Bus geschaltet: "
                "Licht geht kurz an, Storen fahren kurz ab und wieder auf – auch in "
                "anderen Räumen.\n\nBewohner und Personen vor Ort informieren. Starten?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return False
        self._queue = keys
        self._running, self._stop_requested = True, False
        self._update_controls()
        self._next_channel()
        return True

    def stop(self) -> None:
        if self._running:
            self._stop_requested = True
            self._status.setText("Wird angehalten – der laufende Kanal wird noch "
                                 "zurückgesetzt …")

    def _finish(self, text: str) -> None:
        self._running = False
        self._key = None
        self._status.setText(text)
        self._update_controls()

    def _next_channel(self) -> None:
        if self._stop_requested or not self._queue:
            prefix = "Angehalten. " if self._stop_requested else "Fertig. "
            self._finish(prefix + (f"{len(self.found)} Kanäle haben in {self._room_label} "
                                   "reagiert – mit «Fertig» übernehmen."
                                   if self.found else "Nichts hat reagiert."))
            return
        self._key = self._queue.pop(0)
        step = self._steps[self._key]
        self._actions = rb.probe_actions(step)
        self._answer = None
        self._set_result(self._key, "läuft …", _RUNNING)
        self._tree.scrollToItem(self._items[self._key])
        self._status.setText(f"{step.label}: {step.what()}")
        self._next_action()

    def _next_action(self) -> None:
        if not self._running:
            return
        if not self._actions:
            self._channel_done()
            return
        action = self._actions.pop(0)
        if action.kind == "ask" and self._stop_requested:
            self._next_action()
        elif action.kind == "send":
            self._monitor.send_telegram(action.address, "Write", action.payload, action.size,
                                        self._sent)
        elif action.kind == "wait":
            QTimer.singleShot(int(action.seconds * 1000 * self.time_scale), self._next_action)
        elif action.kind == "ask":
            self._answer = self.ask(self._steps[self._key])
            if self._answer is None:
                self._stop_requested = True
            self._next_action()
        else:
            self._next_action()

    def _sent(self, error: str = "") -> None:
        if not error:
            self._next_action()
            return
        self._set_result(self._key, f"nicht gesendet: {error}", _NO)
        self._finish(f"Abgebrochen: {error}")

    def ask(self, step) -> bool | None:
        """Vor Ort fragen; None = anhalten."""
        box = QMessageBox(self)
        box.setWindowTitle("Lasten suchen")
        box.setText(f"Hat in {self._room_label} etwas reagiert?")
        box.setInformativeText(f"Geschaltet: {step.label} ({step.gewerk_code}) – {step.what()}")
        yes = box.addButton("Ja, in diesem Raum", QMessageBox.YesRole)
        box.addButton("Nein", QMessageBox.NoRole)
        stop = box.addButton("Anhalten", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is stop:
            return None
        return clicked is yes

    def _channel_done(self) -> None:
        key = self._key
        if self._answer is None:
            self._set_result(key, "angehalten", _NO)
        elif self._answer:
            if key not in self.found:
                self.found.append(key)
            self._set_result(key, f"reagiert in {self._room_label}", _OK)
            self._items[key].setCheckState(0, Qt.Unchecked)
        else:
            self._set_result(key, "nicht hier", _NO)
            self._items[key].setCheckState(0, Qt.Unchecked)
        QTimer.singleShot(int(STEP_PAUSE * 1000 * self.time_scale), self._next_channel)

    def _set_result(self, key, text: str, color: QColor) -> None:
        item = self._items[key]
        item.setText(_C_RESULT, text)
        item.setForeground(_C_RESULT, color)

    def reject(self) -> None:
        if self._running:
            self.stop()
            return
        super().reject()
