"""
CO-Verknuepfungs-Ansicht (FA-3000 bis FA-3005)

Zeigt automatisch generierte CO-GA-Verknuepfungsvorschlaege in einer
Tabelle an. Der Benutzer kann Vorschlaege pruefen, abwaehlen und mit
einem Klick in die Topologie uebernehmen.
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QCheckBox, QMessageBox, QSizePolicy,
    QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont

logger = logging.getLogger("knix_arranger.co_linking_view")

# Farben
_COLOR_SICHER = QColor("#C8E6C9")       # Gruen: sichere Verknuepfung
_COLOR_MANUELL = QColor("#FFF9C4")      # Gelb: manuell pruefen
_COLOR_ALREADY = QColor("#E3F2FD")      # Blau: bereits verknuepft
_COLOR_HEADER = QColor("#1565C0")       # KNX-Blau fuer Header

# Spalten-Indizes
_COL_SEL = 0
_COL_ADDR = 1
_COL_CO_NAME = 2
_COL_DPT = 3      # CO-DPT (erwartet)
_COL_GA_DPT = 4   # GA-DPT (tatsaechlich) – FA-3004
_COL_FLAGS = 5
_COL_DIR = 6      # Richtung: empfangen / senden
_COL_GEWERK = 7
_COL_GA_ADDR = 8
_COL_GA_NAME = 9
_COL_CONF = 10
_NUM_COLS = 11

_HEADERS = [
    "✓", "Geraeteadresse", "CO-Funktion", "CO-DPT", "GA-DPT", "Flags",
    "Richtung", "Gewerk", "GA-Adresse", "GA-Bezeichnung", "Konfidenz",
]

# Farbe fuer Richtung-Spalte
_COLOR_EMPFANGEN = QColor("#E8F5E9")   # Hellgruen: Aktor empfaengt Befehl
_COLOR_SENDEN    = QColor("#FFF3E0")   # Hellorange: Aktor sendet Rueckmeldung


class CoLinkingView(QWidget):
    """Ansicht fuer CO-Auto-Linking (FA-3000)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._proposals: list = []
        self._checkboxes: list[QCheckBox] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Laedt das Projekt und generiert Verknuepfungsvorschlaege."""
        self._project = project
        self._refresh()

    # ------------------------------------------------------------------
    # UI-Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Titel
        title = QLabel("CO-Verknuepfung (FA-3000)")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel(
            "Das System erkennt anhand der generierten Gruppenadressen (Funktion, "
            "Gewerk, Raum) automatisch, welche Kommunikationsobjekte der Aktoren "
            "mit welchen GAs verknuepft werden sollen. Vorschlaege pruefen und mit "
            "\"Verknuepfungen uebernehmen\" in die Topologie schreiben."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(desc)

        # Trennlinie
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)

        # Statuszeile
        self._status_label = QLabel("Kein Projekt geladen.")
        self._status_label.setStyleSheet("font-size: 11px; color: #555;")
        layout.addWidget(self._status_label)

        # Tabelle
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_GA_NAME, QHeaderView.Stretch
        )
        for col in (_COL_CO_NAME, _COL_DPT, _COL_GA_DPT):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents
            )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_SEL, QHeaderView.Fixed
        )
        self._table.setColumnWidth(_COL_SEL, 32)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)

        # Legende
        legend = QLabel(
            "Legende:  "
            "<span style='background:#C8E6C9; padding:2px 6px;'>Sicher</span>  "
            "<span style='background:#FFF9C4; padding:2px 6px;'>Manuell pruefen</span>  "
            "<span style='background:#E3F2FD; padding:2px 6px;'>Bereits verknuepft</span>"
        )
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet("font-size: 10px;")
        layout.addWidget(legend)

        # Button-Leiste
        btn_layout = QHBoxLayout()

        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.setToolTip("Vorschlaege neu berechnen")
        self._btn_refresh.clicked.connect(self._refresh)
        btn_layout.addWidget(self._btn_refresh)

        self._btn_all = QPushButton("Alle auswaehlen")
        self._btn_all.clicked.connect(lambda: self._set_all(True))
        btn_layout.addWidget(self._btn_all)

        self._btn_none = QPushButton("Alle abwaehlen")
        self._btn_none.clicked.connect(lambda: self._set_all(False))
        btn_layout.addWidget(self._btn_none)

        btn_layout.addStretch()

        self._btn_apply = QPushButton("Verknuepfungen uebernehmen")
        self._btn_apply.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; "
            "font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._btn_apply.clicked.connect(self._apply)
        self._btn_apply.setEnabled(False)
        btn_layout.addWidget(self._btn_apply)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _refresh(self):
        """Generiert Vorschlaege neu und befuellt die Tabelle."""
        if not self._project:
            return
        from ...services.co_linking_service import CoLinkingService
        try:
            self._proposals = CoLinkingService().generate_proposals(self._project)
        except Exception as exc:
            logger.exception("Fehler bei CO-Linking-Generierung")
            QMessageBox.warning(self, "Fehler", f"Vorschlaege konnten nicht generiert werden:\n{exc}")
            return

        self._fill_table()
        self._update_status()
        self._btn_apply.setEnabled(bool(self._proposals))

    def _fill_table(self):
        """Befuellt die QTableWidget mit den aktuellen Vorschlaegen."""
        self._table.setRowCount(0)
        self._checkboxes.clear()
        if not self._proposals:
            self._table.setRowCount(1)
            item = QTableWidgetItem("Keine Vorschlaege — Wizard-Schritte 6–8 zuerst abschliessen.")
            item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(0, _COL_ADDR, item)
            self._table.setSpan(0, 0, 1, _NUM_COLS)
            return

        self._table.setRowCount(len(self._proposals))
        for row_idx, proposal in enumerate(self._proposals):
            # Hintergrundfarbe bestimmen
            if proposal.already_linked:
                bg = _COLOR_ALREADY
            elif proposal.confidence == "sicher":
                bg = _COLOR_SICHER
            else:
                bg = _COLOR_MANUELL

            # Checkbox
            cb = QCheckBox()
            cb.setChecked(proposal.selected and not proposal.already_linked)
            cb.setEnabled(not proposal.already_linked)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(row_idx, _COL_SEL, cb_widget)
            self._checkboxes.append(cb)

            # Spalten fuellen
            direction = getattr(proposal, "direction", "")
            ga_dpt = getattr(proposal, "ga_dpt", "")
            dir_color = _COLOR_EMPFANGEN if direction == "empfangen" else _COLOR_SENDEN
            # FA-3004: GA-DPT-Zelle rot hinterlegen wenn DPT abweicht
            dpt_mismatch = (
                ga_dpt and proposal.co_dpt and ga_dpt != proposal.co_dpt
                and not proposal.already_linked
            )
            ga_dpt_bg = QColor("#FFCDD2") if dpt_mismatch else bg
            for col, text, cell_bg in [
                (_COL_ADDR,    proposal.physical_address,  bg),
                (_COL_CO_NAME, proposal.co_name,           bg),
                (_COL_DPT,     proposal.co_dpt,            bg),
                (_COL_GA_DPT,  ga_dpt,                     ga_dpt_bg),
                (_COL_FLAGS,   proposal.co_flags,          bg),
                (_COL_DIR,     direction,                  dir_color if not proposal.already_linked else bg),
                (_COL_GEWERK,  proposal.gewerk_code,       bg),
                (_COL_GA_ADDR, proposal.ga_address,        bg),
                (_COL_GA_NAME, proposal.ga_designation,    bg),
                (_COL_CONF,    "Bereits verknuepft" if proposal.already_linked else proposal.confidence, bg),
            ]:
                item = QTableWidgetItem(text)
                item.setBackground(QBrush(cell_bg))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(row_idx, col, item)

        self._table.resizeColumnsToContents()
        self._table.setColumnWidth(_COL_SEL, 36)
        # GA-Bezeichnung darf breiter sein (Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_GA_NAME, QHeaderView.Stretch
        )

    def _update_status(self):
        total = len(self._proposals)
        already = sum(1 for p in self._proposals if p.already_linked)
        new_ = total - already
        self._status_label.setText(
            f"{total} Vorschlaege insgesamt  |  "
            f"{new_} neu  |  {already} bereits verknuepft"
        )

    def _set_all(self, state: bool):
        for cb, proposal in zip(self._checkboxes, self._proposals):
            if not proposal.already_linked:
                cb.setChecked(state)

    def _apply(self):
        """Uebernimmt ausgewaehlte Vorschlaege in die Topologie."""
        if not self._project or not self._proposals:
            return

        # Auswahl aus Checkboxen lesen
        for cb, proposal in zip(self._checkboxes, self._proposals):
            proposal.selected = cb.isChecked()

        from ...services.co_linking_service import CoLinkingService
        try:
            count = CoLinkingService().apply_proposals(self._project, self._proposals)
        except Exception as exc:
            logger.exception("Fehler beim Uebernehmen der CO-Verknuepfungen")
            QMessageBox.critical(self, "Fehler", f"Verknuepfungen konnten nicht geschrieben werden:\n{exc}")
            return

        self._project.touch()
        QMessageBox.information(
            self, "CO-Verknuepfung abgeschlossen",
            f"{count} neue CO-GA-Verknuepfung(en) in die Topologie eingetragen.\n\n"
            "Die Verknuepfungen sind beim naechsten KNXPROJ-Export enthalten."
        )
        # Ansicht aktualisieren (bereits verknuepfte Eintraege blau markieren)
        self._refresh()
