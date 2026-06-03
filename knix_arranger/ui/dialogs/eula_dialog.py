"""
EULA-Dialog (NFA-081, NFA-083)

Zeigt den Endbenutzer-Lizenzvertrag beim Erststart an.
Der Text wird aus config/EULA.txt geladen (NFA-083: externe Textdatei).
Die Akzeptanz wird in %APPDATA%/KNiX Arranger/eula_accepted.dat gespeichert.
"""
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ... import APP_NAME, __copyright__
from ..styles import KNX_GREEN, KNX_DARK_GREEN

_EULA_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "EULA.txt")
)


class EulaDialog(QDialog):
    """
    Endbenutzer-Lizenzvertrag-Dialog (NFA-081).

    Muss beim Erststart angezeigt und akzeptiert werden.
    Ablehnen beendet die Anwendung.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} – Lizenzvertrag")
        self.setMinimumSize(680, 560)
        # Kein X-Button: Schliessen nur über "Akzeptieren"/"Ablehnen"
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            & ~Qt.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header-Banner ──────────────────────────────────────────────────────
        banner = QFrame()
        banner.setStyleSheet(
            f"QFrame {{ background-color: {KNX_DARK_GREEN}; border: none; }}"
        )
        banner.setFixedHeight(80)
        banner_layout = QVBoxLayout(banner)
        banner_layout.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel("Endbenutzer-Lizenzvertrag (EULA)")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("color: white; background: transparent;")
        banner_layout.addWidget(title_lbl)

        sub_lbl = QLabel(__copyright__)
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.70); font-size: 11px; background: transparent;"
        )
        banner_layout.addWidget(sub_lbl)

        layout.addWidget(banner)

        # ── Inhalt ─────────────────────────────────────────────────────────────
        content = QFrame()
        content.setStyleSheet("background-color: #FAFAFA;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 16, 24, 16)
        content_layout.setSpacing(10)

        hint_lbl = QLabel(
            "Bitte lesen Sie den Lizenzvertrag vollständig. "
            "Der Schaltknopf «Akzeptieren» wird nach dem Lesen aktiv."
        )
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #555; font-size: 11px;")
        content_layout.addWidget(hint_lbl)

        # EULA-Text
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setStyleSheet(
            "background: white; border: 1px solid #CCC; font-family: monospace; font-size: 11px;"
        )
        self._text_edit.setPlainText(self._load_eula_text())
        content_layout.addWidget(self._text_edit, 1)

        # Trennlinie
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        content_layout.addWidget(line)

        # Buttons
        btn_row = QHBoxLayout()

        self._btn_reject = QPushButton("Ablehnen")
        self._btn_reject.setStyleSheet(
            "QPushButton { color: #555; border: 1px solid #CCC; "
            "padding: 8px 24px; background: white; border-radius: 4px; }"
            "QPushButton:hover { background: #F5F5F5; }"
        )
        self._btn_reject.setToolTip(
            "Lizenzvertrag ablehnen – die Anwendung wird beendet."
        )
        self._btn_reject.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_reject)

        btn_row.addStretch()

        self._btn_accept = QPushButton("Akzeptieren")
        self._btn_accept.setEnabled(False)
        self._btn_accept.setStyleSheet(
            f"QPushButton {{ background-color: {KNX_GREEN}; color: white; "
            f"font-weight: bold; padding: 8px 32px; border-radius: 4px; border: none; }}"
            f"QPushButton:disabled {{ background-color: #BBBBBB; color: #EEEEEE; }}"
            f"QPushButton:hover:enabled {{ background-color: {KNX_DARK_GREEN}; }}"
        )
        self._btn_accept.setToolTip(
            "Lizenzvertrag akzeptieren – Anwendung wird gestartet."
        )
        self._btn_accept.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_accept)

        content_layout.addLayout(btn_row)
        layout.addWidget(content, 1)

        # Scrollbar-Signal: Akzeptieren erst aktiv wenn ans Ende gescrollt
        sb = self._text_edit.verticalScrollBar()
        sb.rangeChanged.connect(self._on_range_changed)
        sb.valueChanged.connect(self._check_scrolled_to_bottom)

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def _load_eula_text(self) -> str:
        """Lädt den EULA-Text aus config/EULA.txt (NFA-083)."""
        try:
            with open(_EULA_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return (
                "EULA-Datei nicht gefunden.\n"
                f"Erwartet unter: {_EULA_PATH}\n\n"
                "Bitte wenden Sie sich an den Hersteller."
            )

    def _on_range_changed(self, _min: int, _max: int):
        """Aktiviert 'Akzeptieren' sofort wenn der Text komplett sichtbar ist."""
        if _max == 0:
            self._btn_accept.setEnabled(True)

    def _check_scrolled_to_bottom(self, value: int):
        """Aktiviert 'Akzeptieren' wenn der Benutzer ans Ende gescrollt hat."""
        sb = self._text_edit.verticalScrollBar()
        if value >= sb.maximum():
            self._btn_accept.setEnabled(True)
