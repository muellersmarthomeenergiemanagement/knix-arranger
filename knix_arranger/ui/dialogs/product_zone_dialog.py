"""
Zonen eines Produkts mit KOs je Raum oder Kanal zuordnen (siehe
services/product_zones), z.B. Revox Multiuser 3.0: welcher Revox-Raum
gehört zu welchem KNiX-Raum, und welcher Raum trägt die Systemobjekte
(System Off, Szenen, KNX-Actions).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHeaderView,
    QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...services.product_zones import zone_label, zone_scheme, zones_of


class ProductZoneDialog(QDialog):
    """Tabelle Raum | Zone im Gerät | Systemobjekte für alle Zuweisungen mit
    dem Produkt. rows: (Beschriftung, Produkt-Dict); apply() schreibt "zone"
    und "system_objects" in die Produkt-Dicts."""

    def __init__(self, product_label: str, rows: list[tuple[str, dict]], parent=None):
        super().__init__(parent)
        self._rows = rows
        product = rows[0][1] if rows else {}
        scheme = zone_scheme(product)
        unit = scheme.label if scheme else "Raum"
        zones = zones_of(product)
        self.setWindowTitle(f"{unit} im Gerät zuordnen")
        self.setMinimumSize(560, 320)

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"{product_label} hat Kommunikationsobjekte je {unit} "
            f"({zone_label(product, zones[0])} … {zone_label(product, zones[-1])}).\n"
            "Jeder KNiX-Raum erhält nur die KOs seiner Zuordnung "
            f"(z.B. {zone_label(product, zones[0])}); die ausgewählten Funktionen "
            "gelten für alle.\n"
            "Systemobjekte (KOs ohne Zuordnung, z.B. System Off, Szenen) nur "
            "in einem Raum anlegen."
            if zones else f"{product_label}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._table = QTableWidget(len(rows), 3)
        self._table.setHorizontalHeaderLabels(["Raum", f"{unit} im Gerät", "Systemobjekte"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._combos: list[QComboBox] = []
        self._checks: list[QCheckBox] = []
        for row, (label, row_product) in enumerate(rows):
            self._table.setItem(row, 0, QTableWidgetItem(label))
            combo = QComboBox()
            combo.addItem("alle", 0)
            for zone in zones:
                combo.addItem(zone_label(product, zone), zone)
            combo.setCurrentIndex(max(0, combo.findData(int(row_product.get("zone") or 0))))
            combo.setToolTip(f"{unit} im Gerät, dessen KOs dieser Raum erhält; "
                             "«alle» = alle ausgewählten KOs")
            self._table.setCellWidget(row, 1, combo)
            self._combos.append(combo)
            check = QCheckBox()
            check.setChecked(bool(row_product.get("system_objects")))
            self._table.setCellWidget(row, 2, check)
            self._checks.append(check)
        layout.addWidget(self._table)

        self._warning = QLabel()
        self._warning.setStyleSheet("color: #b26a00;")
        layout.addWidget(self._warning)
        self._unit = unit
        for combo in self._combos:
            combo.currentIndexChanged.connect(self._check)
        for check in self._checks:
            check.toggled.connect(self._check)
        self._check()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _check(self) -> None:
        zones = [z for z, _s in self.values() if z]
        problems = []
        if len(zones) != len(set(zones)):
            problems.append(f"Ein {self._unit} im Gerät ist mehreren KNiX-Räumen zugeordnet.")
        if sum(c.isChecked() for c in self._checks) > 1:
            problems.append("Systemobjekte sind in mehreren Räumen angelegt.")
        self._warning.setText("\n".join(problems))

    def values(self) -> list[tuple[int, bool]]:
        return [(int(combo.currentData() or 0), check.isChecked())
                for combo, check in zip(self._combos, self._checks)]

    def apply(self) -> None:
        for (_label, product), (zone, system) in zip(self._rows, self.values()):
            if zone:
                product["zone"] = zone
            else:
                product.pop("zone", None)
            product["system_objects"] = system
