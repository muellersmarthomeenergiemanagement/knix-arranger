"""
Dialog "Was ist neu" – zeigt die Release-Notes nach einem Update bzw. über
das Hilfe-Menü (Quelle: config/release_notes.json).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextBrowser, QDialogButtonBox,
)
from PySide6.QtGui import QFont

from ..styles import KNX_DARK_GREEN
from ...services.release_notes_service import ReleaseNotes, notes_to_html


class WhatsNewDialog(QDialog):
    """Listet eine oder mehrere Versionen mit ihren Änderungen auf."""

    def __init__(self, notes: list[ReleaseNotes], title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Was ist neu – KNiX Arranger")
        self.setMinimumSize(620, 480)

        layout = QVBoxLayout(self)

        header = QLabel(title)
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        header.setFont(font)
        header.setStyleSheet(f"color: {KNX_DARK_GREEN};")
        header.setWordWrap(True)
        layout.addWidget(header)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(notes_to_html(notes))
        layout.addWidget(browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
