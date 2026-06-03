"""
KNX-Farbpalette und QSS-Stylesheet (NFA-021, NFA-022)
KNX-Gruen: #5EA126, Dunkelgruen, Blau, Weiss, Grau
"""

# KNX-Farbdefinitionen
KNX_GREEN = "#5EA126"
KNX_DARK_GREEN = "#3A6B19"
KNX_BLUE = "#1A5276"
KNX_LIGHT_BLUE = "#2980B9"
KNX_WHITE = "#FFFFFF"
KNX_LIGHT_GRAY = "#F0F0F0"
KNX_MEDIUM_GRAY = "#C0C0C0"
KNX_DARK_GRAY = "#404040"
KNX_RED = "#E74C3C"
KNX_ORANGE = "#E67E22"
KNX_YELLOW = "#F1C40F"

# Statusfarben
COLOR_ERROR = KNX_RED
COLOR_WARNING = KNX_ORANGE
COLOR_OK = KNX_GREEN
COLOR_INFO = KNX_LIGHT_BLUE

# Gewerk-Farben für GA-Baumansicht
GEWERK_COLORS = {
    "licht": "#F9E79F",       # Gelb
    "jalousie": "#AED6F1",    # Hellblau
    "heizung": "#F5B7B1",     # Hellrot
    "alarm": "#E74C3C",       # Rot
    "allgemein": "#D5DBDB",   # Grau
}


def get_main_stylesheet() -> str:
    """Gibt das Haupt-QSS-Stylesheet zurück."""
    return f"""
    /* Hauptfenster */
    QMainWindow {{
        background-color: {KNX_WHITE};
    }}

    /* Menueleiste */
    QMenuBar {{
        background-color: {KNX_WHITE};
        border-bottom: 1px solid {KNX_MEDIUM_GRAY};
        padding: 2px;
    }}
    QMenuBar::item:selected {{
        background-color: {KNX_GREEN};
        color: white;
    }}
    QMenu {{
        background-color: {KNX_WHITE};
        border: 1px solid {KNX_MEDIUM_GRAY};
    }}
    QMenu::item:selected {{
        background-color: {KNX_GREEN};
        color: white;
    }}

    /* Sidebar */
    #sidebar {{
        background-color: {KNX_DARK_GREEN};
        min-width: 220px;
        max-width: 220px;
    }}

    /* Sidebar-Buttons (ueber Property-Selektor) */
    QPushButton[cssClass="sidebar"] {{
        background-color: #4E8C20;
        color: white;
        text-align: left;
        padding: 5px 10px;
        border: 1px solid rgba(255, 255, 255, 50);
        border-radius: 3px;
        font-size: 12px;
    }}
    QPushButton[cssClass="sidebar"]:hover {{
        background-color: {KNX_GREEN};
        color: white;
        border: 1px solid rgba(255, 255, 255, 120);
    }}
    QPushButton[cssClass="sidebar"]:checked {{
        background-color: {KNX_GREEN};
        color: white;
        font-weight: bold;
        border: 1px solid white;
    }}

    /* Allgemeine Buttons */
    QPushButton {{
        background-color: {KNX_GREEN};
        color: white;
        border: none;
        border-radius: 4px;
        padding: 8px 16px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {KNX_DARK_GREEN};
    }}
    QPushButton:pressed {{
        background-color: {KNX_DARK_GREEN};
    }}
    QPushButton:disabled {{
        background-color: {KNX_MEDIUM_GRAY};
        color: #808080;
    }}
    QPushButton#secondary {{
        background-color: {KNX_BLUE};
    }}
    QPushButton#secondary:hover {{
        background-color: {KNX_LIGHT_BLUE};
    }}
    QPushButton#danger {{
        background-color: {KNX_RED};
    }}

    /* Tabellen */
    QTableWidget {{
        gridline-color: {KNX_MEDIUM_GRAY};
        selection-background-color: {KNX_GREEN};
        selection-color: white;
        font-size: 12px;
    }}
    QHeaderView::section {{
        background-color: {KNX_LIGHT_GRAY};
        padding: 6px;
        border: 1px solid {KNX_MEDIUM_GRAY};
        font-weight: bold;
    }}

    /* Baumansicht */
    QTreeWidget {{
        font-size: 12px;
        show-decoration-selected: 1;
    }}
    QTreeWidget::item:selected {{
        background-color: {KNX_GREEN};
        color: white;
    }}

    /* Eingabefelder */
    QLineEdit, QComboBox {{
        border: 1px solid {KNX_MEDIUM_GRAY};
        border-radius: 3px;
        padding: 5px;
        font-size: 13px;
    }}
    QSpinBox {{
        border: 1px solid {KNX_MEDIUM_GRAY};
        border-radius: 3px;
        padding: 2px;
        padding-right: 20px;
        font-size: 13px;
    }}
    QSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 18px;
        border-left: 1px solid {KNX_MEDIUM_GRAY};
        border-bottom: 1px solid {KNX_MEDIUM_GRAY};
        border-top-right-radius: 3px;
        background-color: {KNX_LIGHT_GRAY};
    }}
    QSpinBox::up-button:hover {{
        background-color: {KNX_GREEN};
    }}
    QSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 18px;
        border-left: 1px solid {KNX_MEDIUM_GRAY};
        border-bottom-right-radius: 3px;
        background-color: {KNX_LIGHT_GRAY};
    }}
    QSpinBox::down-button:hover {{
        background-color: {KNX_GREEN};
    }}
    QSpinBox::up-arrow {{
        image: none;
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 5px solid {KNX_DARK_GRAY};
    }}
    QSpinBox::down-arrow {{
        image: none;
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {KNX_DARK_GRAY};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 2px solid {KNX_GREEN};
    }}

    /* Labels */
    QLabel#title {{
        font-size: 18px;
        font-weight: bold;
        color: {KNX_DARK_GREEN};
    }}
    QLabel#subtitle {{
        font-size: 14px;
        color: {KNX_DARK_GRAY};
    }}

    /* Statusleiste */
    QStatusBar {{
        background-color: {KNX_LIGHT_GRAY};
        border-top: 1px solid {KNX_MEDIUM_GRAY};
    }}

    /* Tabs */
    QTabWidget::pane {{
        border: 1px solid {KNX_MEDIUM_GRAY};
    }}
    QTabBar::tab {{
        background-color: {KNX_LIGHT_GRAY};
        padding: 8px 16px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {KNX_GREEN};
        color: white;
    }}

    /* GroupBox */
    QGroupBox {{
        border: 1px solid {KNX_MEDIUM_GRAY};
        border-radius: 4px;
        margin-top: 10px;
        padding-top: 15px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
    }}

    /* ScrollBar */
    QScrollBar:vertical {{
        width: 10px;
        background: {KNX_LIGHT_GRAY};
    }}
    QScrollBar::handle:vertical {{
        background: {KNX_MEDIUM_GRAY};
        border-radius: 5px;
    }}

    /* ProgressBar */
    QProgressBar {{
        border: 1px solid {KNX_MEDIUM_GRAY};
        border-radius: 4px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {KNX_GREEN};
        border-radius: 3px;
    }}
    """
