"""
Statusleiste mit Projektinfo (NFA-023)
"""
from __future__ import annotations
from PySide6.QtWidgets import QStatusBar, QLabel
from PySide6.QtCore import Qt


class KnxStatusBar(QStatusBar):
    """Erweiterte Statusleiste mit Projektinformationen."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._project_label = QLabel("Kein Projekt geladen")
        self._variant_label = QLabel("")
        self._ga_count_label = QLabel("")
        self._status_label = QLabel("Bereit")

        self.addWidget(self._project_label, 2)
        self.addWidget(self._variant_label, 1)
        self.addWidget(self._ga_count_label, 1)
        self.addPermanentWidget(self._status_label)

    def set_project_name(self, name: str):
        self._project_label.setText(f"Projekt: {name}")

    def set_variant(self, variant: str):
        self._variant_label.setText(f"Variante {variant}")

    def set_ga_count(self, count: int):
        self._ga_count_label.setText(f"{count} Gruppenadressen")

    def set_status(self, text: str):
        self._status_label.setText(text)
        self.showMessage(text, 3000)
