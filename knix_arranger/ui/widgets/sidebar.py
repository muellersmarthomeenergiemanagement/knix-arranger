"""
Sidebar-Navigation (NFA-021)
Scrollbare Seitenleiste mit gepinntem Kopf- und Fussbereich.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QButtonGroup,
    QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt
from ..styles import KNX_DARK_GREEN, KNX_BLUE

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


class SidebarButton(QPushButton):
    """Navigationsbutton für die Sidebar."""

    def __init__(self, text: str, icon_text: str = "", parent=None):
        display = f"  {icon_text}  {text}" if icon_text else f"  {text}"
        super().__init__(display, parent)
        self.setCheckable(True)
        self.setMinimumHeight(34)
        self.setMaximumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setProperty("cssClass", "sidebar")


class Sidebar(QWidget):
    """Seitenleiste für Navigation mit scrollbarem Navigationsbereich."""

    navigation_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._buttons: dict[str, SidebarButton] = {}
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
        self._nav_layout.setContentsMargins(4, 6, 4, 6)
        self._nav_layout.setSpacing(2)

        # Navigationsbuttons
        self._add_section("PROJEKT")
        self._add_button("new_project",  "Neues Projekt",  "N")
        self._add_button("open_project", "Projekt öffnen", "O")
        self._add_button("import_csv",   "ETS6 Import",    "I")

        self._add_section("WIZARD")
        self._add_button("wizard", "13-Schritt-Wizard", "W")

        self._add_section("ANSICHTEN")
        self._add_button("overview",          "Übersicht",             "U")
        self._add_button("building",          "Gebäude",               "G")
        self._add_button("topology",          "Topologie",             "T")
        self._add_button("addresses",         "Gruppenadressen",       "A")
        self._add_button("gewerke",           "Gewerke",               "K")
        self._add_button("validation",        "Validierung",           "V")
        self._add_button("scenes",            "Szenen",                "Z")
        self._add_button("quotations",        "Offertanfragen",        "F")
        self._add_button("customer_quotes",   "Kundenofferte",         "O")
        self._add_button("datasheets",        "Produktdatenblätter",   "P")
        self._add_button("topology_report",   "Topologie-Report",      "R")
        self._add_button("topology_diagram",  "Topologie-Diagramm",   "D")
        self._add_button("material_list",     "Materialliste",         "M")
        self._add_button("co_linking",        "CO-Verknüpfung",        "C")
        self._add_button("linking_matrix",    "Verknüpfungsmatrix",    "X")
        self._add_button("cable_length",      "Leitungslängen",        "L")
        self._add_button("dali_config",       "DALI-Konfiguration",   "DA")
        self._add_button("knx_secure",        "KNX Secure",           "KS")
        self._add_button("time_programs",     "Zeitsteuerung",        "ZT")
        self._add_button("bauherr_form",      "Bauherren-Beratung",  "BB")
        self._add_button("commissioning",     "Inbetriebnahme",      "IB")

        self._add_section("EXPORT")
        self._add_button("export",   "CSV Export", "E")
        self._add_button("reports",  "Berichte",   "B")

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
        self._add_button("help",     "Hilfe (F1)",   "?", layout=footer_layout)
        self._add_button("settings", "Einstellungen", "S", layout=footer_layout)
        outer.addWidget(footer)

        # Button-Klick verbinden
        self._button_group.buttonClicked.connect(self._on_button_clicked)

    def _add_section(self, title: str):
        label = QLabel(f"  {title}")
        label.setFixedHeight(22)
        label.setStyleSheet(
            "color: rgba(255,255,255,140); font-size: 10px; "
            "font-weight: bold; padding: 4px 0 1px 4px; "
            "background-color: transparent;"
        )
        self._nav_layout.addWidget(label)

    def _add_button(self, key: str, text: str, icon_text: str = "",
                    layout=None):
        btn = SidebarButton(text, icon_text)
        self._buttons[key] = btn
        self._button_group.addButton(btn)
        target = layout if layout is not None else self._nav_layout
        target.addWidget(btn)

    def _on_button_clicked(self, button: QPushButton):
        for key, btn in self._buttons.items():
            if btn == button:
                self.navigation_changed.emit(key)
                break

    def select(self, key: str):
        """Wählt einen Button programmatisch aus."""
        if key in self._buttons:
            self._buttons[key].setChecked(True)
