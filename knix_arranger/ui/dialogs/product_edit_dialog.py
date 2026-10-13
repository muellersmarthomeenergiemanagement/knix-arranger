"""
Stammdaten eines Katalogprodukts bearbeiten (Hersteller, Bestellnummer,
Produktname, Gerätetyp, Kanäle, Preis, URL). Kommunikationsobjekte und
ETS-Kennungen bleiben -- sie kommen nur aus dem KNXPROD-Import.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

# Feld für den Gerätetyp je Kategorie
_TYPE_FIELD = {"actor": "actor_type", "sensor": "sensor_type"}


class ProductEditDialog(QDialog):
    """Bearbeitet die Stammdaten eines Produkts; changes() liefert die Felder
    für ProductSearchService.edit_product()."""

    def __init__(self, product: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Produkt bearbeiten")
        self.setMinimumWidth(480)
        self._type_field = _TYPE_FIELD.get(product.get("category", ""), "device_type")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._manufacturer = QLineEdit(product.get("manufacturer", ""))
        self._order_number = QLineEdit(product.get("order_number", ""))
        self._product_name = QLineEdit(product.get("product_name", ""))
        self._type = QLineEdit(product.get(self._type_field, ""))
        self._channels = QSpinBox()
        self._channels.setRange(0, 999)
        self._channels.setSpecialValueText("–")
        self._channels.setValue(int(product.get("channels", 0) or 0))
        self._price = QLineEdit(product.get("price_hint", ""))
        self._url = QLineEdit(product.get("url", ""))
        form.addRow("Hersteller:", self._manufacturer)
        form.addRow("Bestellnummer:", self._order_number)
        form.addRow("Produktname:", self._product_name)
        form.addRow("Gerätetyp:", self._type)
        form.addRow("Kanäle:", self._channels)
        form.addRow("Preis:", self._price)
        form.addRow("URL:", self._url)
        layout.addLayout(form)

        n_cos = len(product.get("com_objects") or [])
        if n_cos:
            note = QLabel(f"{n_cos} Kommunikationsobjekte bleiben unverändert.")
            note.setStyleSheet("color: #666;")
            layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if not self._manufacturer.text().strip() or not self._order_number.text().strip():
            self._manufacturer.setFocus()
            return
        self.accept()

    def changes(self) -> dict:
        return {
            "manufacturer": self._manufacturer.text().strip(),
            "order_number": self._order_number.text().strip(),
            "product_name": self._product_name.text().strip(),
            self._type_field: self._type.text().strip(),
            "channels": self._channels.value(),
            "price_hint": self._price.text().strip(),
            "url": self._url.text().strip(),
        }
