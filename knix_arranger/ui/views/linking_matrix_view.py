"""
Sensor-Aktor-Verknuepfungsmatrix (FA-2500 bis FA-2505)

Zeigt in zwei Tabs eine tabellarische Uebersicht aller
Sensor/Taster-Belegungen und Aktor-GA-Zuordnungen des Projekts.
Datenquelle: BelegungsplanService (bereits im Projekt vorhanden).
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView, QFileDialog,
    QMessageBox, QFrame, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QBrush, QColor

logger = logging.getLogger("knix_arranger.linking_matrix_view")

# Farben
_COLOR_SENSOR_ODD  = QColor("#F3F8FF")
_COLOR_ACTOR_ODD   = QColor("#F3FFF6")


# --------------- Sensor-Tab Spalten ---------------
_S_HEADERS = [
    "Stockwerk", "Zone", "Raum-Nr.", "Raumname",
    "Sensor-Typ", "Phys. Adresse", "Taste",
    "Funktion", "GA-Bezeichnung", "GA-Adresse", "DPT",
]
_S_COL = {h: i for i, h in enumerate(_S_HEADERS)}

# --------------- Aktor-Tab Spalten ---------------
_A_HEADERS = [
    "Linie", "UV / Einbauort", "Aktor-Typ", "Phys. Adresse", "Kanal",
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
        self._setup_ui()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Laedt Projekt und baut die Matrix auf."""
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
        title = QLabel("Verknuepfungsmatrix (FA-2500)")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel(
            "Tabellarische Uebersicht aller Sensor/Taster-Belegungen und "
            "Aktor-GA-Zuordnungen. Grundlage fuer die ETS-Programmierung "
            "und die Revisionsunterlagen."
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

        # FA-2501: Raumfilter
        filter_layout = QHBoxLayout()
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

        # Sensor-Tab
        self._sensor_table = self._create_table(_S_HEADERS)
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
        rows = self._belegungsplan.sensor_rows if self._belegungsplan else []
        hdr = self._sensor_table.horizontalHeader()
        # Disable auto-resize during fill: ResizeToContents mode triggers a
        # column-width recalculation on every setItem() call which is O(n*cols).
        for i in range(len(_S_HEADERS)):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
        self._sensor_table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            color = _COLOR_SENSOR_ODD if r_idx % 2 == 0 else None
            data = [
                row.floor_name, row.zone_name, row.room_number, row.room_name,
                row.sensor_type, row.physical_address, row.taste_label,
                row.function, row.ga_designation, row.ga_address, row.dpt,
            ]
            for c_idx, text in enumerate(data):
                self._sensor_table.setItem(r_idx, c_idx, _make_item(text, color))
        # Single resize pass after all data is in place
        self._sensor_table.resizeColumnsToContents()
        _MAX_COL_WIDTH = 220
        for _cap_col in ("Sensor-Typ", "Stockwerk", "Zone"):
            _idx = _S_COL.get(_cap_col)
            if _idx is not None and self._sensor_table.columnWidth(_idx) > _MAX_COL_WIDTH:
                self._sensor_table.setColumnWidth(_idx, _MAX_COL_WIDTH)
        for i, h in enumerate(_S_HEADERS):
            if "Bezeichnung" in h or "Raumname" in h or "Funktion" in h:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)

    def _fill_actor_tab(self):
        rows = self._belegungsplan.actor_rows if self._belegungsplan else []
        hdr = self._actor_table.horizontalHeader()
        for i in range(len(_A_HEADERS)):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
        self._actor_table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            color = _COLOR_ACTOR_ODD if r_idx % 2 == 0 else None
            data = [
                row.line_name, row.uv_location, row.actor_type,
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
        """FA-2501: Befuellt den Raum-Filter-ComboBox mit den aktuellen Raeumen."""
        self._room_filter.blockSignals(True)
        self._room_filter.clear()
        self._room_filter.addItem("Alle Räume")
        if self._belegungsplan:
            seen = set()
            for row in self._belegungsplan.sensor_rows:
                key = f"{row.room_number}  {row.room_name}"
                if key not in seen:
                    seen.add(key)
                    self._room_filter.addItem(key, userData=row.room_number)
            for row in self._belegungsplan.actor_rows:
                key = f"{row.room_number}  {row.room_name}"
                if key not in seen:
                    seen.add(key)
                    self._room_filter.addItem(key, userData=row.room_number)
        self._room_filter.blockSignals(False)

    def _apply_filter(self):
        """FA-2501: Blendet Zeilen ein/aus basierend auf dem Raum-Filter."""
        room_num = self._room_filter.currentData()  # None wenn "Alle Räume"
        for table, col_idx in (
            (self._sensor_table, _S_COL["Raum-Nr."]),
            (self._actor_table,  _A_COL["Raum-Nr."]),
        ):
            for row in range(table.rowCount()):
                if room_num is None:
                    table.setRowHidden(row, False)
                else:
                    item = table.item(row, col_idx)
                    table.setRowHidden(row, item is None or item.text() != room_num)

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
