"""
Neues Projekt / Vorlage wählen (FA-010)
"""
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QGroupBox, QFormLayout, QPushButton, QRadioButton,
    QButtonGroup, QCheckBox,
)
from PySide6.QtCore import Qt


class NewProjectDialog(QDialog):
    """Dialog zum Erstellen eines neuen Projekts."""

    def __init__(self, parent=None, workspace_root: str = "", project_service=None,
                 reconstruct: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Neues Projekt erstellen")
        self.setMinimumSize(500, 420)

        self._workspace_root = workspace_root
        self._project_service = project_service

        layout = QVBoxLayout(self)

        # Projektinfo
        info_group = QGroupBox("Projektinformationen")
        form = QFormLayout()

        self._name = QLineEdit()
        self._name.setPlaceholderText("z.B. Neubau EFH Müller")
        self._name.textChanged.connect(self._update_preview)
        form.addRow("Projektname:", self._name)

        self._number = QLineEdit()
        self._number.setPlaceholderText("z.B. 2024-001")
        form.addRow("Projektnummer:", self._number)

        info_group.setLayout(form)
        layout.addWidget(info_group)

        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        layout.addWidget(self._preview_label)

        # Vorgehen (FA-3105e): planen oder bestehende Anlage vom Bus aufnehmen
        mode_group = QGroupBox("Vorgehen")
        mode_layout = QVBoxLayout()
        self._mode_plan = QRadioButton("Neues Projekt planen")
        self._mode_reconstruct = QRadioButton(
            "Bestehende Anlage ohne Projektdatei aufnehmen (vom Bus)")
        self._mode_plan.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._mode_plan)
        self._mode_group.addButton(self._mode_reconstruct)
        mode_hint = QLabel(
            "Aufnehmen: leeres Projekt, danach «Teilnehmer suchen» mit den Schritten "
            "Verbinden, Suchen, Übernehmen, GAs lesen, Bedeutung ergänzen, Gebäude "
            "erfassen, Rundgang. Mit ETS-Projektdatei stattdessen die .knxproj einlesen.")
        mode_hint.setWordWrap(True)
        mode_hint.setObjectName("hint")
        mode_layout.addWidget(self._mode_plan)
        mode_layout.addWidget(self._mode_reconstruct)
        mode_layout.addWidget(mode_hint)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # Vorlage
        template_group = QGroupBox("Gebäudetyp")
        self._template_box = template_group
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
        # Erklärung: die Wahl prägt alle Adressen (KNX Swiss Richtlinien)
        variant_hint = QLabel(
            "A: Rückmeldungen in derselben Mittelgruppe wie die Befehle, im Block "
            "des Elements.\n"
            "B: Rückmeldungen getrennt in den Mittelgruppen 6/7, unter derselben "
            "Untergruppe wie ihr Befehl.\n"
            "Änderbar im Wizard (Schritt 9), solange das Projekt nicht in die ETS "
            "übertragen ist.")
        variant_hint.setWordWrap(True)
        variant_hint.setObjectName("hint")
        variant_layout.addWidget(variant_hint)

        variant_group.setLayout(variant_layout)
        layout.addWidget(variant_group)
        self._variant_box = variant_group

        # Nächster Schritt: meist die Grundplanung im Wizard
        self._start_wizard = QCheckBox("Danach den Wizard starten")
        self._start_wizard.setChecked(True)
        layout.addWidget(self._start_wizard)
        self._mode_reconstruct.toggled.connect(self._mode_changed)
        if reconstruct:
            # Einstieg «Anlage vom Bus aufnehmen» (Willkommensbildschirm)
            self._mode_reconstruct.setChecked(True)

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

        self._update_preview()

    def _update_preview(self):
        """Zeigt den künftigen Projektordner an und validiert den Namen."""
        name = self.project_name
        if not name:
            self._preview_label.setText("Bitte einen Projektnamen eingeben.")
            self._preview_label.setStyleSheet("color: #B71C1C;")
            self._btn_create.setEnabled(False)
            return

        if self._workspace_root and self._project_service:
            knxarr_path = self._project_service.project_folder_path(self._workspace_root, name)
            project_dir = os.path.dirname(knxarr_path)
            if os.path.exists(knxarr_path):
                self._preview_label.setText(
                    f"Im Arbeitsverzeichnis existiert bereits ein Projekt '{os.path.basename(project_dir)}'. "
                    f"Bitte einen anderen Namen wählen."
                )
                self._preview_label.setStyleSheet("color: #B71C1C;")
                self._btn_create.setEnabled(False)
                return
            self._preview_label.setText(f"Projektordner: {project_dir}")
            self._preview_label.setStyleSheet("color: #757575;")

        self._btn_create.setEnabled(True)

    def _mode_changed(self, reconstruct: bool) -> None:
        """Aufnehmen: Gebäudetyp, Mittelgruppen-Variante und Wizard gelten
        nicht (die Adressen kommen aus der Anlage, das Gebäude wird erfasst)."""
        self._template_box.setEnabled(not reconstruct)
        self._variant_box.setEnabled(not reconstruct)
        self._start_wizard.setVisible(not reconstruct)

    @property
    def reconstruct(self) -> bool:
        return self._mode_reconstruct.isChecked()

    @property
    def project_name(self) -> str:
        return self._name.text().strip()

    @property
    def project_number(self) -> str:
        return self._number.text().strip()

    @property
    def template_key(self) -> str:
        if self.reconstruct:
            return "empty"
        btn = self._template_group.checkedButton()
        return btn.property("template_key") if btn else "empty"

    @property
    def start_wizard(self) -> bool:
        return self._start_wizard.isChecked() and not self.reconstruct

    @property
    def variant(self) -> str:
        return "B" if self._variant_b.isChecked() else "A"
