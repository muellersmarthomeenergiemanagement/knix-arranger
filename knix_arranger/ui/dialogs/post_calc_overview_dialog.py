"""
Dialog "Nachkalkulation aller Projekte" (FA-2205, FA-2206).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QGroupBox, QMessageBox,
)

from ...services.post_calc_overview import (
    DEVIATION_THRESHOLD, apply_guide_values, build_overview, display_date,
    suggest_guide_values,
)
from ..column_utils import fit_columns

_OVER = "#FFE0D6"     # Mehraufwand
_UNDER = "#E3F5DC"    # Minderaufwand


def _cell(text: str, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if right:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


class PostCalcOverviewDialog(QDialog):
    """Marge und Abweichungen aller nachkalkulierten Projekte, Verlauf und
    Vorschläge für die Richtwerte."""

    def __init__(self, results, profile, save_profile, parent=None):
        """save_profile: Aufruf, der das geänderte Firmenprofil speichert."""
        super().__init__(parent)
        self._profile = profile
        self._save_profile = save_profile
        self.setWindowTitle("Nachkalkulation aller Projekte")
        self.setMinimumSize(900, 620)
        overview = build_overview(results)
        layout = QVBoxLayout(self)

        if not results:
            layout.addWidget(QLabel(
                "Noch keine nachkalkulierten Projekte gefunden. Ausgewertet werden "
                "akzeptierte Kundenofferten mit erfassten Ist-Werten – im geöffneten "
                "Projekt, im Arbeitsverzeichnis und in den zuletzt geöffneten Projekten."))
        else:
            summary = QLabel(
                f"{len(results)} nachkalkulierte Offerte(n). Marge geplant "
                f"{overview.planned_margin_percent:.1f} %, tatsächlich "
                f"{overview.actual_margin_percent:.1f} % (umsatzgewichtet). "
                f"{overview.trend}")
            summary.setWordWrap(True)
            summary.setStyleSheet("font-weight: bold;")
            layout.addWidget(summary)
            note = QLabel("Marge = Offertbetrag netto minus Aufwand (Material zum Einkauf, "
                          "Stunden zu den Offertsätzen).")
            note.setStyleSheet("color: #666;")
            layout.addWidget(note)

        # Projekte im zeitlichen Verlauf
        projects = QGroupBox("Projekte (nach Datum)")
        box = QVBoxLayout(projects)
        table = QTableWidget(len(results), 6)
        table.setHorizontalHeaderLabels(
            ["Datum", "Projekt", "Offerte", "Offertbetrag", "Marge geplant", "Marge Ist"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, r in enumerate(results):
            table.setItem(row, 0, _cell(display_date(r.date)))
            table.setItem(row, 1, _cell(r.project))
            table.setItem(row, 2, _cell(r.quote))
            table.setItem(row, 3, _cell(f"{r.revenue:,.0f}".replace(",", "'"), True))
            table.setItem(row, 4, _cell(f"{r.planned_margin_percent:.1f} %", True))
            actual = _cell(f"{r.actual_margin_percent:.1f} %", True)
            if r.actual_margin_percent < r.planned_margin_percent - DEVIATION_THRESHOLD / 2:
                actual.setBackground(QBrush(QColor(_OVER)))
            table.setItem(row, 5, actual)
        fit_columns(table)
        box.addWidget(table)
        layout.addWidget(projects)

        # Häufigste Abweichungen
        deviations = QGroupBox(
            f"Abweichungen Ist zu Soll (abweichend = mehr als ±{DEVIATION_THRESHOLD:.0f} %)")
        box = QVBoxLayout(deviations)
        dev_table = QTableWidget(len(overview.deviations), 3)
        dev_table.setHorizontalHeaderLabels(["Kategorie", "Mittlere Abweichung", "Abweichend"])
        dev_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        dev_table.verticalHeader().setVisible(False)
        for row, d in enumerate(overview.deviations):
            dev_table.setItem(row, 0, _cell(d.label))
            avg = _cell(f"{d.average_percent:+.1f} %", True)
            if abs(d.average_percent) > DEVIATION_THRESHOLD:
                avg.setBackground(QBrush(QColor(_OVER if d.average_percent > 0 else _UNDER)))
            dev_table.setItem(row, 1, avg)
            dev_table.setItem(row, 2, _cell(f"{d.deviating} von {d.counted}", True))
        fit_columns(dev_table)
        box.addWidget(dev_table)
        layout.addWidget(deviations)

        # Richtwerte (FA-2205)
        guide = QGroupBox("Richtwerte für die Aufwandsschätzung")
        box = QVBoxLayout(guide)
        self._suggestions = suggest_guide_values(results, profile)
        if self._suggestions:
            guide_table = QTableWidget(len(self._suggestions), 4)
            guide_table.setHorizontalHeaderLabels(
                ["Richtwert", "Aktuell", "Vorschlag", "Basis"])
            guide_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            guide_table.verticalHeader().setVisible(False)
            for row, s in enumerate(self._suggestions):
                guide_table.setItem(row, 0, _cell(s.label))
                guide_table.setItem(row, 1, _cell(f"{s.current:g}", True))
                guide_table.setItem(row, 2, _cell(f"{s.suggested:g}", True))
                guide_table.setItem(row, 3, _cell(f"{s.based_on} Projekte", True))
            fit_columns(guide_table)
            box.addWidget(guide_table)
            row = QHBoxLayout()
            row.addStretch()
            self._btn_apply = QPushButton("Vorschläge übernehmen")
            self._btn_apply.setToolTip("Schreibt die vorgeschlagenen Minuten je Gerät ins "
                                       "Firmenprofil (Einstellungen → Stundensätze)")
            self._btn_apply.clicked.connect(self._apply)
            row.addWidget(self._btn_apply)
            box.addLayout(row)
        else:
            box.addWidget(QLabel("Für Vorschläge braucht es mindestens zwei nachkalkulierte "
                                 "Projekte mit Geräten und Ist-Stunden."))
        layout.addWidget(guide)

        close = QPushButton("Schliessen")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _apply(self) -> None:
        lines = "\n".join(f"{s.label}: {s.current:g} → {s.suggested:g}"
                          for s in self._suggestions)
        if QMessageBox.question(
                self, "Richtwerte übernehmen",
                f"Neue Richtwerte ins Firmenprofil übernehmen?\n\n{lines}\n\n"
                "Gilt für künftige Aufwandsschätzungen aller Projekte.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        apply_guide_values(self._profile, self._suggestions)
        self._save_profile(self._profile)
        self._btn_apply.setEnabled(False)
        self._btn_apply.setText("Übernommen")
