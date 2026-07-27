"""
Änderungsprotokoll-Ansicht.

Zeigt das checkpoint-basierte Änderungsprotokoll des Projekts (automatische
Einträge bei Projekt-Erstellung, ETS-Import/Re-Import und Revisionspaket-
Erstellung, siehe models.project.ChangelogEntry) und erlaubt das Hinzufügen
eigener Freitext-Notizen. Bewusst keine feldweise Änderungsverfolgung -- für
ein Solo-Planungswerkzeug wäre das reines Rauschen.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QAbstractItemView,
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor

from ...models.project import KnxProject
from ..column_utils import fit_columns

_COL_TIME = 0
_COL_CAT = 1
_COL_MSG = 2

_CAT_COLORS = {
    "Projekt": "#1565C0",
    "Import": "#2E7D32",
    "Re-Import": "#EF6C00",
    "Revision": "#6A1B9A",
    "Notiz": "#455A64",
}


class ChangelogView(QWidget):
    """Änderungsprotokoll: automatische Checkpoints + manuelle Notizen."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Änderungsprotokoll")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        info = QLabel(
            "Automatische Einträge bei Projekt-Erstellung, ETS-Import/Re-Import "
            "und Revisionspaket-Erstellung. Keine feldweise Änderungsverfolgung -- "
            "für eigene Notizen das Feld unten nutzen."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666;")
        layout.addWidget(info)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Zeitpunkt", "Kategorie", "Meldung"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        # Notiz hinzufügen
        note_row = QHBoxLayout()
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText(
            "Eigene Notiz hinzufügen (z.B. Bauherr-Rückmeldung, Planungsentscheid)…"
        )
        self._note_edit.returnPressed.connect(self._add_note)
        note_row.addWidget(self._note_edit, 1)
        btn_add = QPushButton("Notiz hinzufügen")
        btn_add.clicked.connect(self._add_note)
        note_row.addWidget(btn_add)
        layout.addLayout(note_row)

    def set_project(self, project: KnxProject):
        self._project = project
        self._refresh()

    def _refresh(self):
        if not self._project:
            self._table.setRowCount(0)
            return
        entries = list(reversed(self._project.changelog))  # neueste zuerst
        self._table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            self._table.setItem(i, _COL_TIME, QTableWidgetItem(entry.timestamp))
            cat_item = QTableWidgetItem(entry.category)
            cat_item.setForeground(QColor(_CAT_COLORS.get(entry.category, "#455A64")))
            self._table.setItem(i, _COL_CAT, cat_item)
            self._table.setItem(i, _COL_MSG, QTableWidgetItem(entry.message))
        fit_columns(self._table)

    def _add_note(self):
        text = self._note_edit.text().strip()
        if not text or not self._project:
            return
        self._project.add_changelog_entry("Notiz", text)
        self._note_edit.clear()
        self._refresh()
        self.changed.emit()
