"""
Willkommensbildschirm (NFA-010, FA-3105f)
Drei Einstiege nach Ausgangslage (neue Anlage planen, ETS-Projekt einlesen,
Anlage vom Bus aufnehmen), darunter Weiterarbeiten mit den zuletzt
verwendeten Projekten; Rechte und Lizenz in der Fusszeile.
"""
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ... import __version__, APP_NAME, __copyright__
from ..styles import KNX_GREEN, KNX_DARK_GREEN, KNX_PRIMARY

ACTION_NEW = "new"                 # neue Anlage planen
ACTION_OPEN = "open"
ACTION_IMPORT = "import"           # bestehende Anlage: ETS-Projekt einlesen
ACTION_RECONSTRUCT = "reconstruct"  # bestehende Anlage ohne Projektdatei (vom Bus)


def recent_place(path: str, projects_folder: str = "") -> str:
    """Wo ein Projekt liegt, kurz: «Projekte» im Arbeitsverzeichnis, sonst
    die zwei Ordner über dem Projektordner («AI › KNX Arranger Test3»).
    Unterscheidet gleichnamige Projekte in der Liste."""
    project_dir = os.path.dirname(os.path.normpath(path))
    parent = os.path.dirname(project_dir)
    if projects_folder and os.path.normcase(os.path.normpath(parent)) == \
            os.path.normcase(os.path.normpath(projects_folder)):
        return "Projekte im Arbeitsverzeichnis"
    parts = [p for p in parent.replace("\\", "/").split("/") if p and not p.endswith(":")]
    return " › ".join(parts[-2:])


def _card(title: str, subtitle: str, primary: bool) -> QPushButton:
    """Einstieg: Knopf mit Titel und erklärender Zeile."""
    button = QPushButton()
    button.setFixedHeight(76)
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    button.setCursor(Qt.PointingHandCursor)
    background, color, hover = (KNX_PRIMARY, "white", KNX_DARK_GREEN) if primary else \
        ("white", KNX_DARK_GREEN, "#F0F8F0")
    border = "none" if primary else f"2px solid {KNX_GREEN}"
    button.setStyleSheet(
        f"QPushButton {{ background-color: {background}; border: {border}; "
        f"border-radius: 6px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}")
    layout = QVBoxLayout(button)
    layout.setContentsMargins(16, 10, 12, 10)
    layout.setSpacing(2)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold; "
                            "background: transparent; border: none;")
    sub_lbl = QLabel(subtitle)
    sub_lbl.setWordWrap(True)
    sub_lbl.setStyleSheet(f"color: {color}; font-size: 12px; background: transparent; "
                          "border: none;")
    for label in (title_lbl, sub_lbl):
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(label)
    button.setAccessibleName(f"{title} – {subtitle}")
    return button


class WelcomeDialog(QDialog):
    """Willkommensbildschirm: Einstieg nach Ausgangslage, zuletzt verwendet."""

    def __init__(self, parent=None, recent_projects: list[str] | None = None,
                 projects_folder: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Willkommen bei {APP_NAME}")
        self._action: str | None = None
        self._selected_path: str | None = None
        self._recent_projects = [p for p in (recent_projects or []) if os.path.exists(p)][:5]
        self.setFixedSize(820, 420 + 38 * len(self._recent_projects))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Banner ──
        banner = QFrame()
        banner.setObjectName("welcome_banner")
        banner.setStyleSheet(
            f"QFrame#welcome_banner {{ background-color: {KNX_DARK_GREEN}; border: none; }}")
        banner.setFixedHeight(130)
        banner_layout = QVBoxLayout(banner)
        banner_layout.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(APP_NAME)
        title_font = QFont()
        title_font.setPointSize(26)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("color: white; background: transparent;")
        banner_layout.addWidget(title_lbl)

        tagline_lbl = QLabel(f"Version {__version__}  ·  KNX planen, einlesen und in Betrieb "
                             "nehmen – nach KNX Swiss Richtlinien 2024")
        tagline_lbl.setAlignment(Qt.AlignCenter)
        tagline_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.80); font-size: 12px; background: transparent;")
        banner_layout.addWidget(tagline_lbl)
        layout.addWidget(banner)

        # ── Inhalt ──
        content = QFrame()
        content.setStyleSheet("background-color: #FAFAFA;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 24, 40, 18)
        content_layout.setSpacing(12)

        content_layout.addWidget(self._heading("Neu beginnen"))
        btn_row = QHBoxLayout()
        btn_row.setSpacing(14)
        self._btn_new = _card("Neue Anlage planen", "Vom Grundriss zur ETS", primary=True)
        self._btn_new.setToolTip("Neues Projekt anlegen und im Wizard planen")
        self._btn_new.clicked.connect(lambda: self._choose(ACTION_NEW))
        self._btn_import = _card("ETS-Projekt einlesen", "Bestehende Anlage mit .knxproj",
                                 primary=False)
        self._btn_import.setToolTip(
            "Bestehende Anlage aus der ETS (.knxproj, XLSX- oder CSV-Export) einlesen und "
            "prüfen. Das Projekt wird im Arbeitsverzeichnis angelegt.")
        self._btn_import.clicked.connect(lambda: self._choose(ACTION_IMPORT))
        self._btn_bus = _card("Anlage vom Bus aufnehmen", "Bestehende Anlage ohne "
                              "Projektdatei", primary=False)
        self._btn_bus.setToolTip(
            "Leeres Projekt anlegen und die Anlage Schritt für Schritt vom Bus aufnehmen: "
            "Teilnehmer suchen, GAs lesen, Bedeutung ergänzen, Gebäude erfassen, Rundgang.")
        self._btn_bus.clicked.connect(lambda: self._choose(ACTION_RECONSTRUCT))
        for button in (self._btn_new, self._btn_import, self._btn_bus):
            btn_row.addWidget(button)
        content_layout.addLayout(btn_row)
        content_layout.addSpacing(8)

        # Weiterarbeiten: Öffnen neben der Überschrift, darunter zuletzt verwendet
        open_row = QHBoxLayout()
        open_row.addWidget(self._heading("Weiterarbeiten"))
        open_row.addStretch(1)
        self._btn_open = QPushButton("Projekt öffnen…")
        self._btn_open.setStyleSheet(
            f"QPushButton {{ background-color: white; color: {KNX_DARK_GREEN}; "
            f"font-size: 12px; font-weight: bold; border-radius: 6px; "
            f"border: 2px solid {KNX_GREEN}; padding: 6px 14px; }}"
            f"QPushButton:hover {{ background-color: #F0F8F0; }}")
        self._btn_open.clicked.connect(lambda: self._choose(ACTION_OPEN))
        open_row.addWidget(self._btn_open)
        content_layout.addLayout(open_row)

        if self._recent_projects:
            recent_frame = QFrame()
            recent_frame.setStyleSheet(
                "background-color: white; border: 1px solid #E0E0E0; border-radius: 6px;")
            recent_layout = QVBoxLayout(recent_frame)
            recent_layout.setContentsMargins(4, 4, 4, 4)
            recent_layout.setSpacing(2)
            self._recent_buttons: list[QPushButton] = []
            for path in self._recent_projects:
                recent_layout.addWidget(self._recent_button(path, projects_folder))
            content_layout.addWidget(recent_frame)
        else:
            empty = QLabel("Noch keine Projekte geöffnet.")
            empty.setStyleSheet("color: #666666; font-size: 12px;")
            content_layout.addWidget(empty)

        content_layout.addStretch()

        # ── Fusszeile: Rechte, Claude Code, ohne Projekt ──
        footer_row = QHBoxLayout()
        footer_row.setSpacing(0)
        rights_lbl = QLabel(f"{__copyright__} – alle Rechte vorbehalten\n"
                            "Erstellt mit Claude Code – Anthropic")
        rights_lbl.setToolTip("Die Software darf ohne ausdrückliche Genehmigung weder "
                              "kopiert noch weitergegeben werden.")
        rights_lbl.setStyleSheet("color: #666666; font-size: 11px;")
        footer_row.addWidget(rights_lbl)
        footer_row.addStretch()
        btn_cancel = QPushButton("Ohne Projekt fortfahren")
        btn_cancel.setToolTip("z.B. für Live-Monitor oder Busanalyse")
        btn_cancel.setStyleSheet(
            "color: #666666; border: none; font-size: 12px; "
            "background: transparent; padding: 4px 8px;")
        btn_cancel.clicked.connect(self.reject)
        footer_row.addWidget(btn_cancel)
        content_layout.addLayout(footer_row)

        layout.addWidget(content, 1)

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #333; font-weight: bold; font-size: 12px;")
        return label

    def _recent_button(self, path: str, projects_folder: str) -> QPushButton:
        button = QPushButton()
        button.setToolTip(path)
        button.setFixedHeight(32)
        button.setStyleSheet(
            "QPushButton { border: none; background: transparent; border-radius: 4px; }"
            "QPushButton:hover { background-color: #F0F8F0; }")
        row = QHBoxLayout(button)
        row.setContentsMargins(10, 0, 10, 0)
        name = QLabel(os.path.splitext(os.path.basename(path))[0])
        name.setStyleSheet("color: #333; font-size: 12px; background: transparent; "
                           "border: none;")
        place = QLabel(recent_place(path, projects_folder))
        place.setStyleSheet("color: #666666; font-size: 11px; background: transparent; "
                            "border: none;")
        for label in (name, place):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(name)
        row.addStretch(1)
        row.addWidget(place)
        button.setAccessibleName(f"{name.text()} – {place.text()}")
        button.clicked.connect(lambda _c=False, p=path: self._choose_recent(p))
        self._recent_buttons.append(button)
        return button

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _choose(self, action: str) -> None:
        self._action = action
        self.accept()

    def _choose_recent(self, path: str):
        self._action = ACTION_OPEN
        self._selected_path = path
        self.accept()

    @property
    def action(self) -> str | None:
        """ACTION_NEW, ACTION_OPEN, ACTION_IMPORT oder ACTION_RECONSTRUCT."""
        return self._action

    @property
    def selected_path(self) -> str | None:
        """Pfad eines direkt aus der Liste gewählten Projekts (oder None)."""
        return self._selected_path
