"""
Dialog "Adressen neu ordnen" (FA-701 bis FA-706): Vorher-/Nachher-Vergleich
der neu geordneten Gruppenadressen eines geplanten Projekts (FA-704).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QAbstractItemView,
)

from ...services.renumber_service import RenumberPlan
from ..column_utils import fit_columns


class RenumberDialog(QDialog):
    """Zeigt, welche Gruppenadressen beim Neuordnen wohin wandern."""

    def __init__(self, plan: RenumberPlan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adressen neu ordnen")
        self.setMinimumSize(820, 560)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Die Gruppenadressen der Stockwerke werden lückenlos neu aufgebaut: "
            "Räume und Gewerke in der Reihenfolge der Gebäudestruktur, Blöcke "
            "mit Reserven, Rückmeldungen deckungsgleich zu ihren Befehlen. "
            "Zentraladressen (HG 0) und manuell angelegte Adressen bleiben, "
            "wo sie sind. Verweise von Tastern, Szenen, DALI und "
            "Kommunikationsobjekten werden nachgeführt.\n\n"
            "Nur vor der Übertragung in die ETS sinnvoll. Der gespeicherte "
            "Stand wird vorher unter «Sicherungen» abgelegt.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        summary = QLabel(self._summary(plan))
        summary.setWordWrap(True)
        summary.setStyleSheet("font-weight: bold; padding: 4px 0;")
        layout.addWidget(summary)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Bisher", "Neu", "Bezeichnung bisher", "Bezeichnung neu"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        rows = [(c.old_address, c.new_address, c.old_designation,
                 c.new_designation if c.new_designation != c.old_designation else "")
                for c in plan.changes]
        rows += [("", key.split(" ", 1)[0], "", key.split(" ", 1)[-1]) for key in plan.added]
        rows += [(key.split(" ", 1)[0], "", key.split(" ", 1)[-1], "(entfällt)")
                 for key in plan.removed]
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for col, text in enumerate(row):
                self._table.setItem(i, col, QTableWidgetItem(text))
        fit_columns(self._table)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("Neu ordnen")
        ok.setEnabled(plan.has_changes)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    @staticmethod
    def _summary(plan: RenumberPlan) -> str:
        if not plan.has_changes:
            return "Die Adressen sind bereits lückenlos geordnet – keine Änderung nötig."
        parts = [f"{len(plan.changes)} Adresse(n) verschoben oder umbenannt"]
        if plan.added:
            parts.append(f"{len(plan.added)} neu")
        if plan.removed:
            parts.append(f"{len(plan.removed)} entfallen")
        text = ", ".join(parts) + "."
        text += (f" Unbelegte Untergruppen in den Stockwerken: "
                 f"{plan.gaps_before} → {plan.gaps_after}.")
        return text
