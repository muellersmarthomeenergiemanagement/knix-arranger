"""
Sidebar-Navigation (NFA-021)
Scrollbare Seitenleiste mit gepinntem Kopf- und Fussbereich.

Die Ansichten sind nach Arbeitsablauf in einklappbare Gruppen gegliedert.
Beim Wechsel auf eine Ansicht wird deren Gruppe automatisch aufgeklappt.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QButtonGroup,
    QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt, QSize, QTimer
from ..styles import KNX_DARK_GREEN, KNX_BLUE, FONT_SMALL
from ..icons import icon

# Scrollbar-Styling passend zum dunklen Sidebar-Hintergrund
_SCROLLBAR_QSS = """
QScrollBar:vertical {
    background: #2E5613;
    width: 6px;
    margin: 0;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,100);
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255,255,255,180);
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
}
"""

_GROUP_HEADER_QSS = f"""
QPushButton {{
    background-color: transparent;
    color: rgba(255,255,255,200);
    font-size: {FONT_SMALL}px;
    font-weight: bold;
    text-align: left;
    padding: 6px 6px 3px 4px;
    border: none;
}}
QPushButton:hover {{
    color: white;
    background-color: rgba(255,255,255,20);
}}
"""

# (Gruppentitel, [(Schlüssel, Beschriftung, Icon), ...])
# Reihenfolge der Gruppen folgt dem Arbeitsablauf eines Projekts.
NAV_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Projekt", [
        ("new_project",  "Neues Projekt",  "file-plus"),
        ("open_project", "Projekt öffnen", "folder-open"),
        ("import_csv",   "ETS6 Import",    "file-import"),
    ]),
    ("Planung", [
        ("overview",      "Übersicht",           "layout-dashboard"),
        ("building",      "Gebäude",             "building"),
        ("gewerke",       "Gewerke",             "plug-connected"),
        ("scenes",        "Szenen",              "sparkles"),
        ("time_programs", "Zeitsteuerung",       "clock"),
        ("bauherr_form",  "Bauherren-Beratung",  "users"),
    ]),
    ("Topologie & Geräte", [
        ("topology",          "Topologie",           "topology-star-3"),
        ("topology_diagram",  "Topologie-Diagramm",  "chart-dots-3"),
        ("topology_report",   "Topologie-Report",    "report"),
        ("material_list",     "Materialliste",       "list-details"),
        ("datasheets",        "Produktdatenblätter", "file-description"),
        ("cable_length",      "Leitungslängen",      "ruler-measure"),
        ("dali_config",       "DALI-Konfiguration",  "bulb"),
        ("knx_secure",        "KNX Secure",          "shield-lock"),
    ]),
    ("Adressen & Logik", [
        ("addresses",       "Gruppenadressen",     "binary-tree"),
        ("co_linking",      "CO-Verknüpfung",      "link"),
        ("linking_matrix",  "Verknüpfungsmatrix",  "grid-dots"),
        ("validation",      "Validierung",         "circle-check"),
    ]),
    ("Angebot", [
        ("quotations",       "Offertanfragen",  "mail-forward"),
        ("customer_quotes",  "Kundenofferte",   "file-invoice"),
    ]),
    ("Abschluss & Dokumentation", [
        ("commissioning",  "Inbetriebnahme",      "checklist"),
        ("reports",        "Berichte",            "report-analytics"),
        ("export",         "CSV Export",          "file-export"),
        ("changelog",      "Änderungsprotokoll",  "history"),
    ]),
]


class SidebarButton(QPushButton):
    """Navigationsbutton für die Sidebar."""

    def __init__(self, text: str, icon_name: str = "", parent=None):
        super().__init__(f" {text}", parent)
        self.setCheckable(True)
        self.setMinimumHeight(32)
        self.setMaximumHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setProperty("cssClass", "sidebar")
        if icon_name:
            # weiss auf Grün, dunkelgrün auf dem weissen "aktiv"-Hintergrund
            self.setIcon(icon(icon_name, "#FFFFFF", checked_color=KNX_DARK_GREEN))
            self.setIconSize(QSize(18, 18))


class _NavGroup(QWidget):
    """Einklappbare Gruppe von Navigationsbuttons."""

    def __init__(self, title: str, expanded: bool, on_open=None, parent=None):
        super().__init__(parent)
        self._title = title
        self._on_open = on_open  # Akkordeon: Sidebar schliesst die übrigen Gruppen
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = QPushButton()
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setStyleSheet(_GROUP_HEADER_QSS)
        self._header.setIconSize(QSize(14, 14))
        self._header.clicked.connect(self._on_header_clicked)
        layout.addWidget(self._header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 4)
        self._body_layout.setSpacing(2)
        layout.addWidget(self._body)

        self._expanded = True
        self.set_expanded(expanded)

    def add_button(self, btn: QPushButton) -> None:
        self._body_layout.addWidget(btn)

    def _on_header_clicked(self) -> None:
        if not self._expanded and self._on_open is not None:
            self._on_open(self)
        else:
            self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded)
        # "&&": ein einfaches "&" wäre für Qt eine Tastenkürzel-Markierung
        self._header.setText(f" {self._title.upper().replace('&', '&&')}")
        self._header.setIcon(icon(
            "chevron-down" if expanded else "chevron-right", "#FFFFFF", size=14))

    @property
    def expanded(self) -> bool:
        return self._expanded


class Sidebar(QWidget):
    """Seitenleiste für Navigation mit scrollbarem Navigationsbereich."""

    navigation_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._buttons: dict[str, SidebarButton] = {}
        self._group_of: dict[str, _NavGroup] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Kopfzeile (gepinnt) ──
        title = QLabel("KNiX Arranger")
        title.setAlignment(Qt.AlignCenter)
        title.setFixedHeight(48)
        title.setStyleSheet(
            f"color: {KNX_BLUE}; font-size: 16px; font-weight: bold; "
            f"padding: 8px 4px; background-color: white; "
            f"border-bottom: 2px solid {KNX_BLUE};"
        )
        outer.addWidget(title)

        # ── Wizard als Hauptweg (gepinnt, immer sichtbar) ──
        wizard_area = QWidget()
        wizard_area.setObjectName("sidebar_wizard")
        wizard_area.setStyleSheet(
            f"QWidget#sidebar_wizard {{ background-color: {KNX_DARK_GREEN}; }}"
        )
        wizard_layout = QVBoxLayout(wizard_area)
        wizard_layout.setContentsMargins(4, 8, 4, 4)
        self._add_button("wizard", "13-Schritt-Wizard", "wand", layout=wizard_layout)
        outer.addWidget(wizard_area)

        # ── Scrollbarer Navigationsbereich ──
        scroll = QScrollArea()
        scroll.setObjectName("sidebar_scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(_SCROLLBAR_QSS)

        nav_widget = QWidget()
        nav_widget.setObjectName("sidebar_nav")
        nav_widget.setStyleSheet(
            f"QWidget#sidebar_nav {{ background-color: {KNX_DARK_GREEN}; }}"
        )
        self._nav_layout = QVBoxLayout(nav_widget)
        self._nav_layout.setContentsMargins(4, 2, 4, 6)
        self._nav_layout.setSpacing(2)

        # Akkordeon: immer nur eine Gruppe offen, damit die Leiste auch bei
        # 720 px Fensterhöhe ohne Scrollen passt. Anfangs "Planung"; beim
        # Wechsel auf eine Ansicht öffnet sich deren Gruppe automatisch.
        self._scroll = scroll
        self._groups: list[_NavGroup] = []
        for group_title, entries in NAV_GROUPS:
            group = _NavGroup(group_title, expanded=group_title == "Planung",
                              on_open=self._open_only)
            self._groups.append(group)
            for key, text, icon_name in entries:
                btn = self._add_button(key, text, icon_name, layout=None)
                group.add_button(btn)
                self._group_of[key] = group
            self._nav_layout.addWidget(group)

        self._nav_layout.addStretch()

        scroll.setWidget(nav_widget)
        outer.addWidget(scroll, 1)

        # ── Fusszeile (gepinnt) ──
        footer = QWidget()
        footer.setObjectName("sidebar_footer")
        footer.setStyleSheet(
            f"QWidget#sidebar_footer {{ "
            f"background-color: {KNX_DARK_GREEN}; "
            f"border-top: 1px solid rgba(255,255,255,40); }}"
        )
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(4, 4, 4, 4)
        footer_layout.setSpacing(2)
        self._add_button("help",     "Hilfe (F1)",    "help-circle", layout=footer_layout)
        self._add_button("settings", "Einstellungen", "settings",    layout=footer_layout)
        outer.addWidget(footer)

        # Button-Klick verbinden
        self._button_group.buttonClicked.connect(self._on_button_clicked)

    def _add_button(self, key: str, text: str, icon_name: str = "",
                    layout=None) -> SidebarButton:
        btn = SidebarButton(text, icon_name)
        self._buttons[key] = btn
        self._button_group.addButton(btn)
        if layout is not None:
            layout.addWidget(btn)
        return btn

    def _on_button_clicked(self, button: QPushButton):
        for key, btn in self._buttons.items():
            if btn == button:
                self.navigation_changed.emit(key)
                break

    def _open_only(self, group: _NavGroup) -> None:
        for g in self._groups:
            g.set_expanded(g is group)

    def select(self, key: str):
        """Wählt einen Button programmatisch aus, öffnet seine Gruppe und
        scrollt ihn in den sichtbaren Bereich."""
        if key in self._buttons:
            group = self._group_of.get(key)
            if group is not None and not group.expanded:
                self._open_only(group)
            btn = self._buttons[key]
            btn.setChecked(True)
            if group is not None:
                QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(btn))
