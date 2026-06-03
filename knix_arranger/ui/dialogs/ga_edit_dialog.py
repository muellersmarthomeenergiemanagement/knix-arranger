"""
GA-Bearbeitungsdialog (FA-435)
Ermöglicht das Bearbeiten einer einzelnen Gruppenadresse.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QGridLayout, QCheckBox,
)
from PySide6.QtCore import Qt
from ..styles import KNX_GREEN, KNX_DARK_GREEN
from ...models.group_address import GroupAddress


# Gaengige DPT-Typen
DPT_OPTIONS = [
    "",
    "DPST-1-1",    # Schalten
    "DPST-1-7",    # Stopp
    "DPST-1-8",    # Auf/Ab
    "DPST-3-7",    # Dimmen
    "DPST-5-1",    # Prozentwert
    "DPST-9-1",    # Temperatur
    "DPST-17-1",   # Szene
    "DPST-20-102", # Betriebsart
]


class GaEditDialog(QDialog):
    """Dialog zum Bearbeiten einer Gruppenadresse."""

    def __init__(self, ga: GroupAddress, parent=None):
        super().__init__(parent)
        self._ga = ga
        self.setWindowTitle(f"GA bearbeiten: {ga.address}")
        self.setMinimumSize(500, 500)

        layout = QVBoxLayout(self)

        # Adresse (nur lesen)
        addr_group = QGroupBox("Adresse")
        addr_layout = QGridLayout()

        addr_layout.addWidget(QLabel("Gruppenadresse:"), 0, 0)
        addr_label = QLabel(f"{ga.address}")
        addr_label.setStyleSheet(
            f"font-weight: bold; font-size: 14px; color: {KNX_DARK_GREEN};"
        )
        addr_layout.addWidget(addr_label, 0, 1)

        addr_layout.addWidget(QLabel("Hauptgruppe:"), 1, 0)
        self._hg_spin = QLineEdit(str(ga.main_group))
        self._hg_spin.setMaxLength(2)
        addr_layout.addWidget(self._hg_spin, 1, 1)

        addr_layout.addWidget(QLabel("Mittelgruppe:"), 2, 0)
        self._mg_spin = QLineEdit(str(ga.middle_group))
        self._mg_spin.setMaxLength(1)
        addr_layout.addWidget(self._mg_spin, 2, 1)

        addr_layout.addWidget(QLabel("Untergruppe:"), 3, 0)
        self._ug_spin = QLineEdit(str(ga.sub_group))
        self._ug_spin.setMaxLength(3)
        addr_layout.addWidget(self._ug_spin, 3, 1)

        addr_group.setLayout(addr_layout)
        layout.addWidget(addr_group)

        # Eigenschaften
        prop_group = QGroupBox("Eigenschaften")
        prop_layout = QGridLayout()

        prop_layout.addWidget(QLabel("Bezeichnung:"), 0, 0)
        self._designation = QLineEdit(ga.designation)
        prop_layout.addWidget(self._designation, 0, 1)

        prop_layout.addWidget(QLabel("Beschreibung:"), 1, 0)
        self._description = QLineEdit(ga.description)
        prop_layout.addWidget(self._description, 1, 1)

        prop_layout.addWidget(QLabel("Datenpunkttyp:"), 2, 0)
        self._dpt = QComboBox()
        self._dpt.setEditable(True)
        self._dpt.addItems(DPT_OPTIONS)
        if ga.datapoint_type:
            idx = self._dpt.findText(ga.datapoint_type)
            if idx >= 0:
                self._dpt.setCurrentIndex(idx)
            else:
                self._dpt.setEditText(ga.datapoint_type)
        prop_layout.addWidget(self._dpt, 2, 1)

        prop_layout.addWidget(QLabel("Funktion:"), 3, 0)
        self._function = QLineEdit(ga.function_name)
        prop_layout.addWidget(self._function, 3, 1)

        prop_layout.addWidget(QLabel("Gewerk-Code:"), 4, 0)
        self._gewerk = QLineEdit(ga.gewerk_code)
        self._gewerk.setMaxLength(4)
        prop_layout.addWidget(self._gewerk, 4, 1)

        prop_layout.addWidget(QLabel("Raum-Nummer:"), 5, 0)
        self._room = QLineEdit(ga.room_number)
        prop_layout.addWidget(self._room, 5, 1)

        prop_layout.addWidget(QLabel("Element-Nummer:"), 6, 0)
        self._element = QLineEdit(str(ga.element_number))
        self._element.setMaxLength(3)
        prop_layout.addWidget(self._element, 6, 1)

        # Flags
        self._central = QCheckBox("Zentraladresse")
        self._central.setChecked(ga.central == "true")
        prop_layout.addWidget(self._central, 7, 0, 1, 2)

        self._placeholder = QCheckBox("Reserve/Platzhalter")
        self._placeholder.setChecked(ga.is_placeholder)
        prop_layout.addWidget(self._placeholder, 8, 0, 1, 2)

        prop_group.setLayout(prop_layout)
        layout.addWidget(prop_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Speichern")
        save_btn.setStyleSheet(
            f"background-color: {KNX_GREEN}; color: white; "
            f"font-weight: bold; padding: 6px 20px;"
        )
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _save(self):
        """Speichert die Änderungen in das GA-Objekt."""
        try:
            self._ga.main_group = int(self._hg_spin.text())
            self._ga.middle_group = int(self._mg_spin.text())
            self._ga.sub_group = int(self._ug_spin.text())
        except ValueError:
            pass

        self._ga.designation = self._designation.text()
        self._ga.description = self._description.text()
        self._ga.datapoint_type = self._dpt.currentText()
        self._ga.function_name = self._function.text()
        self._ga.gewerk_code = self._gewerk.text()
        self._ga.room_number = self._room.text()

        try:
            self._ga.element_number = int(self._element.text())
        except ValueError:
            self._ga.element_number = 0

        self._ga.central = "true" if self._central.isChecked() else ""
        self._ga.is_placeholder = self._placeholder.isChecked()

        self.accept()
