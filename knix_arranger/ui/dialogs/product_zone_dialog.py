"""
Zonen eines Produkts mit KOs je Raum zuordnen (siehe services/product_zones),
z.B. Revox Multiuser 3.0: welcher Revox-Raum gehört zu welchem KNiX-Raum,
und welcher Raum trägt die Systemobjekte (System Off, Szenen, KNX-Actions).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...services.product_zones import zones_of


class ProductZoneDialog(QDialog):
    """Tabelle Raum | Zone | Systemobjekte für alle Zuweisungen mit dem
    Produkt. rows: (Beschriftung, Produkt-Dict); apply() schreibt "zone" und
    "system_objects" in die Produkt-Dicts."""

    def __init__(self, product_label: str, rows: list[tuple[str, dict]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Räume des Produkts zuordnen")
        self.setMinimumSize(560, 320)
        self._rows = rows
        zones = zones_of(rows[0][1]) if rows else []
        max_zone = max(zones) if zones else 1

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"{product_label} hat Kommunikationsobjekte für {len(zones)} Räume.\n"
            "Jeder KNiX-Raum erhält nur die KOs seines Raums im Gerät; die "
            "ausgewählten Funktionen gelten für alle Räume.\n"
            "Systemobjekte (z.B. System Off, Szenen) nur in einem Raum anlegen."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._table = QTableWidget(len(rows), 3)
        self._table.setHorizontalHeaderLabels(["Raum", "Raum im Gerät", "Systemobjekte"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._spins: list[QSpinBox] = []
        self._checks: list[QCheckBox] = []
        for row, (label, product) in enumerate(rows):
            self._table.setItem(row, 0, QTableWidgetItem(label))
            spin = QSpinBox()
            spin.setRange(0, max_zone)
            spin.setSpecialValueText("alle")
            spin.setPrefix("Raum ")
            spin.setValue(int(product.get("zone") or 0))
            spin.setToolTip("Raum im Gerät (z.B. Revox-Raum 3 = KOs R_3_…); "
                            "«alle» = alle ausgewählten KOs")
            self._table.setCellWidget(row, 1, spin)
            self._spins.append(spin)
            check = QCheckBox()
            check.setChecked(bool(product.get("system_objects")))
            self._table.setCellWidget(row, 2, check)
            self._checks.append(check)
        layout.addWidget(self._table)

        self._warning = QLabel()
        self._warning.setStyleSheet("color: #b26a00;")
        layout.addWidget(self._warning)
        for spin in self._spins:
            spin.valueChanged.connect(self._check)
        for check in self._checks:
            check.toggled.connect(self._check)
        self._check()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _check(self) -> None:
        zones = [s.value() for s in self._spins if s.value()]
        problems = []
        if len(zones) != len(set(zones)):
            problems.append("Ein Raum im Gerät ist mehreren KNiX-Räumen zugeordnet.")
        n_system = sum(c.isChecked() for c in self._checks)
        if n_system > 1:
            problems.append("Systemobjekte sind in mehreren Räumen angelegt.")
        self._warning.setText("\n".join(problems))

    def values(self) -> list[tuple[int, bool]]:
        return [(s.value(), c.isChecked()) for s, c in zip(self._spins, self._checks)]

    def apply(self) -> None:
        for (_label, product), (zone, system) in zip(self._rows, self.values()):
            if zone:
                product["zone"] = zone
            else:
                product.pop("zone", None)
            product["system_objects"] = system
