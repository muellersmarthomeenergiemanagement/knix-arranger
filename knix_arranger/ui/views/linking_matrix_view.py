"""
Sensor-Aktor-Verknuepfungsmatrix (FA-2500 bis FA-2505)

Sensor-Tab: echte Kreuztabelle (FA-2502) -- Zeile = Sensor-Bedienstelle
(Gerät + Taste), Spalte = ausgelöste Funktionskategorie (Gewerk), Zelle =
zugewiesener Wert. Aktor-Tab: tabellarische Liste der Aktor-GA-Zuordnungen.
Stockwerk- und Raum-Filter (FA-2501). Datenquelle: BelegungsplanService.

Zell-Bearbeitung (FA-2503): Doppelklick öffnet einen GA-Auswahldialog --
aber nur für "direkte GA"-Zuordnungen (SensorFunktion ohne gewerk_code) oder
leere Zellen. Gewerk-basiert automatisch abgeleitete Zuordnungen (Schritt 5
Gewerke) sind bewusst nicht pro Zelle editierbar, da eine SensorFunktion dort
mehrere GAs (Primär+Rückmeldung) gebündelt erzeugt. Änderungen werden in
Bedienelement.funktionen geschrieben (nicht in function_assignments, das bei
jedem Refresh aus funktionen neu berechnet wird) -- dieselbe Datenquelle, die
auch das Bauherr-Formular (FA-1500) liest/schreibt, wodurch beide Wege
automatisch konsistent bleiben (FA-2504).
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView, QFileDialog,
    QMessageBox, QFrame, QSizePolicy, QComboBox, QDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QBrush, QColor

from ...models.building import SensorFunktion
from ..dialogs.ga_picker_dialog import GaPickerDialog

logger = logging.getLogger("knix_arranger.linking_matrix_view")

# Farben
_COLOR_SENSOR_ODD  = QColor("#F3F8FF")
_COLOR_ACTOR_ODD   = QColor("#F3FFF6")


# --------------- Sensor-Tab: feste Zeilenkopf-Spalten (FA-2502) ---------------
# Die restlichen Spalten (Funktionskategorien / Gewerke, z.B. "Licht schalten",
# "Jalousie", "Szene") werden dynamisch aus den Daten aufgebaut -- siehe
# _fill_sensor_tab(). Zeile = Bedienstelle (Gerät + Taste), Spalte = Funktion,
# Zelle = ausgelöster Wert (FA-2502/2503).
_S_FIXED_HEADERS = [
    "Stockwerk", "Zone", "Raum-Nr.", "Raumname", "Sensor-Typ", "Phys. Adresse", "Taste",
]
_S_COL = {h: i for i, h in enumerate(_S_FIXED_HEADERS)}
_S_OTHER_KEY = "__other__"   # Sammelspalte für Zeilen ohne aufgelösten Gewerk-Code

# --------------- Aktor-Tab Spalten ---------------
_A_HEADERS = [
    "Stockwerk", "Linie", "UV / Einbauort", "Aktor-Typ", "Phys. Adresse", "Kanal",
    "Zone", "Raum-Nr.", "Raumname",
    "Gewerk", "Funktion", "GA-Bezeichnung", "GA-Adresse", "DPT",
]
_A_COL = {h: i for i, h in enumerate(_A_HEADERS)}


def _make_item(text: str, color: QColor | None = None, bold: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    if color:
        item.setBackground(QBrush(color))
    if bold:
        f = item.font()
        f.setBold(True)
        item.setFont(f)
    return item


class LinkingMatrixView(QWidget):
    """Verknuepfungsmatrix: Sensoren und Aktoren mit GA-Zuordnung (FA-2500)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._belegungsplan = None
        self._bus = None
        # Von _fill_sensor_tab befuellt, fuer Doppelklick-Zellauflösung (FA-2503):
        self._sensor_row_order: list[tuple[str, str]] = []
        self._sensor_groups: dict = {}
        self._sensor_col_keys: list[str] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Laedt Projekt und baut die Matrix auf."""
        self._project = project
        self._refresh()

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus (FA-2504)."""
        self._bus = bus

    # ------------------------------------------------------------------
    # UI-Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Titel
        title = QLabel("Verknuepfungsmatrix (FA-2500)")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel(
            "Sensoren/Taster als Kreuztabelle (Zeile = Bedienstelle, Spalte = "
            "ausgelöste Funktion) sowie Aktor-GA-Zuordnungen als Liste. "
            "Doppelklick auf eine direkte GA-Zuordnung oder leere Zelle weist "
            "eine Gruppenadresse zu. Grundlage für die ETS-Programmierung und "
            "die Revisionsunterlagen."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)

        # Statuszeile
        self._status_label = QLabel("Kein Projekt geladen.")
        self._status_label.setStyleSheet("font-size: 11px; color: #555;")
        layout.addWidget(self._status_label)

        # FA-2501: Stockwerk- und Raumfilter (Matrix pro Raum, Stockwerk oder Projekt)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Stockwerk-Filter:"))
        self._floor_filter = QComboBox()
        self._floor_filter.setMinimumWidth(140)
        self._floor_filter.addItem("Alle Stockwerke")
        self._floor_filter.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self._floor_filter)

        filter_layout.addWidget(QLabel("Raum-Filter:"))
        self._room_filter = QComboBox()
        self._room_filter.setMinimumWidth(160)
        self._room_filter.addItem("Alle Räume")
        self._room_filter.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self._room_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Tabs
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        # Sensor-Tab (Kreuztabelle: Zeile=Bedienstelle, Spalte=Funktion, FA-2502)
        self._sensor_table = self._create_table(_S_FIXED_HEADERS)
        self._sensor_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._sensor_table.cellDoubleClicked.connect(self._on_sensor_cell_double_clicked)
        self._tabs.addTab(self._sensor_table, "Sensoren / Taster")

        # Aktor-Tab
        self._actor_table = self._create_table(_A_HEADERS)
        self._tabs.addTab(self._actor_table, "Aktoren")

        # Button-Leiste
        btn_layout = QHBoxLayout()

        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(self._refresh)
        btn_layout.addWidget(self._btn_refresh)

        btn_layout.addStretch()

        self._btn_export_pdf = QPushButton("Als PDF exportieren")
        self._btn_export_pdf.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; "
            "font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._btn_export_pdf.clicked.connect(self._export_pdf)
        self._btn_export_pdf.setEnabled(False)
        btn_layout.addWidget(self._btn_export_pdf)

        self._btn_export = QPushButton("Als XLSX exportieren")
        self._btn_export.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; "
            "font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #388E3C; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._btn_export.clicked.connect(self._export_xlsx)
        self._btn_export.setEnabled(False)
        btn_layout.addWidget(self._btn_export)

        layout.addLayout(btn_layout)

    def _create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        # GA-Bezeichnung-Spalte bekommt Stretch
        for i, h in enumerate(headers):
            if "Bezeichnung" in h or "Raumname" in h or "Funktion" in h:
                table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        return table

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _refresh(self):
        if not self._project:
            return
        from ...services.belegungsplan_service import BelegungsplanService
        try:
            self._belegungsplan = BelegungsplanService().generate(self._project)
        except Exception as exc:
            logger.exception("Fehler bei Belegungsplan-Generierung")
            QMessageBox.warning(self, "Fehler",
                f"Verknuepfungsmatrix konnte nicht berechnet werden:\n{exc}")
            return

        self._fill_sensor_tab()
        self._fill_actor_tab()
        self._update_status()
        self._populate_room_filter()
        self._apply_filter()
        self._btn_export.setEnabled(True)
        self._btn_export_pdf.setEnabled(True)

    def _fill_sensor_tab(self):
        """Baut die Sensor/Taster-Kreuztabelle: Zeile = Bedienstelle (Gerät +
        Taste), Spalte = ausgelöste Funktionskategorie (Gewerk), Zelle = Wert
        (FA-2502). Rückmelde-GAs (LED-Status, is_feedback) lösen nichts aus
        und werden hier nicht angezeigt.
        """
        all_rows = self._belegungsplan.sensor_rows if self._belegungsplan else []
        rows = [r for r in all_rows if not r.is_feedback]
        catalog = self._project.gewerk_catalog if self._project else None

        # Funktionsspalten sammeln (Reihenfolge = erstes Auftreten, "Sonstige" ans Ende)
        col_keys: list[str] = []
        col_labels: dict[str, str] = {}
        for r in rows:
            key = r.gewerk_code or _S_OTHER_KEY
            if key not in col_labels:
                col_keys.append(key)
                if r.gewerk_code and catalog:
                    gw = catalog.get(r.gewerk_code)
                    col_labels[key] = gw.name if gw else r.gewerk_code
                elif r.gewerk_code:
                    col_labels[key] = r.gewerk_code
                else:
                    col_labels[key] = "Sonstige"
        col_keys.sort(key=lambda k: (k == _S_OTHER_KEY, col_labels[k]))
        self._sensor_col_keys = col_keys

        headers = list(_S_FIXED_HEADERS) + [col_labels[k] for k in col_keys]
        hdr = self._sensor_table.horizontalHeader()
        self._sensor_table.setColumnCount(len(headers))
        self._sensor_table.setHorizontalHeaderLabels(headers)
        # Disable auto-resize during fill: ResizeToContents mode triggers a
        # column-width recalculation on every setItem() call which is O(n*cols).
        for i in range(len(headers)):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)

        # Zeilen gruppieren: (phys. Adresse, Taste) -> Metadaten + Zellen je Spalte.
        # `rows` ist bereits vom Service nach Adresse/Taste sortiert, daher
        # bestimmt die Einfügereihenfolge direkt die Zeilenreihenfolge.
        groups: dict[tuple[str, str], dict] = {}
        order: list[tuple[str, str]] = []
        for r in rows:
            rk = (r.physical_address, r.taste_label)
            if rk not in groups:
                groups[rk] = {"meta": r, "cells": {}}
                order.append(rk)
            cell_key = r.gewerk_code or _S_OTHER_KEY
            groups[rk]["cells"].setdefault(cell_key, []).append(r)
        self._sensor_row_order = order
        self._sensor_groups = groups

        self._sensor_table.setRowCount(len(order))
        n_fixed = len(_S_FIXED_HEADERS)
        for r_idx, rk in enumerate(order):
            meta = groups[rk]["meta"]
            cells = groups[rk]["cells"]
            color = _COLOR_SENSOR_ODD if r_idx % 2 == 0 else None
            fixed_data = [
                meta.floor_name, meta.zone_name, meta.room_number, meta.room_name,
                meta.sensor_type, meta.physical_address, meta.taste_label,
            ]
            for c_idx, text in enumerate(fixed_data):
                self._sensor_table.setItem(r_idx, c_idx, _make_item(text, color))

            for col_offset, key in enumerate(col_keys):
                entries = cells.get(key)
                editable = self._editable_sf_for_cell(meta, entries) is not None
                if entries:
                    texts, tooltips = [], []
                    for e in entries:
                        label = (f"{e.action_type.capitalize()}: {e.function}"
                                 if e.action_type else (e.function or "—"))
                        texts.append(label)
                        detail = e.ga_designation or e.ga_address or ""
                        if e.ga_address and e.ga_address != detail:
                            detail += f"  ({e.ga_address})"
                        if e.dpt:
                            detail += f"  [{e.dpt}]"
                        tooltips.append(detail)
                    item = _make_item("\n".join(texts), color)
                    tip = "\n".join(tooltips)
                    tip += ("\n\nDoppelklick: andere GA zuweisen" if editable
                            else "\n\n🔒 Aus Schritt 5 (Gewerke) oder Import -- "
                                 "hier nicht direkt bearbeitbar.")
                    item.setToolTip(tip)
                else:
                    item = _make_item("", color)
                    if editable:
                        item.setToolTip("Doppelklick: Gruppenadresse zuweisen")
                self._sensor_table.setItem(r_idx, n_fixed + col_offset, item)

        # Single resize pass after all data is in place
        self._sensor_table.resizeColumnsToContents()
        _MAX_COL_WIDTH = 220
        for _cap_col in ("Sensor-Typ", "Stockwerk", "Zone", "Raumname"):
            _idx = _S_COL.get(_cap_col)
            if _idx is not None and self._sensor_table.columnWidth(_idx) > _MAX_COL_WIDTH:
                self._sensor_table.setColumnWidth(_idx, _MAX_COL_WIDTH)
        for i in range(n_fixed, len(headers)):
            hdr.setSectionResizeMode(i, QHeaderView.Stretch)

    # ── FA-2503: Zell-Bearbeitung ──────────────────────────────────────────────

    def _resolve_be(self, be_id: str):
        """Sucht Raum + Bedienelement anhand der Id. None wenn nicht gefunden."""
        if not self._project or not be_id:
            return None
        for room in self._project.all_rooms:
            for be in room.bedienelemente:
                if be.id == be_id:
                    return room, be
        return None

    def _editable_sf_for_cell(self, meta, entries):
        """Prüft, ob eine Matrix-Zelle per Doppelklick bearbeitbar ist (FA-2503).

        Editierbar: leere Zelle (neue direkte GA-Zuordnung anlegen) oder genau
        ein Eintrag, der auf eine SensorFunktion OHNE gewerk_code zurückgeht
        (Variante 2: direkte GA). Gewerk-basiert automatisch abgeleitete
        Zuordnungen (Variante 1, Schritt 5 Gewerke) sowie ETS6-Import-Zeilen
        ohne SensorFunktion-Bezug sind absichtlich nicht editierbar.

        Gibt (room, be, sf_or_None) zurück, oder None wenn nicht editierbar.
        """
        resolved = self._resolve_be(meta.be_id)
        if not resolved:
            return None
        room, be = resolved
        if not entries:
            return room, be, None
        if len(entries) > 1 or not entries[0].sf_id:
            return None
        sf = next((s for s in be.funktionen if s.id == entries[0].sf_id), None)
        if sf is None or sf.gewerk_code:
            return None
        return room, be, sf

    def _on_sensor_cell_double_clicked(self, row: int, col: int):
        n_fixed = len(_S_FIXED_HEADERS)
        if col < n_fixed:
            return  # feste Metadaten-Spalten nicht editierbar
        col_offset = col - n_fixed
        if row >= len(self._sensor_row_order) or col_offset >= len(self._sensor_col_keys):
            return

        rk = self._sensor_row_order[row]
        group = self._sensor_groups.get(rk)
        if not group:
            return
        meta = group["meta"]
        key = self._sensor_col_keys[col_offset]
        entries = group["cells"].get(key)

        resolved = self._editable_sf_for_cell(meta, entries)
        if resolved is None:
            QMessageBox.information(
                self, "Nicht bearbeitbar",
                "Diese Zuordnung stammt aus der Gewerk-Zuweisung (Schritt 5) "
                "oder einem ETS6-Import und lässt sich hier nicht direkt "
                "bearbeiten."
                if entries else
                "Für diese Bedienstelle ist kein Bedienelement bekannt -- "
                "Zuweisung hier nicht möglich."
            )
            return
        room, be, sf = resolved

        gewerk_hint = "" if key == _S_OTHER_KEY else key
        current_desig = sf.ga_designation if sf else ""
        dlg = GaPickerDialog(
            self._project, room, gewerk_hint=gewerk_hint,
            current_ga_designation=current_desig, parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        if not dlg.clear_requested and not dlg.selected_ga:
            return

        if self._bus:
            self._bus.begin_change("Verknüpfungsmatrix bearbeitet")

        if dlg.clear_requested:
            if sf:
                be.funktionen.remove(sf)
            else:
                return  # leere Zelle, nichts zu entfernen
        else:
            if sf:
                sf.ga_designation = dlg.selected_ga.designation
                sf.label = ""  # Label wird wieder aus der (neuen) GA abgeleitet
            else:
                be.funktionen.append(SensorFunktion(ga_designation=dlg.selected_ga.designation))

        # Hinweis: bewusst KEIN self._bus.emit_functions_changed() -- das löst
        # in main_window._on_functions_changed() eine vollständige Neuberechnung
        # von Aktoren/Topologie-Belegung/Gruppenadressen aus (gedacht für echte
        # Gewerk-Änderungen aus Schritt 5), was für eine einzelne GA-Umzuordnung
        # hier unpassend und überraschend wäre. Andere Ansichten (z.B. das
        # Bauherr-Formular) lesen ohnehin live aus demselben Bedienelement.funktionen
        # und sehen die Änderung beim nächsten eigenen Refresh (FA-2504).
        be.is_auto = False
        self._refresh()

    def _fill_actor_tab(self):
        rows = self._belegungsplan.actor_rows if self._belegungsplan else []
        hdr = self._actor_table.horizontalHeader()
        for i in range(len(_A_HEADERS)):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
        self._actor_table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            color = _COLOR_ACTOR_ODD if r_idx % 2 == 0 else None
            data = [
                row.floor_name, row.line_name, row.uv_location, row.actor_type,
                row.physical_address, row.channel_number,
                row.zone_name, row.room_number, row.room_name,
                row.gewerk_code, row.function_name, row.ga_designation,
                row.ga_address, row.dpt,
            ]
            for c_idx, text in enumerate(data):
                self._actor_table.setItem(r_idx, c_idx, _make_item(text, color))
        self._actor_table.resizeColumnsToContents()
        # Breite bestimmter Spalten nach oben begrenzen (verhindert dass
        # lange Einbauort-/Liniennamen die übrigen Spalten verdrängen)
        _MAX_COL_WIDTH = 220
        for _cap_col in ("UV / Einbauort", "Linie", "Aktor-Typ"):
            _idx = _A_COL.get(_cap_col)
            if _idx is not None and self._actor_table.columnWidth(_idx) > _MAX_COL_WIDTH:
                self._actor_table.setColumnWidth(_idx, _MAX_COL_WIDTH)
        for i, h in enumerate(_A_HEADERS):
            if "Bezeichnung" in h or "Raumname" in h or "Funktion" in h:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)

    def _update_status(self):
        if not self._belegungsplan:
            self._status_label.setText("Kein Belegungsplan verfuegbar.")
            return
        n_sensor = len(self._belegungsplan.sensor_rows)
        n_actor  = len(self._belegungsplan.actor_rows)
        self._status_label.setText(
            f"{n_sensor} Sensor/Taster-Zeilen  |  {n_actor} Aktor-Zeilen"
        )

    def _populate_room_filter(self):
        """FA-2501: Befuellt Stockwerk- und Raum-Filter mit den aktuellen Daten."""
        self._room_filter.blockSignals(True)
        self._room_filter.clear()
        self._room_filter.addItem("Alle Räume")
        self._floor_filter.blockSignals(True)
        self._floor_filter.clear()
        self._floor_filter.addItem("Alle Stockwerke")
        if self._belegungsplan:
            seen_rooms, seen_floors = set(), set()
            for row in (*self._belegungsplan.sensor_rows, *self._belegungsplan.actor_rows):
                key = f"{row.room_number}  {row.room_name}"
                if key not in seen_rooms:
                    seen_rooms.add(key)
                    self._room_filter.addItem(key, userData=row.room_number)
                if row.floor_name and row.floor_name not in seen_floors:
                    seen_floors.add(row.floor_name)
                    self._floor_filter.addItem(row.floor_name, userData=row.floor_name)
        self._room_filter.blockSignals(False)
        self._floor_filter.blockSignals(False)

    def _apply_filter(self):
        """FA-2501: Blendet Zeilen ein/aus basierend auf Stockwerk- und Raum-Filter.

        Die Matrix ist damit wahlweise pro Raum, pro Stockwerk oder für das
        gesamte Projekt anzeigbar (beide Filter kombinierbar, UND-verknüpft).
        """
        room_num = self._room_filter.currentData()    # None wenn "Alle Räume"
        floor_name = self._floor_filter.currentData()  # None wenn "Alle Stockwerke"
        for table, room_col, floor_col in (
            (self._sensor_table, _S_COL["Raum-Nr."], _S_COL["Stockwerk"]),
            (self._actor_table,  _A_COL["Raum-Nr."], _A_COL["Stockwerk"]),
        ):
            for row in range(table.rowCount()):
                visible = True
                if room_num is not None:
                    item = table.item(row, room_col)
                    visible = visible and item is not None and item.text() == room_num
                if floor_name is not None:
                    item = table.item(row, floor_col)
                    visible = visible and item is not None and item.text() == floor_name
                table.setRowHidden(row, not visible)

    def _export_pdf(self):
        """FA-2505: Exportiert Belegungsplan als PDF."""
        if not self._belegungsplan:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Belegungsplan als PDF exportieren",
            f"{self._project.name or 'Belegungsplan'}_Belegungsplan.pdf",
            "PDF-Dateien (*.pdf)",
        )
        if not path:
            return
        try:
            from ...services.belegungsplan_export_service import BelegungsplanExportService
            cp = getattr(self._project, "company_profile", None)
            pi = getattr(self._project, "project_info", None)
            BelegungsplanExportService().export_pdf(self._belegungsplan, path, cp, pi)
            QMessageBox.information(self, "Export erfolgreich",
                f"Belegungsplan exportiert:\n{path}")
        except Exception as exc:
            logger.exception("PDF-Export Fehler")
            QMessageBox.critical(self, "Export-Fehler", str(exc))

    def _export_xlsx(self):
        if not self._belegungsplan:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Verknuepfungsmatrix exportieren",
            f"{self._project.name or 'Verknuepfungsmatrix'}_Matrix.xlsx",
            "Excel-Dateien (*.xlsx)",
        )
        if not path:
            return
        try:
            from ...services.belegungsplan_export_service import BelegungsplanExportService
            BelegungsplanExportService().export_xlsx(self._belegungsplan, path)
            QMessageBox.information(self, "Export erfolgreich",
                f"Verknuepfungsmatrix exportiert:\n{path}")
        except Exception as exc:
            logger.exception("XLSX-Export Fehler")
            QMessageBox.critical(self, "Export-Fehler", str(exc))
