"""
Anlagen-Check (FA-641): Prüfpunkte mit Bewertung, Doppelklick öffnet die
Ansicht zum Weiterarbeiten (services/plant_check).
"""
from __future__ import annotations
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...services.plant_check import ATTENTION, CRITICAL, OK, rating_counts, run_check
from ..column_utils import fit_columns
from ..styles import TEXT_MUTED

RATING_COLORS = {OK: "#2E7D32", ATTENTION: "#E65100", CRITICAL: "#C62828", "info": "#1565C0"}


class PlantCheckView(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._counts = None
        layout = QVBoxLayout(self)
        title = QLabel("Anlagen-Check")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Zustand der Anlage auf einen Blick: Topologie, Reserven, Gruppenadressen, "
            "Geräte, Validierung, KNX Secure, Dokumentation und Busanalyse. Doppelklick "
            "öffnet die passende Ansicht.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)
        row = QHBoxLayout()
        self._summary = QLabel()
        row.addWidget(self._summary)
        row.addStretch()
        refresh = QPushButton("Neu prüfen")
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self._refresh)
        self._report_btn = QPushButton("Bericht Anlagen-Check…")
        self._report_btn.clicked.connect(self._report)
        row.addWidget(refresh)
        row.addWidget(self._report_btn)
        layout.addLayout(row)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Bereich", "Prüfpunkt", "Ergebnis", "Bewertung",
                                               "Empfehlung"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setWordWrap(True)
        self._table.cellDoubleClicked.connect(self._open)
        layout.addWidget(self._table, 1)

    def set_project(self, project) -> None:
        self._project = project
        self._refresh()

    def set_problem_counts(self, counts) -> None:
        """(Fehler, Warnungen) der laufenden Prüfung -- spart die eigene Validierung."""
        self._counts = counts

    def _refresh(self) -> None:
        if self._project is None:
            return
        items = run_check(self._project, self._counts)
        counts = rating_counts(items)
        self._summary.setText(
            f"<b>{counts.get(CRITICAL, 0)}</b> kritisch · <b>{counts.get(ATTENTION, 0)}</b> "
            f"beachten · <b>{counts.get(OK, 0)}</b> in Ordnung")
        self._table.setRowCount(len(items))
        for r, item in enumerate(items):
            for c, text in enumerate((item.area, item.title, item.value, item.rating, item.hint)):
                cell = QTableWidgetItem(text)
                if c == 3:
                    cell.setForeground(QColor(RATING_COLORS.get(item.rating, TEXT_MUTED)))
                if c == 0:
                    cell.setData(Qt.UserRole, item.nav_key)
                self._table.setItem(r, c, cell)
        self._fit()

    def _fit(self) -> None:
        """«Empfehlung» nimmt die restliche Breite (vorher halbe Breite
        genutzt und «Gruppena…» abgeschnitten)."""
        fit_columns(self._table, flex=4)
        self._table.resizeRowsToContents()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _open(self, row: int, _column: int) -> None:
        key = self._table.item(row, 0).data(Qt.UserRole)
        if key:
            self.navigate_requested.emit(key)

    def _report(self) -> None:
        from .. import license_gate
        from ..dialogs.reports_dialog import open_report
        from ...services.project_service import ProjectService
        from ...services.report_service import ReportService
        folder = self._project.folder_path
        name = f"{self._project.name}_Anlagen-Check.pdf"
        default = os.path.join(folder, "Berichte", name) if folder else name
        if folder:
            os.makedirs(os.path.join(folder, "Berichte"), exist_ok=True)
        path, _ = license_gate.get_save_file_name(
            self, "Bericht Anlagen-Check speichern", default, "PDF-Dateien (*.pdf)")
        if not path:
            return
        ReportService(self._project, company_profile=ProjectService().load_company_profile()) \
            .generate_plant_check_report(path, self._counts)
        open_report(path)
