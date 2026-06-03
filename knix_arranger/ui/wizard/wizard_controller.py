"""
13-Schritt-Wizard Steuerung (FA-1002)
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QStackedWidget, QProgressBar, QWidget, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from .step01_building import Step01Building
from .step02_apartments import Step02Apartments
from .step03_rooms import Step03Rooms
from .step03b_verteiler import Step03bVerteiler
from .step04_topology import Step04Topology
from .step05_gewerke import Step05Gewerke
from .step05c_devices import Step05cDevices
from .step06_actors import Step06Actors
from .step07_addresses import Step07Addresses
from .step07b_scenes import Step07bScenes
from .step08_sensors import Step08Sensors
from .step09_functions import Step09Functions
from .step10_export import Step10Export

from ...models.project import KnxProject
from ..styles import KNX_GREEN, KNX_DARK_GREEN

logger = logging.getLogger("knix_arranger.wizard_controller")


STEP_TITLES = [
    "1. Gebäudestruktur",        # 0
    "2. Wohnungen / Zonen",      # 1
    "3. Räume",                  # 2
    "4. Elektroverteilungen",    # 3
    "5. Gewerke",                # 4
    "6. Gerätekonfiguration",    # 5
    "7. Topologie",              # 6
    "8. Aktor-Ermittlung",       # 7
    "9. Szenen",                 # 8
    "10. Gruppenadressen",       # 9
    "11. Funktionszuordnung",    # 10
    "12. Funktionsdefinition",   # 11
    "13. Export",                # 12
]

NUM_STEPS = len(STEP_TITLES)


class WizardController(QDialog):
    """Steuert den 13-Schritt-Wizard."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KNiX Arranger - Projektassistent")
        self.setMinimumSize(900, 650)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self._project = project
        self._current_step = 0

        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        self._step_label = QLabel("")
        self._step_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {KNX_DARK_GREEN};"
        )
        header.addWidget(self._step_label)
        header.addStretch()

        self._step_info = QLabel("")
        self._step_info.setStyleSheet("color: #808080;")
        header.addWidget(self._step_info)
        layout.addLayout(header)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, NUM_STEPS)
        self._progress.setValue(1)
        self._progress.setFormat(f"Schritt %v von {NUM_STEPS}")
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        # Steps
        self._stack = QStackedWidget()
        self._steps: list[QWidget] = [
            Step01Building(project),    # 1.  Gebäudestruktur
            Step02Apartments(project),  # 2.  Wohnungen / Zonen
            Step03Rooms(project),       # 3.  Räume
            Step03bVerteiler(project),  # 4.  Elektroverteilungen (HV/UV)
            Step05Gewerke(project),     # 5.  Gewerke (Zuweisung zu Räumen)
            Step05cDevices(project),    # 6.  Gerätekonfiguration (vor Topologie)
            Step04Topology(project),    # 7.  Topologie und Linienzuteilung
            Step06Actors(project),      # 8.  Aktor-Ermittlung
            Step07bScenes(project),     # 9.  Szenen
            Step07Addresses(project),   # 10. Gruppenadress-Generierung
            Step08Sensors(project),     # 11. Funktionszuordnung
            Step09Functions(project),   # 12. Funktionsdefinition
            Step10Export(project),      # 13. Export
        ]
        for step in self._steps:
            self._stack.addWidget(step)
        layout.addWidget(self._stack, 1)

        # Navigation
        nav = QHBoxLayout()
        self._btn_back = QPushButton("Zurueck")
        self._btn_back.setObjectName("secondary")
        self._btn_back.clicked.connect(self._go_back)
        nav.addWidget(self._btn_back)

        nav.addStretch()

        # Schrittnummern-Buttons
        self._step_buttons: list[QPushButton] = []
        for i in range(NUM_STEPS):
            btn = QPushButton(str(i + 1))
            btn.setFixedSize(32, 32)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, idx=i: self._go_to_step(idx))
            self._step_buttons.append(btn)
            nav.addWidget(btn)

        nav.addStretch()

        self._btn_next = QPushButton("Weiter")
        self._btn_next.setToolTip("Weiter (Alt+N)")
        self._btn_next.clicked.connect(self._go_next)
        nav.addWidget(self._btn_next)

        QShortcut(QKeySequence("Alt+N"), self, self._go_next)

        self._btn_finish = QPushButton("Fertig")
        self._btn_finish.setStyleSheet(f"background-color: {KNX_GREEN};")
        self._btn_finish.clicked.connect(self._finish)
        self._btn_finish.hide()
        nav.addWidget(self._btn_finish)

        layout.addLayout(nav)

        self._update_ui()

        # Ersten Schritt initialisieren (vorhandene Projektdaten laden)
        if hasattr(self._steps[0], "on_enter"):
            self._steps[0].on_enter()

    def _go_to_step(self, index: int):
        current = self._steps[self._current_step]
        if hasattr(current, "on_leave"):
            current.on_leave()

        self._current_step = index
        self._stack.setCurrentIndex(index)

        step = self._steps[index]
        if hasattr(step, "on_enter"):
            step.on_enter()

        self._update_ui()

    def _go_next(self):
        if self._current_step >= NUM_STEPS - 1:
            return
        ok, msg, is_hard = self._check_can_leave(self._current_step)
        if not ok:
            if is_hard:
                QMessageBox.warning(self, "Schritt unvollständig", msg)
                return
            else:
                reply = QMessageBox.question(
                    self, "Schritt unvollständig",
                    msg + "\n\nTrotzdem weiter?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return
        self._go_to_step(self._current_step + 1)

    def _check_can_leave(self, step_index: int) -> tuple[bool, str, bool]:
        """
        Prüft ob der aktuelle Schritt verlassen werden darf.

        Rückgabe: (darf_weiter, meldung, ist_hard_block)
        - ist_hard_block=True  → Pflichtdaten fehlen, Weiter gesperrt
        - ist_hard_block=False → optionale Warnung, Benutzer kann trotzdem weiter
        """
        p = self._project
        try:
            if step_index == 0:   # Gebäudestruktur
                if not p.all_floors:
                    return False, "Bitte mindestens ein Stockwerk anlegen.", True

            elif step_index == 1:   # Wohnungen / Zonen
                zones = sum(len(f.apartments) for f in p.all_floors)
                if zones == 0:
                    return False, "Bitte mindestens eine Zone/Wohnung anlegen.", True

            elif step_index == 2:   # Räume
                if not p.all_rooms:
                    return False, "Bitte mindestens einen Raum anlegen.", True

            elif step_index == 4:   # Gewerke
                rooms = p.all_rooms
                if rooms and not any(r.gewerk_assignments for r in rooms):
                    return (
                        False,
                        "Noch keinem Raum wurden Gewerke zugewiesen.\n"
                        "Ohne Gewerke können keine Adressen generiert werden.",
                        False,   # weiche Warnung
                    )

            elif step_index == 6:   # Topologie
                lines = sum(len(a.lines) for a in p.topology.areas)
                if lines == 0:
                    return (
                        False,
                        "Die Topologie enthält noch keine Linien.\n"
                        "Bitte zuerst die Topologie berechnen lassen (Schritt 7).",
                        True,
                    )

            elif step_index == 9:   # Gruppenadressen
                if len(p.group_addresses.all_addresses()) == 0:
                    return (
                        False,
                        "Es wurden noch keine Gruppenadressen generiert.\n"
                        "Ohne GAs ist ein sinnvoller Export nicht möglich.",
                        False,   # weiche Warnung
                    )

        except Exception:
            logger.exception("Fehler in _check_can_leave (Schritt %d)", step_index)

        return True, "", False

    def _go_back(self):
        if self._current_step > 0:
            self._go_to_step(self._current_step - 1)

    def _finish(self):
        current = self._steps[self._current_step]
        if hasattr(current, "on_leave"):
            current.on_leave()
        self.accept()

    # ── FA-3211: Schritt-Status für Farbkodierung ─────────────────────────────

    def _step_status(self, step_index: int) -> str:
        """Gibt 'complete', 'partial' oder 'empty' zurück (FA-3211)."""
        p = self._project
        try:
            if step_index == 0:      # Gebäudestruktur
                return "complete" if p.all_floors else "empty"
            elif step_index == 1:    # Wohnungen/Zonen
                zones = sum(len(f.apartments) for f in p.all_floors)
                total = len(p.all_floors)
                if total == 0:
                    return "empty"
                return "complete" if zones >= total else ("partial" if zones > 0 else "empty")
            elif step_index == 2:    # Räume
                n = len(p.all_rooms)
                return "complete" if n >= 2 else ("partial" if n > 0 else "empty")
            elif step_index == 3:    # Verteiler
                n = sum(
                    len(apt.verteiler) if hasattr(apt, "verteiler") else 0
                    for f in p.all_floors for apt in f.apartments
                )
                return "complete" if n >= 1 else "empty"
            elif step_index == 4:    # Gewerke
                rooms = p.all_rooms
                if not rooms:
                    return "empty"
                assigned = sum(1 for r in rooms if r.gewerk_assignments)
                return "complete" if assigned == len(rooms) else (
                    "partial" if assigned > 0 else "empty"
                )
            elif step_index == 5:    # Gerätekonfiguration
                rooms = p.all_rooms
                with_ga = [r for r in rooms if r.gewerk_assignments]
                if not with_ga:
                    return "empty"
                with_be = sum(1 for r in with_ga if r.bedienelemente)
                return "complete" if with_be >= len(with_ga) else (
                    "partial" if with_be > 0 else "empty"
                )
            elif step_index == 6:    # Topologie
                lines = sum(len(a.lines) for a in p.topology.areas)
                return "complete" if lines >= 1 else "empty"
            elif step_index == 7:    # Aktoren
                devs = sum(
                    len(line.devices)
                    for area in p.topology.areas
                    for line in area.lines
                )
                return "complete" if devs >= 1 else "empty"
            elif step_index == 8:    # Szenen
                return "complete" if p.scenes else "partial"  # optional
            elif step_index == 9:    # Gruppenadressen
                n = len(p.group_addresses.all_addresses())
                return "complete" if n >= 10 else ("partial" if n > 0 else "empty")
            elif step_index == 10:   # Funktionszuordnung
                n = sum(
                    len(be.funktionen)
                    for r in p.all_rooms
                    for be in r.bedienelemente
                )
                return "complete" if n >= 1 else "partial"  # optional
            elif step_index == 11:   # Funktionsdefinition
                return "partial"     # Bauherr-Formular: immer optional
            elif step_index == 12:   # Export
                return "partial"     # immer bereit, nie "fertig"
        except Exception:
            logger.exception("Fehler bei Schritt-Status-Berechnung (Schritt %d)", step_index)
        return "empty"

    def _update_ui(self):
        idx = self._current_step
        self._step_label.setText(STEP_TITLES[idx])
        self._step_info.setText(f"Schritt {idx + 1} von {NUM_STEPS}")
        self._progress.setValue(idx + 1)

        self._btn_back.setEnabled(idx > 0)
        self._btn_next.setVisible(idx < NUM_STEPS - 1)
        self._btn_finish.setVisible(idx == NUM_STEPS - 1)

        _STATUS_STYLE = {
            "complete": (KNX_GREEN, "white"),
            "partial":  ("#FFA726", "white"),
            "empty":    ("#C0C0C0", "white"),
            "current":  (KNX_DARK_GREEN, "white"),
        }

        for i, btn in enumerate(self._step_buttons):
            btn.setChecked(i == idx)
            tooltip = f"{STEP_TITLES[i]}\n{self._step_tooltip(i)}"
            if i == idx:
                status = "current"
                tooltip += "\n▶ Aktueller Schritt"
            else:
                status = self._step_status(i)
                status_text = {
                    "complete": "✓ Abgeschlossen",
                    "partial":  "~ Teilweise",
                    "empty":    "○ Leer",
                }.get(status, "")
                if status_text:
                    tooltip += f"\n{status_text}"
            btn.setToolTip(tooltip)
            color, text_color = _STATUS_STYLE[status]
            btn.setStyleSheet(
                f"background-color: {color}; color: {text_color}; "
                f"border-radius: 16px; font-weight: bold;"
            )

    def _step_tooltip(self, step_index: int) -> str:
        """Gibt einen kurzen Statustext für den Schritt-Button zurück (FA-3211)."""
        p = self._project
        try:
            if step_index == 0:
                n = len(p.all_floors)
                return f"{n} Stockwerk{'e' if n != 1 else ''}"
            elif step_index == 1:
                zones = sum(len(f.apartments) for f in p.all_floors)
                return f"{zones} Zone{'n' if zones != 1 else ''}"
            elif step_index == 2:
                n = len(p.all_rooms)
                return f"{n} Raum/Räume"
            elif step_index == 3:
                n = sum(
                    len(apt.verteiler) if hasattr(apt, "verteiler") else 0
                    for f in p.all_floors for apt in f.apartments
                )
                return f"{n} Verteilung{'en' if n != 1 else ''}"
            elif step_index == 4:
                n = sum(len(r.gewerk_assignments) for r in p.all_rooms)
                return f"{n} Gewerk-Zuweisung{'en' if n != 1 else ''}"
            elif step_index == 5:
                n = sum(len(r.bedienelemente) for r in p.all_rooms)
                return f"{n} Gerät{'e' if n != 1 else ''} konfiguriert"
            elif step_index == 6:
                lines = sum(len(a.lines) for a in p.topology.areas)
                return f"{lines} Linie{'n' if lines != 1 else ''}"
            elif step_index == 7:
                n = sum(
                    len(line.devices)
                    for area in p.topology.areas
                    for line in area.lines
                )
                return f"{n} Gerät{'e' if n != 1 else ''}"
            elif step_index == 8:
                n = len(p.scenes)
                return f"{n} Szene{'n' if n != 1 else ''}"
            elif step_index == 9:
                n = len(p.group_addresses.all_addresses())
                return f"{n} Gruppenadresse{'n' if n != 1 else ''}"
            elif step_index == 10:
                n = sum(
                    len(be.funktionen)
                    for r in p.all_rooms
                    for be in r.bedienelemente
                )
                return f"{n} Funktion{'en' if n != 1 else ''} zugewiesen"
            elif step_index == 11:
                return "Bauherr-Formular"
            elif step_index == 12:
                return "Export & Speichern"
        except Exception:
            logger.exception("Fehler bei Schritt-Tooltip-Berechnung (Schritt %d)", step_index)
        return ""
