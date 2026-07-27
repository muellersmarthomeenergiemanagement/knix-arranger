"""
Dialog zum Anlegen eines benutzerdefinierten Gewerks (FA-303).

Für Bedarfe, die der Standard-Katalog (41 Gewerke) nicht abdeckt -- z.B. ein
spezifisches Fremdsystem-Gateway (Musikanlage, individuelle Wärmepumpen-
Steuerung) oder eine Zusatzfunktion eines Kombigeräts (z.B. die Binäreingänge
eines Schaltaktors mit integriertem Eingang), die sich in kein bestehendes
Gewerk einordnen lässt.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QSpinBox,
    QDialogButtonBox, QLabel, QMessageBox,
)

from ...models.gewerk import Gewerk, GewerkCatalog

# Deckt sich mit GEWERK_CATEGORY_LABELS in report_service.py (Filter-Buttons
# GA-Ansicht) -- ein neues Gewerk muss in eine dieser Kategorien passen, damit
# es in bestehenden Berichten/Filtern korrekt einsortiert wird.
_CATEGORY_LABELS = {
    "licht": "Licht",
    "licht_color": "Licht (Farbe)",
    "jalousie": "Jalousie",
    "heizung": "Heizung",
    "lueftung": "Lüftung / Klima",
    "energie": "Energie",
    "alarm": "Alarm",
    "allgemein": "Allgemein",
}

_INTERFACE_LABELS = {
    "actor": "Standard-Aktor (Schalt-/Dimm-/Jalousieaktor o.ä.)",
    "gateway": "Fremdsystem-Gateway (z.B. Musikanlage, individuelle Wärmepumpe)",
    "system_sensor": "Systemsensor (gewerkeübergreifend, kein Raumbezug)",
}


class CustomGewerkDialog(QDialog):
    """Dialog zum Anlegen eines benutzerdefinierten Gewerks."""

    def __init__(self, catalog: GewerkCatalog, parent=None):
        super().__init__(parent)
        self._catalog = catalog
        self._result_gewerk: Gewerk | None = None
        self.setWindowTitle("Eigenes Gewerk anlegen")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Für Bedarfe, die der Standard-Katalog nicht abdeckt. Das Gewerk "
            "wird mit dem Projekt gespeichert und steht danach überall zur "
            "Verfügung, wo Gewerke zugewiesen werden -- inklusive "
            "automatischer Gruppenadress-Erzeugung.\n\n"
            "Automatische Aktor-/Produktvorschläge funktionieren dafür nicht -- "
            "das Gerät muss manuell zugewiesen und seine Kommunikationsobjekte "
            "über die CO-Verknüpfung manuell mit Gruppenadressen verbunden "
            "werden."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666;")
        layout.addWidget(info)

        form = QFormLayout()

        self._code_edit = QLineEdit()
        self._code_edit.setMaxLength(4)
        self._code_edit.setPlaceholderText("z.B. MU")
        form.addRow("Kürzel:", self._code_edit)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("z.B. Musikanlage")
        form.addRow("Name:", self._name_edit)

        self._category_combo = QComboBox()
        for key, label in _CATEGORY_LABELS.items():
            self._category_combo.addItem(label, key)
        self._category_combo.setCurrentIndex(list(_CATEGORY_LABELS).index("allgemein"))
        form.addRow("Kategorie:", self._category_combo)

        self._interface_combo = QComboBox()
        for key, label in _INTERFACE_LABELS.items():
            self._interface_combo.addItem(label, key)
        self._interface_combo.setCurrentIndex(list(_INTERFACE_LABELS).index("gateway"))
        form.addRow("Schnittstellentyp:", self._interface_combo)

        self._block_combo = QComboBox()
        self._block_combo.addItem("5 (Standard)", 5)
        self._block_combo.addItem("10 (z.B. für Gateways mit vielen GAs)", 10)
        form.addRow("GAs pro Element:", self._block_combo)

        self._mg_spin = QSpinBox()
        self._mg_spin.setRange(0, 6)
        self._mg_spin.setValue(4)
        self._mg_spin.setToolTip(
            "Mittelgruppe für die Gruppenadress-Erzeugung:\n"
            "0=Licht  1=Jalousie  2=Heizung  3=Szenen\n"
            "4=Allgemein  5=Lüftung/Klima  6=Energie"
        )
        form.addRow("Mittelgruppe:", self._mg_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        code = self._code_edit.text().strip().upper()
        name = self._name_edit.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Angaben fehlen", "Bitte Kürzel und Name angeben.")
            return
        if not code.isalpha():
            QMessageBox.warning(
                self, "Ungültiges Kürzel", "Das Kürzel darf nur Buchstaben enthalten."
            )
            return
        existing = self._catalog.get(code)
        if existing:
            QMessageBox.warning(
                self, "Kürzel bereits vergeben",
                f"Das Kürzel '{code}' wird bereits verwendet ({existing.name}). "
                "Bitte ein anderes wählen.",
            )
            return

        block = self._block_combo.currentData()
        self._result_gewerk = Gewerk(
            code=code, name=name,
            ga_count=block, block_size=block,
            middle_group=self._mg_spin.value(),
            category=self._category_combo.currentData(),
            interface_type=self._interface_combo.currentData(),
        )
        self.accept()

    def get_gewerk(self) -> Gewerk | None:
        return self._result_gewerk
