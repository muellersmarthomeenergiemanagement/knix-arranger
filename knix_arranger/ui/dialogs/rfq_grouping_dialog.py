"""
Dialog zur Herstellerzuweisung vor der Offertanfrage-Generierung.

Ermoeglicht das Zusammenfassen von Geraeten verschiedener Hersteller
fuer einen Gross-/Fachhaendler (FA-1611, FA-1615).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QCheckBox,
    QAbstractItemView, QDialogButtonBox, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ...models.quotation import Supplier
from ..column_utils import fit_columns

_NO_SUPPLIER_ID = ""
_NO_SUPPLIER_LABEL = "— Eigene Anfrage —"


class RfqGroupingDialog(QDialog):
    """
    Zeigt alle Hersteller aus der Materialliste und laesst den Benutzer
    festlegen, welcher Lieferant fuer welchen Hersteller angefragt wird.
    Mehrere Hersteller koennen demselben Lieferanten zugewiesen werden –
    sie landen dann in einer gemeinsamen Offertanfrage.
    """

    def __init__(
        self,
        manufacturer_counts: dict[str, int],  # {manufacturer: anzahl_positionen}
        suppliers: list[Supplier],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Offertanfragen generieren – Herstellerzuweisung")
        self.setMinimumSize(680, 440)
        self.resize(740, 500)

        self._suppliers = suppliers
        self._manufacturer_counts = manufacturer_counts
        self._combos: dict[str, QComboBox] = {}  # {manufacturer: combo}

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Info-Text ──
        info = QLabel(
            "Weisen Sie jedem Hersteller einen Lieferanten / Haendler zu. "
            "Hersteller mit <b>demselben Lieferanten</b> werden in einer einzigen "
            "Offertanfrage zusammengefasst. "
            "Lieferanten mit hinterlegten Marken werden automatisch vorgeschlagen."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # ── Tabelle ──
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Hersteller", "Pos.", "Lieferant / Haendler"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._table)

        self._populate_table()

        # ── Zusammenfassung ──
        self._summary_label = QLabel()
        font = self._summary_label.font()
        font.setBold(True)
        self._summary_label.setFont(font)
        layout.addWidget(self._summary_label)
        self._update_summary()

        # ── Marken speichern ──
        self._chk_save_brands = QCheckBox(
            "Lieferant-Markenzuordnung fuer kuenftige Projekte speichern"
        )
        self._chk_save_brands.setToolTip(
            "Speichert die Zuordnung in den Lieferanten-Stammdaten (Feld 'Marken'),\n"
            "sodass sie beim naechsten Projekt automatisch vorgeschlagen wird."
        )
        self._chk_save_brands.setChecked(True)
        layout.addWidget(self._chk_save_brands)

        # ── Buttons ──
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("Generieren")
        btn_box.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ── Aufbau ──

    def _populate_table(self):
        manufacturers = sorted(self._manufacturer_counts.keys(), key=str.lower)
        self._table.setRowCount(len(manufacturers))

        # Brand-Lookup: {brand_lower: Supplier}
        brand_to_supplier: dict[str, Supplier] = {}
        for sup in self._suppliers:
            for brand in sup.brands:
                key = brand.strip().lower()
                if key and key not in brand_to_supplier:
                    brand_to_supplier[key] = sup

        for row, mfr in enumerate(manufacturers):
            count = self._manufacturer_counts[mfr]

            item_mfr = QTableWidgetItem(mfr)
            item_mfr.setFlags(item_mfr.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 0, item_mfr)

            item_count = QTableWidgetItem(str(count))
            item_count.setTextAlignment(Qt.AlignCenter)
            item_count.setFlags(item_count.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 1, item_count)

            combo = QComboBox()
            combo.addItem(_NO_SUPPLIER_LABEL, _NO_SUPPLIER_ID)
            for sup in self._suppliers:
                combo.addItem(sup.company_name, sup.id)

            # Vorauswahl via Marken-Matching
            matched = brand_to_supplier.get(mfr.strip().lower())
            if matched:
                idx = combo.findData(matched.id)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            combo.currentIndexChanged.connect(self._update_summary)
            self._table.setCellWidget(row, 2, combo)
            self._combos[mfr] = combo

        fit_columns(self._table)

    def _update_summary(self):
        grouping = self._get_grouping()

        # Anzahl unterschiedlicher Anfragen ermitteln
        groups: set[str] = set()
        for mfr, sup_id in grouping.items():
            groups.add(sup_id if sup_id else f"__own__{mfr}")

        n = len(groups)
        n_combined = sum(
            1 for sup_id in grouping.values() if sup_id
        )
        n_own = sum(
            1 for sup_id in grouping.values() if not sup_id
        )

        parts = []
        if n_combined:
            unique_suppliers = {sup_id for sup_id in grouping.values() if sup_id}
            parts.append(f"{len(unique_suppliers)} Lieferanten-Anfrage(n)")
        if n_own:
            parts.append(f"{n_own} Einzelanfrage(n) ohne Lieferant")

        detail = " + ".join(parts) if parts else ""
        self._summary_label.setText(
            f"Ergebnis: {n} Offertanfrage(n) werden erstellt"
            + (f"  ({detail})" if detail else "") + "."
        )

    def _get_grouping(self) -> dict[str, str]:
        """Gibt {manufacturer: supplier_id_oder_''} zurueck."""
        return {mfr: (combo.currentData() or "") for mfr, combo in self._combos.items()}

    # ── Public API ──

    @property
    def grouping(self) -> dict[str, str]:
        """Ergebnis: {manufacturer: supplier_id oder '' fuer eigene Anfrage}."""
        return self._get_grouping()

    @property
    def save_brands(self) -> bool:
        """True wenn die Zuordnung in Supplier.brands zurueckgeschrieben werden soll."""
        return self._chk_save_brands.isChecked()
