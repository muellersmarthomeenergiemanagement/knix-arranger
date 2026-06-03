"""
Leitungslaengen-Ansicht (FA-2601 bis FA-2604)

Zeigt alle KNX-Linien mit ihren Leitungslaengen und Validierungsstatus.
Ermoeglicht die Eingabe von Stamm- und Stichleitungslaengen pro Linie.
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QComboBox, QDoubleSpinBox,
    QFrame, QMessageBox, QDialog, QDialogButtonBox, QListWidget,
    QListWidgetItem, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont

logger = logging.getLogger("knix_arranger.cable_length_view")

# Farben (FA-2603)
_COLOR_OK      = QColor("#C8E6C9")   # Gruen
_COLOR_WARN    = QColor("#FFF9C4")   # Gelb
_COLOR_ERROR   = QColor("#FFCDD2")   # Rot
_COLOR_NEUTRAL = QColor("#FAFAFA")   # Hellgrau (kein Eintrag)

# Spalten
_COL_AREA  = 0
_COL_LINE  = 1
_COL_FORM  = 2
_COL_TRUNK = 3
_COL_NBRANCH = 4
_COL_MAXBR = 5
_COL_TOTAL = 6
_COL_STATUS = 7
_NUM_COLS  = 8

_HEADERS = [
    "Bereich", "Linie", "Topologieform",
    "Stamm [m]", "Anz. Stichl.", "Max. Stichleitung [m]",
    "Gesamt [m]", "Status",
]

_TOPOLOGY_FORMS = ["Linie", "Stern", "Baum"]


class BranchDialog(QDialog):
    """Dialog zur Bearbeitung der einzelnen Stichleitungslaengen."""

    def __init__(self, branch_lengths: list[float], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stichleitungen bearbeiten")
        self.setMinimumWidth(320)
        self._lengths = list(branch_lengths)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Laenge jeder Stichleitung in Metern (KNX Max. 10 m):"
        ))

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self._list)
        self._refresh_list()

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Hinzufuegen")
        add_btn.clicked.connect(self._add)
        del_btn = QPushButton("Entfernen")
        del_btn.clicked.connect(self._remove)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_list(self):
        self._list.clear()
        for i, v in enumerate(self._lengths):
            item = QListWidgetItem(f"Stichleitung {i+1}: {v:.1f} m")
            item.setData(Qt.UserRole, v)
            self._list.addItem(item)

    def _add(self):
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 10.0)
        spin.setSingleStep(0.5)
        spin.setSuffix(" m")
        spin.setValue(5.0)
        # Simple inline dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Stichleitung hinzufuegen")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Laenge [m]:"))
        v.addWidget(spin)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() == QDialog.Accepted:
            self._lengths.append(spin.value())
            self._refresh_list()

    def _remove(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._lengths):
            del self._lengths[row]
            self._refresh_list()

    def get_lengths(self) -> list[float]:
        return list(self._lengths)


class CableLengthView(QWidget):
    """Ansicht fuer Leitungslaengen-Erfassung und -Validierung (FA-2601/2604)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._line_map: dict[str, object] = {}   # line_id → Line
        self._setup_ui()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        self._refresh()

    # ------------------------------------------------------------------
    # UI-Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Leitungslaengen (FA-2600)")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel(
            "Erfassen Sie die Leitungslaengen jeder KNX-Linie. "
            "Das System prueft die Werte gegen die KNX-TP-Grenzwerte "
            "(Gesamt max. 1000 m, Stamm max. 700 m, Stichleitung max. 10 m)."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)

        self._status_label = QLabel("Kein Projekt geladen.")
        self._status_label.setStyleSheet("font-size: 11px; color: #555;")
        layout.addWidget(self._status_label)

        # Tabelle
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_LINE, QHeaderView.Stretch
        )
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        layout.addWidget(self._table, 1)

        # Legende
        legend = QLabel(
            "Legende:  "
            "<span style='background:#C8E6C9; padding:2px 6px;'>OK</span>  "
            "<span style='background:#FFF9C4; padding:2px 6px;'>Warnung</span>  "
            "<span style='background:#FFCDD2; padding:2px 6px;'>Fehler</span>"
        )
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet("font-size: 10px;")
        layout.addWidget(legend)

        # Buttons
        btn_layout = QHBoxLayout()
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(self._refresh)
        btn_layout.addWidget(self._btn_refresh)
        btn_layout.addStretch()
        self._btn_save = QPushButton("Laengen speichern")
        self._btn_save.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; "
            "font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._btn_save.clicked.connect(self._save)
        self._btn_save.setEnabled(False)
        btn_layout.addWidget(self._btn_save)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _refresh(self):
        if not self._project:
            return
        self._line_map.clear()
        self._table.setRowCount(0)

        from ...services.cable_length_service import CableLengthService
        validations = CableLengthService().validate_project(self._project)

        # Linienkarte aufbauen
        for area in self._project.topology.areas:
            for lne in area.lines:
                self._line_map[lne.id] = lne

        self._table.setRowCount(len(validations))
        for row_idx, val in enumerate(validations):
            line = self._line_map.get(val.line_id)
            if not line:
                continue

            area_name = self._area_name_for_line(line)
            bg = _COLOR_NEUTRAL if val.total_length == 0 else {
                "OK": _COLOR_OK, "Warnung": _COLOR_WARN, "Fehler": _COLOR_ERROR
            }.get(val.status, _COLOR_NEUTRAL)

            # Bereich (read-only)
            self._set_item(row_idx, _COL_AREA, area_name, bg, editable=False)
            # Linie (read-only)
            self._set_item(row_idx, _COL_LINE, val.line_name, bg, editable=False)

            # Topologieform (ComboBox)
            combo = QComboBox()
            combo.addItems(_TOPOLOGY_FORMS)
            combo.setCurrentText(line.topology_form)
            combo.setProperty("line_id", line.id)
            combo.currentTextChanged.connect(
                lambda text, lid=line.id: self._on_form_changed(lid, text)
            )
            self._table.setCellWidget(row_idx, _COL_FORM, combo)

            # Stammleitung (SpinBox)
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setSingleStep(10.0)
            spin.setSuffix(" m")
            spin.setDecimals(1)
            spin.setValue(line.trunk_length)
            spin.setProperty("line_id", line.id)
            spin.valueChanged.connect(
                lambda val_, lid=line.id: self._on_trunk_changed(lid, val_)
            )
            self._table.setCellWidget(row_idx, _COL_TRUNK, spin)

            # Anzahl Stichleitungen (Button)
            n = len(line.branch_lengths)
            btn = QPushButton(f"{n} Stichleitung{'en' if n != 1 else ''} bearbeiten…")
            btn.setProperty("line_id", line.id)
            btn.clicked.connect(
                lambda checked=False, lid=line.id: self._edit_branches(lid)
            )
            self._table.setCellWidget(row_idx, _COL_NBRANCH, btn)

            # Max. Stichleitung (read-only, berechnet)
            max_br_text = f"{val.max_branch:.1f} m" if val.branch_count else "—"
            self._set_item(row_idx, _COL_MAXBR, max_br_text, bg, editable=False)

            # Gesamtlaenge (read-only, berechnet)
            total_text = f"{val.total_length:.1f} m" if val.total_length > 0 else "—"
            self._set_item(row_idx, _COL_TOTAL, total_text, bg, editable=False)

            # Status + Tooltip
            status_item = QTableWidgetItem(val.status if val.total_length > 0 else "—")
            status_item.setBackground(QBrush(bg))
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            if val.messages:
                status_item.setToolTip("\n".join(val.messages))
            self._table.setItem(row_idx, _COL_STATUS, status_item)

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_LINE, QHeaderView.Stretch
        )
        self._btn_save.setEnabled(bool(self._line_map))
        self._update_status(validations)

    def _set_item(self, row: int, col: int, text: str, bg: QColor, editable: bool = True):
        item = QTableWidgetItem(text)
        item.setBackground(QBrush(bg))
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self._table.setItem(row, col, item)

    def _area_name_for_line(self, line) -> str:
        for area in self._project.topology.areas:
            for lne in area.lines:
                if lne.id == line.id:
                    return area.name or f"Bereich {area.area_number}"
        return ""

    def _on_form_changed(self, line_id: str, text: str):
        line = self._line_map.get(line_id)
        if line:
            line.topology_form = text

    def _on_trunk_changed(self, line_id: str, value: float):
        line = self._line_map.get(line_id)
        if line:
            line.trunk_length = value

    def _edit_branches(self, line_id: str):
        line = self._line_map.get(line_id)
        if not line:
            return
        dlg = BranchDialog(line.branch_lengths, self)
        if dlg.exec() == QDialog.Accepted:
            line.branch_lengths = dlg.get_lengths()
            self._refresh()

    def _save(self):
        if self._project:
            self._project.touch()
            self._refresh()
            QMessageBox.information(
                self, "Gespeichert",
                "Leitungslaengen wurden im Projekt gespeichert."
            )

    def _update_status(self, validations):
        ok = sum(1 for v in validations if v.status == "OK" and v.total_length > 0)
        warn = sum(1 for v in validations if v.status == "Warnung")
        err = sum(1 for v in validations if v.status == "Fehler")
        empty = sum(1 for v in validations if v.total_length == 0)
        parts = [f"{len(validations)} Linien"]
        if ok:
            parts.append(f"{ok} OK")
        if warn:
            parts.append(f"{warn} Warnung(en)")
        if err:
            parts.append(f"{err} Fehler")
        if empty:
            parts.append(f"{empty} ohne Laengenangabe")
        self._status_label.setText("  |  ".join(parts))
