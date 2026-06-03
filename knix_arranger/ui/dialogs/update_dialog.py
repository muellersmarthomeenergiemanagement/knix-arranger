"""
Update-Informations-Dialog (NFA-111 bis NFA-115)

Zeigt dem Benutzer an, dass eine neue Version verfuegbar ist, mit Changelog
und Download-Link. Erlaubt Ignorieren der Version oder Deaktivierung des
automatischen Update-Checks.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QCheckBox, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtCore import QUrl

from ..styles import KNX_GREEN, KNX_DARK_GREEN
from ...services.update_service import UpdateInfo


class UpdateDialog(QDialog):
    """
    Dialog fuer verfuegbare Updates (NFA-112, NFA-113, NFA-114).

    Zeigt Versions-Info, Changelog und bietet:
    - Download-Link oeffnen im Browser (NFA-113)
    - Spaeter erinnern (NFA-114)
    - Diese Version ignorieren (NFA-114)
    - Auto-Check aktivieren/deaktivieren (NFA-115)
    """

    def __init__(self, update_info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update verfügbar – KNiX Arranger")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._update_info = update_info
        self._ignore_version = False

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
        hdr_font = QFont()
        hdr_font.setPointSize(14)
        hdr_font.setBold(True)

        icon_lbl = QLabel("🔔")
        icon_font = QFont()
        icon_font.setPointSize(24)
        icon_lbl.setFont(icon_font)

        hdr_row = QHBoxLayout()
        hdr_row.addWidget(icon_lbl)

        hdr_text = QVBoxLayout()
        title_lbl = QLabel(
            f"Version <b>{update_info.latest_version}</b> ist verfügbar!"
        )
        title_lbl.setFont(hdr_font)
        title_lbl.setStyleSheet(f"color: {KNX_DARK_GREEN};")
        hdr_text.addWidget(title_lbl)

        if update_info.current_version:
            curr_lbl = QLabel(
                f"Aktuell installiert: {update_info.current_version}"
            )
            curr_lbl.setStyleSheet("color: #666;")
            hdr_text.addWidget(curr_lbl)

        hdr_row.addLayout(hdr_text, 1)
        layout.addLayout(hdr_row)

        # ── Trennlinie ────────────────────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # ── Changelog ─────────────────────────────────────────────────────────
        if update_info.changelog:
            layout.addWidget(QLabel("<b>Neuerungen in dieser Version:</b>"))
            changelog = QTextEdit()
            changelog.setReadOnly(True)
            changelog.setPlainText(update_info.changelog)
            changelog.setMaximumHeight(180)
            changelog.setStyleSheet("background: #F5F5F5; border: 1px solid #DDD;")
            layout.addWidget(changelog)

        # ── Auto-Check-Checkbox ────────────────────────────────────────────────
        self._auto_check = QCheckBox(
            "Beim Programmstart automatisch nach Updates suchen (NFA-111)"
        )
        self._auto_check.setChecked(True)
        layout.addWidget(self._auto_check)

        # ── Buttons ───────────────────────────────────────────────────────────
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line2)

        btn_row = QHBoxLayout()

        btn_ignore = QPushButton("Version ignorieren")
        btn_ignore.setObjectName("secondary")
        btn_ignore.setToolTip(
            "Diese Version nicht mehr anzeigen (bis zum nächsten Release)"
        )
        btn_ignore.clicked.connect(self._on_ignore)
        btn_row.addWidget(btn_ignore)

        btn_row.addStretch()

        btn_later = QPushButton("Später erinnern")
        btn_later.setObjectName("secondary")
        btn_later.setToolTip("Beim nächsten Start wieder erinnern")
        btn_later.clicked.connect(self.reject)
        btn_row.addWidget(btn_later)

        if update_info.download_url:
            btn_download = QPushButton("⬇  Download öffnen")
            btn_download.setStyleSheet(
                f"background-color: {KNX_GREEN}; color: white; font-weight: bold;"
            )
            btn_download.setToolTip(
                f"Öffnet {update_info.download_url} im Standard-Browser"
            )
            btn_download.clicked.connect(self._on_download)
            btn_row.addWidget(btn_download)
        else:
            btn_close = QPushButton("Schliessen")
            btn_close.clicked.connect(self.reject)
            btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    def _on_download(self):
        """Oeffnet den Download-Link im Browser und schliesst den Dialog."""
        QDesktopServices.openUrl(QUrl(self._update_info.download_url))
        self.accept()

    def _on_ignore(self):
        """Markiert die Version zum Ignorieren und schliesst den Dialog."""
        self._ignore_version = True
        self.accept()

    @property
    def auto_check_enabled(self) -> bool:
        """True wenn der automatische Update-Check aktiviert bleiben soll."""
        return self._auto_check.isChecked()

    @property
    def ignored_version(self) -> str | None:
        """Die zu ignorierende Version, oder None wenn nicht ignoriert."""
        return self._update_info.latest_version if self._ignore_version else None
