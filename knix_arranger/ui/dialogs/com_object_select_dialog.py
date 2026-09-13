"""
Dialog zur Auswahl, welche ComObjects eines verknüpften Produkts eine
Gruppenadresse erhalten sollen.

Grosse Gateway-/Sensorprodukte (z.B. Multimedia-Gateways, Wetterstationen)
können hunderte GA-relevante ComObjects mitbringen – deutlich mehr, als ein
Projekt tatsächlich braucht. Dieser Dialog lässt den Integrator gezielt
abwählen, was keine GA bekommen soll; die Auswahl wird als
GewerkAssignment.linked_product["excluded_co_numbers"] gespeichert und von
AddressGenerator._build_product_schema berücksichtigt.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialogButtonBox, QCheckBox, QWidget,
)
from PySide6.QtCore import Qt

from ...services.knxprod_catalog_service import ComObjectInfo

_COL_CHECK    = 0
_COL_NUMBER   = 1
_COL_FUNCTION = 2
_COL_DPT      = 3
_COL_FLAGS    = 4


class ComObjectSelectDialog(QDialog):
    """Lässt auswählen, welche GA-relevanten ComObjects eines Produkts
    tatsächlich eine Gruppenadresse bekommen sollen."""

    def __init__(self, product_label: str, com_objects: list[dict],
                 excluded_numbers: set[int] | None = None,
                 default_all_selected: bool = True,
                 header_note: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gruppenadressen-Auswahl")
        self.setMinimumSize(720, 560)

        all_infos = [ComObjectInfo.from_dict(co) for co in com_objects]
        self._relevant: list[ComObjectInfo] = [i for i in all_infos if i.needs_ga]
        self._checkboxes: list[QCheckBox] = []
        self._want_different_product = False

        # Ohne explizite Vorauswahl entscheidet default_all_selected über den
        # Ausgangszustand: True = alle an (Standardfall Gewerk-Produkt), False
        # = alle aus (Opt-in-Fall Taster-Zusatzsensorik – nur bewusst
        # ausgewählte Zusatzfunktionen sollen eine GA bekommen).
        if excluded_numbers is not None:
            excluded = set(excluded_numbers)
        elif default_all_selected:
            excluded = set()
        else:
            excluded = {i.number for i in self._relevant}

        layout = QVBoxLayout(self)

        header_note = header_note or (
            "Abgewählte Objekte erhalten keine Gruppenadresse."
        )
        header = QLabel(
            f"<b>{product_label}</b><br>"
            f"{len(self._relevant)} von {len(all_infos)} ComObjects sind "
            f"GA-relevant. {header_note}"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Suche:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Nummer, Name oder Funktion…")
        self._search_edit.textChanged.connect(self._apply_filter)
        search_layout.addWidget(self._search_edit)
        layout.addLayout(search_layout)

        toolbar = QHBoxLayout()
        btn_all = QPushButton("Alle auswählen")
        btn_all.setToolTip("Wirkt nur auf aktuell sichtbare (gefilterte) Zeilen")
        btn_all.clicked.connect(lambda: self._set_visible(True))
        toolbar.addWidget(btn_all)
        btn_none = QPushButton("Alle abwählen")
        btn_none.setToolTip("Wirkt nur auf aktuell sichtbare (gefilterte) Zeilen")
        btn_none.clicked.connect(lambda: self._set_visible(False))
        toolbar.addWidget(btn_none)
        toolbar.addStretch()
        self._count_label = QLabel()
        toolbar.addWidget(self._count_label)
        layout.addLayout(toolbar)

        self._table = QTableWidget(len(self._relevant), 5)
        self._table.setHorizontalHeaderLabels(["", "Nr.", "Funktion", "DPT", "Flags"])
        self._table.horizontalHeader().setSectionResizeMode(_COL_FUNCTION, QHeaderView.Stretch)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        for row, info in enumerate(self._relevant):
            checkbox = QCheckBox()
            checkbox.setChecked(info.number not in excluded)
            checkbox.stateChanged.connect(self._update_count)
            self._checkboxes.append(checkbox)
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.addWidget(checkbox)
            holder_layout.setAlignment(Qt.AlignCenter)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(row, _COL_CHECK, holder)

            self._table.setItem(row, _COL_NUMBER, QTableWidgetItem(str(info.number)))
            func_text = info.function_text or info.name
            self._table.setItem(row, _COL_FUNCTION, QTableWidgetItem(func_text))
            self._table.setItem(row, _COL_DPT, QTableWidgetItem(info.datapoint_type))
            self._table.setItem(row, _COL_FLAGS, QTableWidgetItem(info.flags_display))

        layout.addWidget(self._table)
        self._update_count()

        footer = QHBoxLayout()
        btn_other = QPushButton("Anderes Produkt wählen…")
        btn_other.setToolTip("Bricht diese Auswahl ab und öffnet die Produktsuche erneut")
        btn_other.clicked.connect(self._choose_different_product)
        footer.addWidget(btn_other)
        footer.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    # ------------------------------------------------------------------

    def _apply_filter(self, text: str):
        text = text.lower().strip()
        for row, info in enumerate(self._relevant):
            haystack = f"{info.number} {info.name} {info.function_text}".lower()
            self._table.setRowHidden(row, bool(text) and text not in haystack)

    def _set_visible(self, checked: bool):
        for row, checkbox in enumerate(self._checkboxes):
            if not self._table.isRowHidden(row):
                checkbox.setChecked(checked)

    def _update_count(self):
        selected = sum(1 for cb in self._checkboxes if cb.isChecked())
        self._count_label.setText(f"{selected} von {len(self._relevant)} ausgewählt")

    def _choose_different_product(self):
        self._want_different_product = True
        self.reject()

    # ------------------------------------------------------------------ Ergebnis

    def excluded_numbers(self) -> set[int]:
        """Nummern der abgewählten ComObjects (sollen keine GA erhalten)."""
        return {
            info.number for info, cb in zip(self._relevant, self._checkboxes)
            if not cb.isChecked()
        }

    def wants_different_product(self) -> bool:
        """True wenn der Nutzer 'Anderes Produkt wählen…' geklickt hat."""
        return self._want_different_product
