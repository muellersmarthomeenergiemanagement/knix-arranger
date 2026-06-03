"""
Dialog zum Erstellen und Bearbeiten von Gewerke-Vorlagen.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QComboBox,
    QSpinBox, QGroupBox, QFormLayout, QAbstractItemView,
)
from PySide6.QtCore import Qt
from ..styles import KNX_GREEN
from ...models.gewerk import GewerkCatalog
from ..column_utils import fit_columns


class GewerkTemplateDialog(QDialog):
    """Dialog zum Erstellen/Bearbeiten einer Gewerke-Vorlage."""

    def __init__(self, catalog: GewerkCatalog,
                 name: str = "", gewerke: list[tuple[str, int]] | None = None,
                 parent=None):
        super().__init__(parent)
        self._catalog = catalog
        self._result_accepted = False

        is_edit = bool(name)
        self.setWindowTitle(
            "Vorlage bearbeiten" if is_edit else "Neue Vorlage erstellen"
        )
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # Name
        name_group = QGroupBox("Vorlagenname")
        name_layout = QFormLayout()
        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("z.B. Grosses Wohnzimmer")
        name_layout.addRow("Name:", self._name_edit)
        name_group.setLayout(name_layout)
        layout.addWidget(name_group)

        # Gewerke-Tabelle
        gewerk_group = QGroupBox("Gewerke in der Vorlage")
        gewerk_layout = QVBoxLayout()

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            "Kürzel", "Name", "Anzahl", "Aktion",
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        gewerk_layout.addWidget(self._table)

        # Gewerk hinzufügen
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("Gewerk:"))
        self._gewerk_combo = QComboBox()
        for code in catalog.all_codes():
            g = catalog.get(code)
            self._gewerk_combo.addItem(f"{code} - {g.name}", code)
        add_layout.addWidget(self._gewerk_combo)

        add_layout.addWidget(QLabel("Anzahl:"))
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 20)
        self._count_spin.setValue(1)
        add_layout.addWidget(self._count_spin)

        self._btn_add = QPushButton("Hinzufügen")
        self._btn_add.clicked.connect(self._add_gewerk)
        add_layout.addWidget(self._btn_add)

        gewerk_layout.addLayout(add_layout)
        gewerk_group.setLayout(gewerk_layout)
        layout.addWidget(gewerk_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_cancel = QPushButton("Abbrechen")
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_save = QPushButton("Speichern")
        self._btn_save.setStyleSheet(
            f"QPushButton {{ background-color: {KNX_GREEN}; color: white; "
            f"padding: 6px 20px; font-weight: bold; }}"
        )
        self._btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self._btn_save)

        layout.addLayout(btn_layout)

        # Bestehende Gewerke laden
        self._gewerke: list[tuple[str, int]] = list(gewerke) if gewerke else []
        self._refresh_table()

    def _refresh_table(self):
        self._table.setRowCount(len(self._gewerke))
        for i, (code, count) in enumerate(self._gewerke):
            gewerk = self._catalog.get(code)
            gewerk_name = gewerk.name if gewerk else "?"
            self._table.setItem(i, 0, QTableWidgetItem(code))
            self._table.setItem(i, 1, QTableWidgetItem(gewerk_name))
            self._table.setItem(i, 2, QTableWidgetItem(str(count)))

            btn = QPushButton("X")
            btn.setFixedWidth(30)
            btn.setObjectName("danger")
            btn.clicked.connect(lambda checked, idx=i: self._remove_gewerk(idx))
            self._table.setCellWidget(i, 3, btn)

        fit_columns(self._table)

    def _add_gewerk(self):
        code = self._gewerk_combo.currentData()
        count = self._count_spin.value()
        if not code:
            return
        self._gewerke.append((code, count))
        self._refresh_table()

    def _remove_gewerk(self, idx: int):
        if 0 <= idx < len(self._gewerke):
            self._gewerke.pop(idx)
            self._refresh_table()

    def _on_save(self):
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setFocus()
            self._name_edit.setStyleSheet("border: 1px solid red;")
            return
        if not self._gewerke:
            return
        self._name_edit.setStyleSheet("")
        self._result_accepted = True
        self.accept()

    def get_template(self) -> tuple[str, list[tuple[str, int]]] | None:
        """Gibt (name, gewerke) zurück wenn gespeichert, sonst None."""
        if not self._result_accepted:
            return None
        return self._name_edit.text().strip(), list(self._gewerke)
