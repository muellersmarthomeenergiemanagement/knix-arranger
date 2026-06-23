"""
Willkommensbildschirm (NFA-010)
Zeigt Firmennamen, Softwarerechte und Einstiegsoptionen beim Start.
"""
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ... import __version__, APP_NAME, __copyright__, __author__
from ..styles import KNX_GREEN, KNX_DARK_GREEN

ACTION_NEW = "new"
ACTION_OPEN = "open"


class WelcomeDialog(QDialog):
    """Willkommensbildschirm mit Neu/Öffnen-Auswahl."""

    def __init__(self, parent=None, recent_projects: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Willkommen bei {APP_NAME}")
        self._action: str | None = None
        self._selected_path: str | None = None
        self._recent_projects = [p for p in (recent_projects or []) if os.path.exists(p)][:5]
        self.setFixedSize(580, 520 + (40 * len(self._recent_projects) if self._recent_projects else 0))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header-Banner ──
        banner = QFrame()
        banner.setObjectName("welcome_banner")
        banner.setStyleSheet(
            f"QFrame#welcome_banner {{ "
            f"background-color: {KNX_DARK_GREEN}; "
            f"border: none; }}"
        )
        banner.setFixedHeight(160)
        banner_layout = QVBoxLayout(banner)
        banner_layout.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(APP_NAME)
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("color: white; background: transparent;")
        banner_layout.addWidget(title_lbl)

        version_lbl = QLabel(f"Version {__version__}")
        version_lbl.setAlignment(Qt.AlignCenter)
        version_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.75); font-size: 13px; background: transparent;"
        )
        banner_layout.addWidget(version_lbl)

        tagline_lbl = QLabel("KNX-Projektplanungstool nach KNX Swiss Richtlinien 2024")
        tagline_lbl.setAlignment(Qt.AlignCenter)
        tagline_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.60); font-size: 11px; background: transparent;"
        )
        banner_layout.addWidget(tagline_lbl)

        layout.addWidget(banner)

        # ── Inhalt ──
        content = QFrame()
        content.setStyleSheet("background-color: #FAFAFA;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 28, 40, 24)
        content_layout.setSpacing(20)

        # Rechte / Copyright
        rights_frame = QFrame()
        rights_frame.setStyleSheet(
            "background-color: white; border: 1px solid #E0E0E0; border-radius: 6px;"
        )
        rights_layout = QVBoxLayout(rights_frame)
        rights_layout.setContentsMargins(16, 12, 16, 12)
        rights_layout.setSpacing(4)

        company_lbl = QLabel(__author__)
        company_font = QFont()
        company_font.setBold(True)
        company_font.setPointSize(11)
        company_lbl.setFont(company_font)
        company_lbl.setStyleSheet(f"color: {KNX_DARK_GREEN}; border: none;")
        rights_layout.addWidget(company_lbl)

        copy_lbl = QLabel(__copyright__)
        copy_lbl.setStyleSheet("color: #555; font-size: 11px; border: none;")
        rights_layout.addWidget(copy_lbl)

        rights_note = QLabel(
            "Alle Rechte vorbehalten. Die Software darf ohne ausdrückliche Genehmigung\n"
            "weder kopiert noch weitergegeben werden."
        )
        rights_note.setWordWrap(True)
        rights_note.setStyleSheet("color: #888; font-size: 10px; border: none;")
        rights_layout.addWidget(rights_note)

        content_layout.addWidget(rights_frame)

        # Zuletzt verwendete Projekte
        if self._recent_projects:
            recent_lbl = QLabel("Zuletzt verwendet")
            recent_lbl.setStyleSheet("color: #333; font-weight: bold; font-size: 12px;")
            content_layout.addWidget(recent_lbl)

            recent_frame = QFrame()
            recent_frame.setStyleSheet(
                "background-color: white; border: 1px solid #E0E0E0; border-radius: 6px;"
            )
            recent_layout = QVBoxLayout(recent_frame)
            recent_layout.setContentsMargins(4, 4, 4, 4)
            recent_layout.setSpacing(2)
            for path in self._recent_projects:
                name = os.path.splitext(os.path.basename(path))[0]
                btn = QPushButton(name)
                btn.setToolTip(path)
                btn.setStyleSheet(
                    "QPushButton { text-align: left; border: none; "
                    "padding: 6px 10px; color: #333; font-size: 11px; "
                    "background: transparent; border-radius: 4px; }"
                    "QPushButton:hover { background-color: #F0F8F0; }"
                )
                btn.clicked.connect(lambda checked=False, p=path: self._choose_recent(p))
                recent_layout.addWidget(btn)
            content_layout.addWidget(recent_frame)

        # Aktions-Buttons
        actions_lbl = QLabel("Was möchten Sie tun?")
        actions_lbl.setStyleSheet("color: #333; font-weight: bold; font-size: 12px;")
        content_layout.addWidget(actions_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        self._btn_new = QPushButton("Neues Projekt erstellen")
        self._btn_new.setFixedHeight(52)
        self._btn_new.setStyleSheet(
            f"QPushButton {{ "
            f"background-color: {KNX_GREEN}; color: white; "
            f"font-size: 13px; font-weight: bold; "
            f"border-radius: 6px; border: none; text-align: left; padding-left: 16px; }}"
            f"QPushButton:hover {{ background-color: {KNX_DARK_GREEN}; }}"
        )
        self._btn_new.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_new.clicked.connect(self._choose_new)
        btn_row.addWidget(self._btn_new)

        self._btn_open = QPushButton("Bestehendes Projekt öffnen")
        self._btn_open.setFixedHeight(52)
        self._btn_open.setStyleSheet(
            f"QPushButton {{ "
            f"background-color: white; color: {KNX_DARK_GREEN}; "
            f"font-size: 13px; font-weight: bold; "
            f"border-radius: 6px; border: 2px solid {KNX_GREEN}; "
            f"text-align: left; padding-left: 16px; }}"
            f"QPushButton:hover {{ background-color: #F0F8F0; }}"
        )
        self._btn_open.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_open.clicked.connect(self._choose_open)
        btn_row.addWidget(self._btn_open)

        content_layout.addLayout(btn_row)

        content_layout.addStretch()

        # ── Footer: ClaudeCode + Abbrechen ──
        footer_row = QHBoxLayout()
        footer_row.setSpacing(0)

        claude_lbl = QLabel("Erstellt mit ClaudeCode – Anthropic")
        claude_lbl.setStyleSheet(
            "color: #AAAAAA; font-size: 10px; font-style: italic;"
        )
        footer_row.addWidget(claude_lbl)

        footer_row.addStretch()

        btn_cancel = QPushButton("Ohne Projekt fortfahren")
        btn_cancel.setStyleSheet(
            "color: #888; border: none; font-size: 11px; "
            "background: transparent; padding: 4px 8px;"
        )
        btn_cancel.clicked.connect(self.reject)
        footer_row.addWidget(btn_cancel)

        content_layout.addLayout(footer_row)

        layout.addWidget(content, 1)

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _choose_new(self):
        self._action = ACTION_NEW
        self.accept()

    def _choose_open(self):
        self._action = ACTION_OPEN
        self.accept()

    def _choose_recent(self, path: str):
        self._action = ACTION_OPEN
        self._selected_path = path
        self.accept()

    @property
    def action(self) -> str | None:
        """ACTION_NEW oder ACTION_OPEN, je nach Benutzerwahl."""
        return self._action

    @property
    def selected_path(self) -> str | None:
        """Pfad eines direkt aus der Recent-Liste gewählten Projekts (oder None)."""
        return self._selected_path
