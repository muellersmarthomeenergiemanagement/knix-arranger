"""
CO-Verknuepfungs-Ansicht (FA-3000 bis FA-3005)

Zeigt automatisch generierte CO-GA-Verknuepfungsvorschlaege in einer
Tabelle an. Der Benutzer kann Vorschlaege pruefen, abwaehlen und mit
einem Klick in die Topologie uebernehmen.
"""
from __future__ import annotations
import logging
from collections import Counter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QCheckBox, QMessageBox, QSizePolicy,
    QFrame, QLineEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont

logger = logging.getLogger("knix_arranger.co_linking_view")


def _segment_matches(filter_text: str, value: str, sep: str) -> bool:
    """Vergleicht filter_text gegen value anhand von durch `sep` getrennten
    Segmenten (physikalische Adresse "Bereich.Linie.Geraet" mit sep=".",
    GA-Adresse "HG/MG/UG" mit sep="/").

    Ein vollstaendiger Filter (gleich viele oder mehr Segmente als die
    Adresse) muss EXAKT passen -- sonst wuerde z.B. "1.1.1" faelschlich auch
    "1.1.10"/"1.1.12" treffen (reiner Praefixvergleich auf dem String statt
    auf Segmenten). Ein kuerzerer Filter grenzt weiterhin per Praefix auf
    ganze Segmente ein, z.B. "1.1" zeigt alle Geraete der Linie 1.1."""
    filter_text = filter_text.strip()
    if not filter_text:
        return True
    f_parts = filter_text.split(sep)
    while len(f_parts) > 1 and f_parts[-1] == "":
        f_parts.pop()
    v_parts = value.split(sep)
    if len(f_parts) >= len(v_parts):
        return f_parts == v_parts
    return v_parts[:len(f_parts)] == f_parts

# Farben
_COLOR_SICHER = QColor("#C8E6C9")       # Gruen: sichere Verknuepfung
_COLOR_MANUELL = QColor("#FFF9C4")      # Gelb: manuell pruefen
_COLOR_ALREADY = QColor("#E3F2FD")      # Blau: bereits verknuepft
_COLOR_HEADER = QColor("#1565C0")       # KNX-Blau fuer Header
_COLOR_DUP = QColor("#FFAB91")          # Orange-Rot: mehrfach verknuepfte GA (FA-3000)

# Spalten-Indizes
_COL_SEL = 0
_COL_ADDR = 1
_COL_ORT = 2      # Ort/Raum des Stromkreises – FA-3000
_COL_CO_NAME = 3
_COL_DPT = 4      # CO-DPT (erwartet)
_COL_GA_DPT = 5   # GA-DPT (tatsaechlich) – FA-3004
_COL_FLAGS = 6
_COL_DIR = 7      # Richtung: empfangen / senden
_COL_GEWERK = 8
_COL_GA_ADDR = 9
_COL_GA_NAME = 10
_COL_CONF = 11
_NUM_COLS = 12

_HEADERS = [
    "✓", "Geraeteadresse", "Ort", "CO-Funktion", "CO-DPT", "GA-DPT", "Flags",
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
        self._dup_keys: set[tuple] = set()
        self._setup_ui()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Laedt das Projekt und generiert Verknuepfungsvorschlaege."""
        self._project = project
        self._refresh()

    def showEvent(self, event):
        """Spaltenbreiten neu berechnen, wenn diese Ansicht sichtbar wird.

        set_project()/_refresh() laufen oft, während dieser Tab noch gar
        nicht sichtbar ist -- main_window.py hält alle Ansichten dauerhaft in
        einem QStackedWidget vor, statt sie neu zu erzeugen.
        resizeColumnsToContents() liefert auf einem verborgenen Widget teils
        falsche (zu schmale) Breiten. Beim ersten Einblenden hier korrekt
        nachziehen.
        """
        super().showEvent(event)
        self._table.resizeColumnsToContents()
        self._table.setColumnWidth(_COL_SEL, 36)

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
            "mit welchen GAs verknüpft werden sollen. Vorschläge prüfen und mit "
            "\"Verknüpfungen übernehmen\" in die Topologie schreiben."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(desc)

        # Trennlinie
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)

        # Filterzeile
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Geraeteadresse:"))
        self._filter_addr = QLineEdit()
        self._filter_addr.setPlaceholderText("z.B. 1.1.3")
        self._filter_addr.setClearButtonEnabled(True)
        self._filter_addr.setMaximumWidth(140)
        self._filter_addr.textChanged.connect(self._apply_filters)
        filter_layout.addWidget(self._filter_addr)

        filter_layout.addSpacing(8)
        filter_layout.addWidget(QLabel("Gruppenadresse:"))
        self._filter_ga = QLineEdit()
        self._filter_ga.setPlaceholderText("z.B. 2/0/4")
        self._filter_ga.setClearButtonEnabled(True)
        self._filter_ga.setMaximumWidth(140)
        self._filter_ga.textChanged.connect(self._apply_filters)
        filter_layout.addWidget(self._filter_ga)

        filter_layout.addSpacing(12)
        filter_layout.addWidget(QLabel("Anzeigen:"))
        self._cb_filter_sicher = QCheckBox("Sicher")
        self._cb_filter_sicher.setChecked(True)
        self._cb_filter_sicher.toggled.connect(self._apply_filters)
        filter_layout.addWidget(self._cb_filter_sicher)

        self._cb_filter_manuell = QCheckBox("Manuell pruefen")
        self._cb_filter_manuell.setChecked(True)
        self._cb_filter_manuell.toggled.connect(self._apply_filters)
        filter_layout.addWidget(self._cb_filter_manuell)

        self._cb_filter_already = QCheckBox("Bereits verknuepft")
        self._cb_filter_already.setChecked(True)
        self._cb_filter_already.toggled.connect(self._apply_filters)
        filter_layout.addWidget(self._cb_filter_already)

        filter_layout.addSpacing(12)
        self._cb_filter_dup = QCheckBox("Nur Mehrfachverknuepfungen (gleiche GA am selben Geraet)")
        self._cb_filter_dup.toggled.connect(self._apply_filters)
        filter_layout.addWidget(self._cb_filter_dup)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Statuszeile
        self._status_label = QLabel("Kein Projekt geladen.")
        self._status_label.setStyleSheet("font-size: 11px; color: #555;")
        layout.addWidget(self._status_label)

        # Tabelle -- inhaltsbasierte Breite für alle Spalten (kein Stretch
        # für "GA-Bezeichnung": zwang die Spalte sonst unabhängig vom Inhalt
        # auf die volle Restbreite, analog zum Verknüpfungsmatrix-/Topologie-
        # /Gruppenadressen-Fix). _fill_table() ruft resizeColumnsToContents()
        # nach jedem Befüllen erneut auf.
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels(_HEADERS)
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
            "<span style='background:#E3F2FD; padding:2px 6px;'>Bereits verknuepft</span>  "
            "<span style='background:#FFAB91; padding:2px 6px;'>Gleiche GA mehrfach am Geraet</span>"
        )
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet("font-size: 10px;")
        layout.addWidget(legend)

        # Button-Leiste
        btn_layout = QHBoxLayout()

        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.setToolTip("Vorschläge neu berechnen")
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
            QMessageBox.warning(self, "Fehler", f"Vorschläge konnten nicht generiert werden:\n{exc}")
            return

        self._fill_table()
        self._update_status()
        self._btn_apply.setEnabled(bool(self._proposals))

    def _fill_table(self):
        """Befuellt die QTableWidget mit den aktuellen Vorschlaegen."""
        self._table.setRowCount(0)
        self._checkboxes.clear()
        self._dup_keys.clear()
        if not self._proposals:
            self._table.setRowCount(1)
            item = QTableWidgetItem("Keine Vorschläge — Wizard-Schritte 6–8 zuerst abschliessen.")
            item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(0, _COL_ADDR, item)
            self._table.setSpan(0, 0, 1, _NUM_COLS)
            return

        self._table.setRowCount(len(self._proposals))
        # FA-3000: GA-Adressen zaehlen, die am selben Geraet mehrfach auftauchen
        # (z.B. gleiche GA fuer zwei verschiedene CO-Funktionen vorgeschlagen) --
        # echte 1:1-Duplikate (identische Geraet+GA+CO-Funktion) werden bereits
        # in CoLinkingService._dedupe_proposals() entfernt; was hier uebrig
        # bleibt, ist eine Mehrfachverknuepfung derselben GA am selben Geraet,
        # die der Planer pruefen sollte.
        ga_counts = Counter(
            (p.physical_address, p.ga_address)
            for p in self._proposals if p.ga_address
        )
        self._dup_keys = {key for key, n in ga_counts.items() if n > 1}

        for row_idx, proposal in enumerate(self._proposals):
            # Hintergrundfarbe bestimmen
            if proposal.already_linked:
                bg = _COLOR_ALREADY
            elif proposal.confidence == "sicher":
                bg = _COLOR_SICHER
            else:
                bg = _COLOR_MANUELL
            is_dup = (proposal.physical_address, proposal.ga_address) in self._dup_keys

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
            ga_addr_bg = _COLOR_DUP if is_dup else bg
            for col, text, cell_bg in [
                (_COL_ADDR,    proposal.physical_address,  bg),
                (_COL_ORT,     proposal.room_name or "Zentral", bg),
                (_COL_CO_NAME, proposal.co_name,           bg),
                (_COL_DPT,     proposal.co_dpt,            bg),
                (_COL_GA_DPT,  ga_dpt,                     ga_dpt_bg),
                (_COL_FLAGS,   proposal.co_flags,          bg),
                (_COL_DIR,     direction,                  dir_color if not proposal.already_linked else bg),
                (_COL_GEWERK,  proposal.gewerk_code,       bg),
                (_COL_GA_ADDR, proposal.ga_address,        ga_addr_bg),
                (_COL_GA_NAME, proposal.ga_designation,    bg),
                (_COL_CONF,    "Bereits verknuepft" if proposal.already_linked else proposal.confidence, bg),
            ]:
                item = QTableWidgetItem(text)
                item.setBackground(QBrush(cell_bg))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == _COL_GA_ADDR and is_dup:
                    item.setToolTip(
                        "Diese GA-Adresse wird am selben Geraet mehrfach vorgeschlagen "
                        "(mehrere CO-Funktionen) -- pruefen, ob das gewollt ist."
                    )
                self._table.setItem(row_idx, col, item)

        self._table.resizeColumnsToContents()
        self._table.setColumnWidth(_COL_SEL, 36)
        self._apply_filters()

    def _update_status(self):
        total = len(self._proposals)
        already = sum(1 for p in self._proposals if p.already_linked)
        new_ = total - already
        dup = len(self._dup_keys)
        text = f"{total} Vorschläge insgesamt  |  {new_} neu  |  {already} bereits verknüpft"
        if dup:
            text += f"  |  {dup} GA-Adresse(n) mehrfach am gleichen Geraet"
        self._status_label.setText(text)

    def _apply_filters(self):
        """FA-3000: Blendet Zeilen aus, die nicht zum Geraeteadress-/GA-/Farb-/
        Mehrfachverknuepfungs-Filter passen. Arbeitet rein auf Zeilensichtbarkeit
        (setRowHidden) -- Proposal-Liste und Checkbox-Zuordnung bleiben
        unveraendert, damit "Alle auswaehlen"/"Uebernehmen" weiterhin korrekt
        auf die zugrundeliegenden Vorschlaege abbilden.

        Adress-/GA-Filter vergleichen segmentweise (siehe _segment_matches),
        damit z.B. "1.1.1" nicht faelschlich auch "1.1.10"/"1.1.12" trifft."""
        if not self._proposals:
            return
        addr_filter = self._filter_addr.text()
        ga_filter = self._filter_ga.text()
        show_sicher = self._cb_filter_sicher.isChecked()
        show_manuell = self._cb_filter_manuell.isChecked()
        show_already = self._cb_filter_already.isChecked()
        dup_only = self._cb_filter_dup.isChecked()

        for row_idx, proposal in enumerate(self._proposals):
            visible = True
            if not _segment_matches(addr_filter, proposal.physical_address, "."):
                visible = False
            elif not _segment_matches(ga_filter, proposal.ga_address, "/"):
                visible = False
            elif proposal.already_linked:
                visible = show_already
            elif proposal.confidence == "sicher":
                visible = show_sicher
            else:
                visible = show_manuell
            if visible and dup_only:
                visible = (proposal.physical_address, proposal.ga_address) in self._dup_keys
            self._table.setRowHidden(row_idx, not visible)

    def _visible_indices(self) -> list[int]:
        return [
            i for i in range(len(self._proposals))
            if not self._table.isRowHidden(i)
        ]

    def _set_all(self, state: bool):
        visible = set(self._visible_indices())
        for idx, (cb, proposal) in enumerate(zip(self._checkboxes, self._proposals)):
            if idx not in visible:
                continue
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
