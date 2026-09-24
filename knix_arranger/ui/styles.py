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

# Kontrastfarben für Schrift (WCAG AA: mind. 4,5:1 für normale Schrift).
# Das KNX-Grün (#5EA126) erreicht mit weisser Schrift nur 3,2:1 und ist
# deshalb nur noch für Akzente ohne Text gedacht (Fortschrittsbalken,
# Rahmen, Symbole). Flächen mit Schrift und grüne Schrift nutzen KNX_PRIMARY.
KNX_PRIMARY = "#427A1B"          # 5,2:1 mit Weiss
KNX_PRIMARY_PRESSED = "#2F5714"  # 8,4:1 mit Weiss
KNX_DANGER = "#C0392B"           # 5,4:1 mit Weiss (KNX_RED nur 3,8:1)
TEXT_MUTED = "#666666"           # Hinweistexte, 5,7:1 auf Weiss

# Schriftgrössen (px) -- nur diese Stufen verwenden
FONT_SMALL = 12    # Hinweise, Legenden, Tabellen
FONT_BODY = 13     # Standardtext, Buttons, Eingabefelder
FONT_HEADING = 16  # Zwischentitel
FONT_TITLE = 20    # Ansichtstitel

# Statusfarben -- werden auch als Schriftfarbe verwendet (Validierung),
# daher alle mit mind. 4,5:1 auf Weiss
COLOR_ERROR = KNX_DANGER
COLOR_WARNING = "#B35900"   # 4,8:1 (KNX_ORANGE nur 2,9:1)
COLOR_OK = KNX_PRIMARY
COLOR_INFO = "#1F6391"      # 6,5:1 (KNX_LIGHT_BLUE 4,3:1)

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
    QMenuBar::item {{
        color: {KNX_DARK_GRAY};
        padding: 4px 10px;
    }}
    QMenuBar::item:selected {{
        background-color: {KNX_PRIMARY};
        color: white;
    }}
    QMenu {{
        background-color: {KNX_WHITE};
        border: 1px solid {KNX_MEDIUM_GRAY};
    }}
    QMenu::item:selected {{
        background-color: {KNX_PRIMARY};
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
        background-color: {KNX_PRIMARY};
        color: white;
        text-align: left;
        padding: 5px 10px;
        border: 1px solid rgba(255, 255, 255, 50);
        border-radius: 3px;
        font-size: {FONT_BODY}px;
    }}
    QPushButton[cssClass="sidebar"]:hover {{
        background-color: {KNX_PRIMARY_PRESSED};
        color: white;
        border: 1px solid rgba(255, 255, 255, 120);
    }}
    /* Aktive Ansicht: weiss hinterlegt statt hellgrün -- deutlich
       erkennbar und mit 6,4:1 gut lesbar */
    QPushButton[cssClass="sidebar"]:checked {{
        background-color: {KNX_WHITE};
        color: {KNX_DARK_GREEN};
        font-weight: bold;
        border: 1px solid white;
    }}

    /* Buttons in drei Stufen:
       - Hauptaktion (Standard): grün gefüllt
       - Zweitaktion (objectName "secondary"): weiss mit blauem Rahmen
       - Link (objectName "link"): nur Text, für Nebenfunktionen
       dazu "danger" für löschende Aktionen. */
    QPushButton {{
        background-color: {KNX_PRIMARY};
        color: white;
        border: none;
        border-radius: 4px;
        padding: 8px 16px;
        font-size: {FONT_BODY}px;
    }}
    QPushButton:hover {{
        background-color: {KNX_DARK_GREEN};
    }}
    QPushButton:pressed {{
        background-color: {KNX_PRIMARY_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: {KNX_MEDIUM_GRAY};
        color: #505050;
    }}
    QPushButton#secondary {{
        background-color: {KNX_WHITE};
        color: {KNX_BLUE};
        border: 1px solid {KNX_BLUE};
        padding: 7px 15px;
    }}
    QPushButton#secondary:hover {{
        background-color: #E8F0F7;
    }}
    QPushButton#secondary:pressed {{
        background-color: #D4E3EF;
    }}
    /* Buttons mit Menü ("Weitere", "Katalog"): Pfeil mittig rechts */
    QPushButton::menu-indicator {{
        subcontrol-origin: padding;
        subcontrol-position: right center;
        right: 4px;
    }}
    QPushButton#link {{
        background-color: transparent;
        color: {KNX_BLUE};
        padding: 2px 4px;
        text-decoration: underline;
    }}
    QPushButton#link:hover {{
        background-color: transparent;
        color: {KNX_DARK_GRAY};
    }}
    QPushButton#danger {{
        background-color: {KNX_DANGER};
    }}
    QPushButton#danger:hover {{
        background-color: #A93226;
    }}
    /* Die ID-Selektoren oben sind spezifischer als QPushButton:disabled --
       ohne diese Regel bliebe z.B. ein deaktivierter "Löschen"-Button rot
       mit kaum lesbarer Schrift. */
    QPushButton#secondary:disabled, QPushButton#danger:disabled {{
        background-color: {KNX_MEDIUM_GRAY};
        color: #505050;
        border: none;
    }}
    QPushButton#link:disabled {{
        background-color: transparent;
        color: #808080;
    }}

    /* Tabellen */
    QTableWidget {{
        gridline-color: {KNX_MEDIUM_GRAY};
        selection-background-color: {KNX_PRIMARY};
        selection-color: white;
        font-size: {FONT_SMALL}px;
    }}
    QHeaderView::section {{
        background-color: {KNX_LIGHT_GRAY};
        padding: 6px;
        border: 1px solid {KNX_MEDIUM_GRAY};
        font-weight: bold;
    }}

    /* Baumansicht */
    QTreeWidget {{
        font-size: {FONT_SMALL}px;
        show-decoration-selected: 1;
    }}
    QTreeWidget::item:selected {{
        background-color: {KNX_PRIMARY};
        color: white;
    }}

    /* Eingabefelder */
    QLineEdit, QComboBox {{
        border: 1px solid {KNX_MEDIUM_GRAY};
        border-radius: 3px;
        padding: 5px;
        font-size: {FONT_BODY}px;
    }}
    QSpinBox {{
        border: 1px solid {KNX_MEDIUM_GRAY};
        border-radius: 3px;
        padding: 2px;
        padding-right: 20px;
        font-size: {FONT_BODY}px;
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

    /* Labels: Ansichtstitel, Zwischentitel, Einleitungstext, Hinweis */
    QLabel#title {{
        font-size: {FONT_TITLE}px;
        font-weight: bold;
        color: {KNX_DARK_GREEN};
    }}
    QLabel#heading {{
        font-size: {FONT_HEADING}px;
        font-weight: bold;
        color: {KNX_DARK_GRAY};
    }}
    QLabel#subtitle {{
        font-size: {FONT_BODY}px;
        color: {KNX_DARK_GRAY};
    }}
    QLabel#hint {{
        font-size: {FONT_SMALL}px;
        color: {TEXT_MUTED};
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
        background-color: {KNX_PRIMARY};
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
