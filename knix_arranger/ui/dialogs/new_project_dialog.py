"""
Neues Projekt / Vorlage wählen (FA-010)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QGroupBox, QFormLayout, QPushButton, QRadioButton,
    QButtonGroup,
)
from PySide6.QtCore import Qt


class NewProjectDialog(QDialog):
    """Dialog zum Erstellen eines neuen Projekts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neues Projekt erstellen")
        self.setMinimumSize(500, 420)

        layout = QVBoxLayout(self)

        # Projektinfo
        info_group = QGroupBox("Projektinformationen")
        form = QFormLayout()

        self._name = QLineEdit()
        self._name.setPlaceholderText("z.B. Neubau EFH Mueller")
        form.addRow("Projektname:", self._name)

        self._number = QLineEdit()
        self._number.setPlaceholderText("z.B. 2024-001")
        form.addRow("Projektnummer:", self._number)

        info_group.setLayout(form)
        layout.addWidget(info_group)

        # Vorlage
        template_group = QGroupBox("Gebäudetyp")
        template_layout = QVBoxLayout()

        self._template_group = QButtonGroup(self)
        templates = [
            ("empty", "Leeres Projekt"),
            ("efh", "Einfamilienhaus (EFH) - 4 Stockwerke"),
            ("mfh", "Mehrfamilienhaus (MFH) - 3 Stockwerke, 2 Wohnungen"),
            ("zweckbau", "Zweckbau - 2 Stockwerke, Zonen"),
        ]
        for key, text in templates:
            radio = QRadioButton(text)
            radio.setProperty("template_key", key)
            self._template_group.addButton(radio)
            template_layout.addWidget(radio)
            if key == "efh":
                radio.setChecked(True)

        template_group.setLayout(template_layout)
        layout.addWidget(template_group)

        # MG-Variante
        variant_group = QGroupBox("Mittelgruppen-Variante")
        variant_layout = QVBoxLayout()

        self._variant_group = QButtonGroup(self)
        self._variant_a = QRadioButton(
            "Variante A - Rückmeldungen in gleicher MG (Standard)"
        )
        self._variant_b = QRadioButton(
            "Variante B - Rückmeldungen in MG 6/7 (separate)"
        )
        self._variant_a.setChecked(True)
        self._variant_group.addButton(self._variant_a)
        self._variant_group.addButton(self._variant_b)
        variant_layout.addWidget(self._variant_a)
        variant_layout.addWidget(self._variant_b)

        variant_group.setLayout(variant_layout)
        layout.addWidget(variant_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_cancel = QPushButton("Abbrechen")
        self._btn_cancel.setObjectName("secondary")
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_create = QPushButton("Projekt erstellen")
        self._btn_create.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_create)
        layout.addLayout(btn_layout)

    @property
    def project_name(self) -> str:
        return self._name.text().strip()

    @property
    def project_number(self) -> str:
        return self._number.text().strip()

    @property
    def template_key(self) -> str:
        btn = self._template_group.checkedButton()
        return btn.property("template_key") if btn else "empty"

    @property
    def variant(self) -> str:
        return "B" if self._variant_b.isChecked() else "A"
