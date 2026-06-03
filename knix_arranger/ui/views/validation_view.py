"""
Validierungsbericht-Ansicht (FA-600)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QAbstractItemView,
)
from PySide6.QtGui import QColor, QBrush
from PySide6.QtCore import Signal, Qt
from ..styles import COLOR_ERROR, COLOR_WARNING, COLOR_INFO, COLOR_OK
from ..column_utils import fit_columns


class ValidationView(QWidget):
    """Zeigt Validierungsergebnisse als Fehlerliste."""

    revalidate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # Titel und Button
        header = QHBoxLayout()
        title = QLabel("Validierung")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self._btn_validate = QPushButton("Erneut validieren")
        self._btn_validate.clicked.connect(self.revalidate_requested.emit)
        header.addWidget(self._btn_validate)
        layout.addLayout(header)

        # Zusammenfassung
        self._summary = QLabel("")
        self._summary.setObjectName("subtitle")
        layout.addWidget(self._summary)

        # Tabelle
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Stufe", "Regel", "Adresse", "Meldung", "Vorschlag",
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

    def set_issues(self, issues: list):
        """Zeigt Validierungsprobleme an."""
        self._table.setRowCount(len(issues))

        error_count = 0
        warning_count = 0
        info_count = 0

        for row, issue in enumerate(issues):
            # issue kann ein ValidationIssue-Objekt oder dict sein
            if hasattr(issue, "level"):
                level = issue.level
                rule_id = issue.rule_id
                address = issue.address
                message = issue.message
                suggestion = issue.suggestion
            else:
                level = issue.get("level", "")
                rule_id = issue.get("rule_id", "")
                address = issue.get("address", "")
                message = issue.get("message", "")
                suggestion = issue.get("suggestion", "")

            level_text = {"error": "Fehler", "warning": "Warnung", "info": "Info"}.get(
                level, level
            )
            items = [level_text, rule_id, address, message, suggestion]

            color = {
                "error": COLOR_ERROR,
                "warning": COLOR_WARNING,
                "info": COLOR_INFO,
            }.get(level, "#000000")

            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(QBrush(QColor(color)))
                    item.setData(Qt.FontRole, True)
                self._table.setItem(row, col, item)

            if level == "error":
                error_count += 1
            elif level == "warning":
                warning_count += 1
            else:
                info_count += 1

        fit_columns(self._table)

        # Zusammenfassung
        if not issues:
            self._summary.setText("Keine Probleme gefunden.")
            self._summary.setStyleSheet(f"color: {COLOR_OK}; font-weight: bold;")
        else:
            self._summary.setText(
                f"{error_count} Fehler, {warning_count} Warnungen, {info_count} Hinweise"
            )
            if error_count > 0:
                self._summary.setStyleSheet(f"color: {COLOR_ERROR}; font-weight: bold;")
            elif warning_count > 0:
                self._summary.setStyleSheet(f"color: {COLOR_WARNING}; font-weight: bold;")
            else:
                self._summary.setStyleSheet(f"color: {COLOR_INFO}; font-weight: bold;")
