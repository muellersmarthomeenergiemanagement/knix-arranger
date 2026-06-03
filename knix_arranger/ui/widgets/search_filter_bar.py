"""
Such- und Filterleiste (FA-820)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QComboBox, QLabel,
)
from PySide6.QtCore import Signal, Qt


class SearchFilterBar(QWidget):
    """Such- und Filterleiste für Tabellen und Baeume."""

    search_changed = Signal(str)
    filter_changed = Signal(str)

    def __init__(self, filters: list[tuple[str, str]] = None, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Suchfeld
        layout.addWidget(QLabel("Suche:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Adresse, Name, Gewerk, Raum...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self._search, 2)

        # Filter
        if filters:
            layout.addWidget(QLabel("Filter:"))
            self._filter = QComboBox()
            self._filter.addItem("Alle", "")
            for key, text in filters:
                self._filter.addItem(text, key)
            self._filter.currentIndexChanged.connect(self._on_filter_changed)
            layout.addWidget(self._filter, 1)

    def _on_filter_changed(self, index: int):
        data = self._filter.itemData(index)
        self.filter_changed.emit(data or "")

    @property
    def search_text(self) -> str:
        return self._search.text()

    def clear(self):
        self._search.clear()
