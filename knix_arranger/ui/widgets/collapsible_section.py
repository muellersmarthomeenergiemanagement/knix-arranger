"""
Einklappbarer Bereich mit Überschrift (Ersatz für QGroupBox bei selten
genutzten Werkzeugen, damit der eigentliche Arbeitsbereich mehr Platz hat).
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFrame, QLayout

from ..icons import icon
from ..styles import KNX_DARK_GRAY, KNX_MEDIUM_GRAY, FONT_BODY


class CollapsibleSection(QWidget):
    """Überschrift mit Pfeil; ein Klick blendet den Inhalt ein oder aus."""

    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(0)

        self._header = QPushButton()
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setIconSize(QSize(16, 16))
        self._header.setStyleSheet(
            "QPushButton {"
            f" background-color: transparent; color: {KNX_DARK_GRAY};"
            f" font-size: {FONT_BODY}px; font-weight: bold; text-align: left;"
            f" padding: 4px 2px; border: none; border-bottom: 1px solid {KNX_MEDIUM_GRAY};"
            "}"
            "QPushButton:hover { background-color: #EDEDED; }"
        )
        self._header.clicked.connect(lambda: self.set_expanded(not self._expanded))
        outer.addWidget(self._header)

        self._body = QFrame()
        outer.addWidget(self._body)

        self._expanded = not expanded  # erzwingt Aktualisierung
        self.set_expanded(expanded)

    def set_body_layout(self, layout: QLayout) -> None:
        """Setzt den Inhalt (analog QGroupBox.setLayout)."""
        layout.setContentsMargins(8, 6, 4, 6)
        self._body.setLayout(layout)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._header.setText(f" {self._title}")
        self._header.setIcon(icon("chevron-down" if expanded else "chevron-right", KNX_DARK_GRAY))
        self._header.setToolTip("Einklappen" if expanded else "Aufklappen")
        self.toggled.emit(expanded)

    def is_expanded(self) -> bool:
        return self._expanded
