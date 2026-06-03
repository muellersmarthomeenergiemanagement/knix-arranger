"""
Onboarding-Tour fuer Neueinsteiger (FA-1106)

Wird beim ersten Start angezeigt und fuehrt den Benutzer in 6 Schritten
durch die wichtigsten Konzepte des KNiX Arrangers.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QWidget, QCheckBox, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ..styles import KNX_GREEN, KNX_DARK_GREEN


# ── Tourinhalt ─────────────────────────────────────────────────────────────────

_TOUR_STEPS = [
    {
        "title": "Willkommen im KNiX Arranger!",
        "icon": "🏠",
        "content": (
            "<p>Der <b>KNiX Arranger</b> ist Ihr professionelles Werkzeug zur Planung "
            "und Dokumentation von KNX-Gebäudeautomationsprojekten.</p>"
            "<table border='0' cellspacing='0' cellpadding='8' style='width:100%; border-collapse:collapse; margin:10px 0;'>"
            "<tr style='background:#1B5E20; color:white;'>"
            "<td style='padding:8px 12px; border-radius:4px 4px 0 0;'><b>Was der KNiX Arranger für Sie erledigt</b></td>"
            "</tr>"
            "<tr style='background:#E8F5E9;'><td style='padding:6px 12px; border-bottom:1px solid #C5E1A5;'>&#10003; &nbsp;KNX-Busstruktur (Topologie) automatisch berechnen</td></tr>"
            "<tr style='background:white;'><td style='padding:6px 12px; border-bottom:1px solid #C5E1A5;'>&#10003; &nbsp;Alle Gruppenadressen nach KNX Swiss Richtlinien generieren</td></tr>"
            "<tr style='background:#E8F5E9;'><td style='padding:6px 12px; border-bottom:1px solid #C5E1A5;'>&#10003; &nbsp;Komplettes Revisionspaket und Bauherr-Anleitung erstellen</td></tr>"
            "<tr style='background:white;'><td style='padding:6px 12px; border-radius:0 0 4px 4px;'>&#10003; &nbsp;ETS6-kompatible CSV- und KNXPROJ-Dateien exportieren</td></tr>"
            "</table>"
            "<p style='color:#666; font-size:11px;'>Diese kurze Tour dauert ca. 2 Minuten.</p>"
        ),
    },
    {
        "title": "Neues Projekt oder Import?",
        "icon": "📂",
        "content": (
            "<p>Sie haben zwei Möglichkeiten, ein Projekt zu starten:</p>"
            "<table border='0' cellspacing='0' cellpadding='0' style='width:100%; margin:8px 0;'>"
            "<tr><td style='padding:8px;'>"
            "<div style='background:#1B5E20; color:white; border-radius:6px; padding:10px 14px;'>"
            "<b>Option 1 – Neues Projekt</b><br>"
            "<span style='font-size:11px;'>Seitenleiste → Neues Projekt → 13-Schritt-Wizard</span>"
            "</div>"
            "</td></tr>"
            "<tr><td style='padding:4px 8px; text-align:center; color:#888; font-size:20px;'>&#8597;</td></tr>"
            "<tr><td style='padding:8px;'>"
            "<div style='background:#1565C0; color:white; border-radius:6px; padding:10px 14px;'>"
            "<b>Option 2 – ETS6-Import</b><br>"
            "<span style='font-size:11px;'>Datei → Import &nbsp;|&nbsp; CSV &nbsp;·&nbsp; XLSX &nbsp;·&nbsp; KNXPROJ</span>"
            "</div>"
            "</td></tr>"
            "</table>"
            "<p style='font-size:11px; color:#666;'>Beide Wege führen zur gleichen Projektübersicht. "
            "Der Wizard ist der empfohlene Einstieg für neue Projekte.</p>"
        ),
    },
    {
        "title": "Der 13-Schritt-Wizard",
        "icon": "🧙",
        "content": (
            "<p>Der Wizard führt Sie strukturiert durch alle Planungsschritte:</p>"
            "<table border='0' cellspacing='0' cellpadding='4' style='width:100%; border-collapse:collapse; font-size:11px;'>"
            "<tr style='background:#1B5E20; color:white;'>"
            "<td style='padding:5px 8px; width:26px;'><b>#</b></td>"
            "<td style='padding:5px 8px;'><b>Schritt</b></td>"
            "<td style='padding:5px 8px;'><b>Ergebnis</b></td>"
            "</tr>"
            "<tr style='background:#F1F8E9;'><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>1</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'><b>Gebäudestruktur</b></td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Stockwerke &amp; HG-Nummern</td></tr>"
            "<tr style='background:white;'><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>2</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Wohnungen / Zonen</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>1 Zone = 1 KNX-Linie</td></tr>"
            "<tr style='background:#F1F8E9;'><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>3</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Räume</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Raumnummern E01, O01…</td></tr>"
            "<tr style='background:white;'><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>4–5</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Verteiler + Gewerke</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>HV/UV, Licht/Jalousie/Heizung…</td></tr>"
            "<tr style='background:#F1F8E9;'><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>6–8</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Topologie + Aktoren</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Linien, Koppler, Aktoren</td></tr>"
            "<tr style='background:white;'><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>9–10</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Szenen + Gruppenadressen</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Vollständige GA-Struktur</td></tr>"
            "<tr style='background:#F1F8E9;'><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>11–12</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Sensoren + Funktionen</td><td style='padding:4px 8px; border-bottom:1px solid #C5E1A5;'>Bedienelemente + Tastenbelegung</td></tr>"
            "<tr style='background:white;'><td style='padding:4px 8px;'><b>13</b></td><td style='padding:4px 8px;'><b>Export</b></td><td style='padding:4px 8px;'>CSV, KNXPROJ, Revisionspaket</td></tr>"
            "</table>"
        ),
    },
    {
        "title": "Gewerke-Konzept",
        "icon": "⚡",
        "content": (
            "<p><b>Gewerke</b> sind das Herzstück: Sie beschreiben, welche Funktionen ein Raum hat.</p>"
            "<table border='0' cellspacing='0' cellpadding='5' style='width:100%; border-collapse:collapse; font-size:12px; margin:8px 0;'>"
            "<tr style='background:#1B5E20; color:white;'>"
            "<td style='padding:5px 10px;'><b>Code</b></td>"
            "<td style='padding:5px 10px;'><b>Funktion</b></td>"
            "<td style='padding:5px 10px;'><b>Erzeugt</b></td>"
            "</tr>"
            "<tr style='background:#F1F8E9;'><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'><b>L</b></td><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'>Licht (schaltbar)</td><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'>Schaltaktor-Kanal + 2 GAs</td></tr>"
            "<tr style='background:white;'><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'><b>LD</b></td><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'>Licht (dimmbar)</td><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'>Dimmaktor-Kanal + 4 GAs</td></tr>"
            "<tr style='background:#F1F8E9;'><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'><b>J</b></td><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'>Jalousie / Storen</td><td style='padding:4px 10px; border-bottom:1px solid #C5E1A5;'>Jalousieaktor-Kanal + 5 GAs</td></tr>"
            "<tr style='background:white;'><td style='padding:4px 10px;'><b>H</b></td><td style='padding:4px 10px;'>Heizung</td><td style='padding:4px 10px;'>Heizungsaktor + Thermostat GAs</td></tr>"
            "</table>"
            "<p style='margin-top:8px;'><b>Beispiel Wohnzimmer:</b></p>"
            "<div style='background:#F9FBE7; border:1px solid #C5E1A5; border-radius:4px; padding:8px 12px; font-size:12px;'>"
            "L × 2 &nbsp;+&nbsp; LD × 1 &nbsp;+&nbsp; J × 2 &nbsp;+&nbsp; H × 1<br>"
            "<span style='color:#555; font-size:11px;'>→ 1 Schaltaktor (2 Kan.) + 1 Dimmaktor + 1 Jalousieaktor (2 Kan.) + 1 Heizungsaktor</span>"
            "</div>"
        ),
    },
    {
        "title": "Gruppenadressen nach KNX Swiss",
        "icon": "📋",
        "content": (
            "<p>Der KNiX Arranger generiert Gruppenadressen automatisch nach den "
            "<b>KNX Swiss Projektrichtlinien</b>.</p>"
            "<p><b>3-stufige GA-Struktur:</b></p>"
            "<table border='0' cellspacing='0' cellpadding='0' style='width:100%; margin:8px 0;'>"
            "<tr><td>"
            "<div style='background:#1B5E20; color:white; padding:7px 12px; border-radius:4px; font-size:12px;'>"
            "<b>Hauptgruppe (HG)</b> &nbsp; 0=Zentral &nbsp;|&nbsp; 1=KG &nbsp;|&nbsp; 2=EG &nbsp;|&nbsp; 3=OG1 …"
            "</div></td></tr>"
            "<tr><td style='text-align:center; color:#888; font-size:16px; padding:2px;'>&#9660;</td></tr>"
            "<tr><td>"
            "<div style='background:#1565C0; color:white; padding:7px 12px; border-radius:4px; font-size:12px; margin-left:16px;'>"
            "<b>Mittelgruppe (MG)</b> &nbsp; 0=Licht &nbsp;|&nbsp; 1=Jalousie &nbsp;|&nbsp; 2=Heizung &nbsp;|&nbsp; 5=Lüftung …"
            "</div></td></tr>"
            "<tr><td style='text-align:center; color:#888; font-size:16px; padding:2px;'>&#9660;</td></tr>"
            "<tr><td>"
            "<div style='background:#E3F2FD; color:#0D47A1; padding:7px 12px; border-radius:4px; font-size:12px; margin-left:32px; border:1px solid #BBDEFB;'>"
            "<b>Untergruppe (UG)</b> &nbsp; Einzelne GA-Adressen in 5er-/10er-Blöcken"
            "</div></td></tr>"
            "</table>"
            "<p style='font-size:12px; margin-top:8px;'>"
            "<b>Variante A:</b> Rückmeldungen in gleicher MG (kompakt, EFH)<br>"
            "<b>Variante B:</b> Rückmeldungen in separater MG 6/7 (übersichtlich, MFH)"
            "</p>"
        ),
    },
    {
        "title": "Alles bereit – los geht's!",
        "icon": "🚀",
        "content": (
            "<p>Sie sind bereit, Ihr erstes KNX-Projekt zu planen!</p>"
            "<table border='0' cellspacing='0' cellpadding='0' style='width:100%; margin:10px 0;'>"
            "<tr><td style='padding:5px 0;'>"
            "<div style='display:inline-block; background:#1B5E20; color:white; border-radius:50%; "
            "width:24px; height:24px; text-align:center; line-height:24px; font-weight:bold; font-size:12px;'>1</div>"
            "&nbsp;&nbsp;<b>Neues Projekt</b> in der Seitenleiste anklicken"
            "</td></tr>"
            "<tr><td style='padding:5px 0;'>"
            "<div style='display:inline-block; background:#1565C0; color:white; border-radius:50%; "
            "width:24px; height:24px; text-align:center; line-height:24px; font-weight:bold; font-size:12px;'>2</div>"
            "&nbsp;&nbsp;<b>Projektname und Nummer</b> eingeben"
            "</td></tr>"
            "<tr><td style='padding:5px 0;'>"
            "<div style='display:inline-block; background:#1565C0; color:white; border-radius:50%; "
            "width:24px; height:24px; text-align:center; line-height:24px; font-weight:bold; font-size:12px;'>3</div>"
            "&nbsp;&nbsp;<b>Vorlage wählen</b> oder leer starten"
            "</td></tr>"
            "<tr><td style='padding:5px 0;'>"
            "<div style='display:inline-block; background:#1565C0; color:white; border-radius:50%; "
            "width:24px; height:24px; text-align:center; line-height:24px; font-weight:bold; font-size:12px;'>4</div>"
            "&nbsp;&nbsp;<b>Wizard starten</b> und Schritt für Schritt vorgehen"
            "</td></tr>"
            "<tr><td style='padding:5px 0;'>"
            "<div style='display:inline-block; background:#2E7D32; color:white; border-radius:50%; "
            "width:24px; height:24px; text-align:center; line-height:24px; font-weight:bold; font-size:12px;'>5</div>"
            "&nbsp;&nbsp;<b>Export</b> erstellen – CSV, KNXPROJ, Revisionspaket"
            "</td></tr>"
            "</table>"
            "<div style='background:#F9FBE7; border:1px solid #C5E1A5; border-radius:4px; padding:8px 12px; margin-top:8px; font-size:12px;'>"
            "&#128161; &nbsp;<b>Hilfe:</b> Jederzeit <b>F1</b> drücken oder den <b>?</b>-Button "
            "in jedem Wizard-Schritt nutzen."
            "</div>"
            "<p style='color:#888; font-size:10px; margin-top:8px;'>Diese Tour über "
            "<i>Hilfe → Erste Schritte</i> jederzeit erneut aufrufen.</p>"
        ),
    },
]


class OnboardingTourDialog(QDialog):
    """6-Schritt Onboarding-Tour fuer Neueinsteiger (FA-1106)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Erste Schritte – KNiX Arranger")
        self.setMinimumSize(620, 500)
        self.setModal(True)

        self._current = 0
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Fortschrittsleiste (Punkte) ────────────────────────────────────────
        dots_row = QHBoxLayout()
        dots_row.addStretch()
        self._dots: list[QLabel] = []
        for i in range(len(_TOUR_STEPS)):
            dot = QLabel("●")
            dot.setAlignment(Qt.AlignCenter)
            self._dots.append(dot)
            dots_row.addWidget(dot)
        dots_row.addStretch()
        layout.addLayout(dots_row)

        # ── Stack ──────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        for step in _TOUR_STEPS:
            self._stack.addWidget(self._build_step_widget(step))
        layout.addWidget(self._stack, 1)

        # ── Trennlinie ─────────────────────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # ── Fussbereich ────────────────────────────────────────────────────────
        foot = QHBoxLayout()

        self._no_show_check = QCheckBox("Tour beim nächsten Start nicht mehr anzeigen")
        foot.addWidget(self._no_show_check)

        foot.addStretch()

        self._btn_skip = QPushButton("Tour überspringen")
        self._btn_skip.setObjectName("secondary")
        self._btn_skip.clicked.connect(self.reject)
        foot.addWidget(self._btn_skip)

        self._btn_back = QPushButton("← Zurück")
        self._btn_back.setObjectName("secondary")
        self._btn_back.clicked.connect(self._go_back)
        foot.addWidget(self._btn_back)

        self._btn_next = QPushButton("Weiter →")
        self._btn_next.setStyleSheet(f"background-color: {KNX_GREEN}; color: white;")
        self._btn_next.clicked.connect(self._go_next)
        foot.addWidget(self._btn_next)

        layout.addLayout(foot)

        self._update_ui()

    @staticmethod
    def _build_step_widget(step: dict) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 10, 20, 10)

        # Icon + Titel
        title_row = QHBoxLayout()
        icon_lbl = QLabel(step["icon"])
        icon_font = QFont()
        icon_font.setPointSize(32)
        icon_lbl.setFont(icon_font)
        icon_lbl.setFixedWidth(60)
        title_row.addWidget(icon_lbl)

        title_lbl = QLabel(step["title"])
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {KNX_DARK_GREEN};")
        title_lbl.setWordWrap(True)
        title_row.addWidget(title_lbl, 1)
        vl.addLayout(title_row)

        vl.addSpacing(8)

        # Inhalt
        from PySide6.QtWidgets import QTextBrowser
        content = QTextBrowser()
        content.setReadOnly(True)
        content.setOpenExternalLinks(True)
        content.setHtml(step["content"])
        content.setFrameShape(QFrame.NoFrame)
        content.setStyleSheet("background: transparent;")
        vl.addWidget(content, 1)

        return w

    def _update_ui(self):
        self._stack.setCurrentIndex(self._current)
        n = len(_TOUR_STEPS)

        # Dots einfärben
        for i, dot in enumerate(self._dots):
            if i == self._current:
                dot.setStyleSheet(f"color: {KNX_GREEN}; font-size: 18px;")
            elif i < self._current:
                dot.setStyleSheet("color: #90A4AE; font-size: 14px;")
            else:
                dot.setStyleSheet("color: #CFD8DC; font-size: 14px;")

        self._btn_back.setEnabled(self._current > 0)

        if self._current == n - 1:
            self._btn_next.setText("Fertig ✓")
            self._btn_next.setStyleSheet(
                f"background-color: {KNX_DARK_GREEN}; color: white;"
            )
        else:
            self._btn_next.setText("Weiter →")
            self._btn_next.setStyleSheet(
                f"background-color: {KNX_GREEN}; color: white;"
            )

    def _go_next(self):
        if self._current < len(_TOUR_STEPS) - 1:
            self._current += 1
            self._update_ui()
        else:
            self.accept()

    def _go_back(self):
        if self._current > 0:
            self._current -= 1
            self._update_ui()

    @property
    def suppress_on_next_start(self) -> bool:
        """True wenn der Benutzer die Tour beim nächsten Start nicht mehr sehen will."""
        return self._no_show_check.isChecked()
