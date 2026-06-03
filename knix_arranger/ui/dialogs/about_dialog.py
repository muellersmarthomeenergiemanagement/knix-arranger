"""
About-Dialog (NFA-060)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
)
from PySide6.QtCore import Qt
from ... import __version__, APP_NAME, __copyright__
from ..styles import KNX_GREEN, KNX_DARK_GREEN


class AboutDialog(QDialog):
    """Zeigt Copyright, Version und Lizenzinformationen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ueber {APP_NAME}")
        self.setFixedWidth(400)
        self.setMinimumHeight(280)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Logo/Titel
        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {KNX_DARK_GREEN}; "
            f"padding: 15px;"
        )
        layout.addWidget(title)

        # Version
        version = QLabel(f"Version {__version__}")
        version.setAlignment(Qt.AlignCenter)
        version.setStyleSheet("font-size: 14px; color: #808080;")
        layout.addWidget(version)

        # Copyright
        copyright_label = QLabel(__copyright__)
        copyright_label.setAlignment(Qt.AlignCenter)
        copyright_label.setWordWrap(True)
        layout.addWidget(copyright_label)

        # Beschreibung
        desc = QLabel(
            "KNX-Projektplanungstool für die automatisierte\n"
            "Generierung von Gruppenadressen, Topologie\n"
            "und Dokumentation nach KNX Swiss Richtlinien."
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("padding: 10px; color: #404040;")
        layout.addWidget(desc)

        # KNX Swiss
        knx = QLabel("Basierend auf KNX Swiss Projektrichtlinien 2024")
        knx.setAlignment(Qt.AlignCenter)
        knx.setStyleSheet(f"color: {KNX_GREEN}; font-weight: bold;")
        layout.addWidget(knx)

        # Schliessen
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_close = QPushButton("Schliessen")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
