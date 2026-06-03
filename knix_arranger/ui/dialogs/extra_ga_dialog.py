"""
Dialog zum Definieren zusätzlicher GA-Einträge für eine GewerkAssignment-Instanz.

Der Standard-Block eines Gewerks (z.B. 5er Licht) kann hier um beliebige
weitere GA-Funktionen ergänzt werden. Die Einträge werden als BlockEntry-Dicts
in GewerkAssignment.extra_entries gespeichert und bei der GA-Generierung
an den Standard-Block angehängt.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QLineEdit,
    QCheckBox, QHeaderView, QDialogButtonBox, QAbstractItemView,
)
from PySide6.QtCore import Qt

# Gängige KNX-Datenpunkttypen zur Auswahl
_DPT_OPTIONS = [
    ("DPST-1-1",   "1-Bit: Ein/Aus"),
    ("DPST-1-7",   "1-Bit: Stopp"),
    ("DPST-1-8",   "1-Bit: Auf/Ab"),
    ("DPST-3-7",   "4-Bit: Dimmen"),
    ("DPST-5-1",   "1-Byte: Prozent 0-100%"),
    ("DPST-5-10",  "1-Byte: Wert 0-255"),
    ("DPST-9-1",   "2-Byte: Temperatur"),
    ("DPST-17-1",  "1-Byte: Szenen-Nummer"),
    ("DPST-20-102","1-Byte: HVAC-Betriebsart"),
]

_COL_FUNCTION = 0
_COL_DPT      = 1
_COL_RESERVE  = 2
_COL_DELETE   = 3


class ExtraGaDialog(QDialog):
    """Dialog zum Verwalten zusätzlicher GA-Einträge einer GewerkAssignment."""

    def __init__(self, gewerk_code: str, block_size: int,
                 extra_entries: list[dict], parent=None):
        """
        Parameters
        ----------
        gewerk_code   : Kürzel des Gewerks, z.B. "LD"
        block_size    : Größe des Standard-Blocks (5 oder 10) – nur zur Anzeige
        extra_entries : Aktuelle Liste von BlockEntry-Dicts (wird nicht mutiert)
        """
        super().__init__(parent)
        self._block_size = block_size
        self._entries: list[dict] = [dict(e) for e in extra_entries]

        self.setWindowTitle(f"Zusätzliche GAs – Gewerk {gewerk_code}")
        self.setMinimumWidth(560)
        self.setMinimumHeight(360)

        layout = QVBoxLayout(self)

        info = QLabel(
            f"Standard-Block: {block_size} GAs (Offset 0–{block_size - 1}).\n"
            "Hier definierte Einträge werden bei der Generierung automatisch angehängt.\n"
            "Der Offset wird fortlaufend vergeben (erster Extra-Eintrag = Offset "
            f"{block_size})."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Tabelle
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Funktion", "DPT", "Reserve", ""])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self._table)

        # Hinzufügen-Zeile
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("Funktion:"))
        self._fn_edit = QLineEdit()
        self._fn_edit.setPlaceholderText("z.B. SZENE, SPERREN, STATUS")
        self._fn_edit.setMaximumWidth(160)
        add_layout.addWidget(self._fn_edit)

        add_layout.addWidget(QLabel("DPT:"))
        self._dpt_combo = QComboBox()
        for dpt, label in _DPT_OPTIONS:
            self._dpt_combo.addItem(f"{dpt}  {label}" if dpt else label, dpt)
        add_layout.addWidget(self._dpt_combo)

        self._reserve_check = QCheckBox("Reserve")
        self._reserve_check.setToolTip("Platzhalter ohne Funktion (wird als Reserve-Adresse generiert)")
        add_layout.addWidget(self._reserve_check)

        btn_add = QPushButton("+ Hinzufügen")
        btn_add.clicked.connect(self._add_entry)
        add_layout.addWidget(btn_add)
        add_layout.addStretch()
        layout.addLayout(add_layout)

        # OK / Abbrechen
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_table()

    # ── Tabelle ────────────────────────────────────────────────────────────

    def _refresh_table(self):
        self._table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            offset = self._block_size + row
            is_reserve = entry.get("is_reserve", False)
            fn = entry.get("function", "") if not is_reserve else "(Reserve)"
            dpt = entry.get("dpt", "") if not is_reserve else ""

            fn_item = QTableWidgetItem(f"+{offset}  {fn}")
            fn_item.setToolTip(f"Offset {offset} im Block")
            self._table.setItem(row, _COL_FUNCTION, fn_item)
            self._table.setItem(row, _COL_DPT, QTableWidgetItem(dpt))

            reserve_item = QTableWidgetItem("✓" if is_reserve else "")
            reserve_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, _COL_RESERVE, reserve_item)

            del_btn = QPushButton("X")
            del_btn.setFixedWidth(28)
            del_btn.setObjectName("danger")
            del_btn.clicked.connect(lambda checked, r=row: self._remove_entry(r))
            self._table.setCellWidget(row, _COL_DELETE, del_btn)

        self._table.resizeColumnToContents(_COL_DPT)

    # ── Aktionen ───────────────────────────────────────────────────────────

    def _add_entry(self):
        is_reserve = self._reserve_check.isChecked()
        fn = self._fn_edit.text().strip().upper()
        dpt = self._dpt_combo.currentData() if not is_reserve else ""

        if not is_reserve:
            if not fn:
                self._fn_edit.setFocus()
                self._fn_edit.setStyleSheet("border: 1px solid red;")
                return
            if not dpt:
                self._dpt_combo.setStyleSheet("border: 1px solid red;")
                return
        self._fn_edit.setStyleSheet("")
        self._dpt_combo.setStyleSheet("")

        entry = {
            "offset": self._block_size + len(self._entries),
            "function": "" if is_reserve else fn,
            "designation": "" if is_reserve else fn,
            "dpt": "" if is_reserve else dpt,
            "is_feedback": False,
            "is_reserve": is_reserve,
        }
        self._entries.append(entry)
        self._fn_edit.clear()
        self._reserve_check.setChecked(False)
        self._refresh_table()

    def _remove_entry(self, row: int):
        if 0 <= row < len(self._entries):
            self._entries.pop(row)
            # Offsets neu berechnen
            for i, e in enumerate(self._entries):
                e["offset"] = self._block_size + i
            self._refresh_table()

    # ── Ergebnis ───────────────────────────────────────────────────────────

    def get_extra_entries(self) -> list[dict]:
        """Gibt die aktualisierten Extra-Einträge zurück (nach accept())."""
        return [dict(e) for e in self._entries]
