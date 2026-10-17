"""
Mehr Tasten geplant als das Produkt hat (FA-629, FA-1411c): drei Wege zur
Wahl -- in der Bauherrenberatung verteilen, auf zwei Taster aufteilen (wie
bei Aktoren) oder ein Produkt mit genügend Tasten wählen.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QButtonGroup, QListWidget, QListWidgetItem, QApplication,
)
from PySide6.QtCore import Qt
from ..styles import KNX_PRIMARY

BAUHERR, SPLIT, PRODUCT = "bauherr", "split", "product"


class KeyShortageDialog(QDialog):
    """Wahl des Wegs; bei «Produkt» zusätzlich das Produkt (selected_product)."""

    def __init__(self, shortage, catalog=None, parent=None):
        super().__init__(parent)
        self._shortage = shortage
        self._catalog = catalog
        self._options_loaded = False
        self.choice = ""
        self.selected_product = None
        device = shortage.device
        name = device.product_name or device.product
        surplus = shortage.planned - shortage.available
        self.setWindowTitle("Tasten anpassen")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        info = QLabel(
            f"<b>{device.physical_address}</b> ({shortage.room.number} {shortage.room.name}): "
            f"{shortage.planned} Tasten geplant, {name} hat {shortage.available}.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._group = QButtonGroup(self)
        self._bauherr = QRadioButton("In der Bauherrenberatung verteilen – Funktionen von Hand "
                                     "auf andere Taster legen oder zusammenfassen")
        self._split = QRadioButton(
            f"Auf zwei Taster aufteilen – die letzten {surplus} Taste(n) auf eine zweite "
            f"Tastereinheit im selben Raum, mit demselben Produkt")
        self._product = QRadioButton(f"Produkt mit mindestens {shortage.planned} Tasten wählen")
        for i, button in enumerate((self._bauherr, self._split, self._product)):
            self._group.addButton(button, i)
            layout.addWidget(button)
        self._split.setChecked(True)

        self._list = QListWidget()
        self._list.setEnabled(False)
        self._list.itemDoubleClicked.connect(lambda _i: self._accept())
        layout.addWidget(self._list)
        self._hint = QLabel("Zuerst gleicher Hersteller und dieselben Fühler, dann die kleinste "
                            "passende Tastenzahl.")
        self._hint.setStyleSheet("color: #666666; font-style: italic;")
        layout.addWidget(self._hint)
        self._product.toggled.connect(self._on_product_toggled)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("Übernehmen")
        ok.setStyleSheet(f"background-color: {KNX_PRIMARY}; color: white; "
                         f"font-weight: bold; padding: 6px 20px;")
        ok.clicked.connect(self._accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _on_product_toggled(self, checked: bool) -> None:
        self._list.setEnabled(checked)
        if checked and not self._options_loaded:
            self._load_options()

    def _load_options(self) -> None:
        from ...services.product_capabilities import products_with_keys
        self._options_loaded = True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            options = (products_with_keys(self._catalog, self._shortage.device,
                                          self._shortage.planned)
                       if self._catalog is not None else [])
        finally:
            QApplication.restoreOverrideCursor()
        for option in options:
            prod = option.product
            item = QListWidgetItem(f"{prod.manufacturer} · {prod.product_name} "
                                   f"({prod.order_number}) – {option.capabilities.summary}")
            item.setData(Qt.UserRole, prod)
            self._list.addItem(item)
        if options:
            self._list.setCurrentRow(0)
        else:
            self._list.addItem("Kein Taster mit genügend Tasten im Katalog.")

    def _accept(self) -> None:
        if self._bauherr.isChecked():
            self.choice = BAUHERR
        elif self._split.isChecked():
            self.choice = SPLIT
        else:
            item = self._list.currentItem()
            prod = item.data(Qt.UserRole) if item is not None else None
            if prod is None:
                return
            self.choice, self.selected_product = PRODUCT, prod
        self.accept()
