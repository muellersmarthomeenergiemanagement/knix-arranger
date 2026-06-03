"""
Projekteigenschaften bearbeiten
Ermöglicht die nachträgliche Bearbeitung aller Projekt-Metadaten.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QComboBox, QPushButton, QRadioButton,
    QButtonGroup,
)
from PySide6.QtCore import Qt
from ..styles import KNX_GREEN, KNX_DARK_GREEN
from ...models.project import KnxProject


class ProjectPropertiesDialog(QDialog):
    """Dialog zum Bearbeiten aller Projekteigenschaften."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self.setWindowTitle("Projekteigenschaften")
        self.setMinimumSize(480, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Titel
        title_lbl = QLabel("Projekteigenschaften bearbeiten")
        title_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {KNX_DARK_GREEN};"
        )
        layout.addWidget(title_lbl)

        # ── Allgemeine Angaben ──
        general_group = QGroupBox("Allgemeine Angaben")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._name_edit = QLineEdit(project.name)
        self._name_edit.setPlaceholderText("z.B. Neubau EFH Mueller")
        form.addRow("Projektname:", self._name_edit)

        self._number_edit = QLineEdit(project.project_number)
        self._number_edit.setPlaceholderText("z.B. 2024-001")
        form.addRow("Projektnummer:", self._number_edit)

        # Erstellt / Geändert (nur lesen)
        created_lbl = QLabel(project.created or "-")
        created_lbl.setStyleSheet("color: #666;")
        form.addRow("Erstellt:", created_lbl)

        modified_lbl = QLabel(project.modified or "-")
        modified_lbl.setStyleSheet("color: #666;")
        form.addRow("Zuletzt geändert:", modified_lbl)

        general_group.setLayout(form)
        layout.addWidget(general_group)

        # ── Konfiguration ──
        config_group = QGroupBox("Projektkonfiguration")
        config_layout = QVBoxLayout()

        # MG-Variante
        variant_form = QFormLayout()
        variant_form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        variant_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        variant_row = QHBoxLayout()
        self._variant_group = QButtonGroup(self)
        self._radio_a = QRadioButton("Variante A  –  Rückmeldungen in gleicher MG (Standard)")
        self._radio_b = QRadioButton("Variante B  –  Rückmeldungen in MG 6/7 (separate)")
        self._variant_group.addButton(self._radio_a)
        self._variant_group.addButton(self._radio_b)
        if project.config.mg_variant == "B":
            self._radio_b.setChecked(True)
        else:
            self._radio_a.setChecked(True)
        variant_col = QVBoxLayout()
        variant_col.setSpacing(4)
        variant_col.addWidget(self._radio_a)
        variant_col.addWidget(self._radio_b)
        variant_form.addRow("MG-Variante:", variant_col)
        config_layout.addLayout(variant_form)

        # Topologie-Modus & Backbone
        topo_form = QFormLayout()
        topo_form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        topo_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        topo_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._topo_combo = QComboBox()
        self._topo_combo.addItems(["TP-256", "TP-64"])
        idx = self._topo_combo.findText(project.config.topology_mode)
        self._topo_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._topo_combo.setToolTip(
            "TP-256: bis zu 256 Teilnehmer pro Linie (Standard)\n"
            "TP-64: bis zu 64 Teilnehmer pro Linie (Kleinprojekt)"
        )
        topo_form.addRow("Topologie-Modus:", self._topo_combo)

        self._backbone_combo = QComboBox()
        self._backbone_combo.addItems(["TP", "IP"])
        bidx = self._backbone_combo.findText(project.config.backbone_type)
        self._backbone_combo.setCurrentIndex(bidx if bidx >= 0 else 0)
        self._backbone_combo.setToolTip(
            "TP: Twisted-Pair-Backbone (Standard)\n"
            "IP: IP-Backbone (KNXnet/IP)"
        )
        topo_form.addRow("Backbone-Typ:", self._backbone_combo)

        config_layout.addLayout(topo_form)
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        layout.addStretch()

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("Übernehmen")
        btn_ok.setStyleSheet(
            f"background-color: {KNX_GREEN}; color: white; "
            f"font-weight: bold; padding: 6px 20px;"
        )
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._apply)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------

    def _apply(self):
        """Schreibt alle Änderungen ins Projekt-Objekt."""
        name = self._name_edit.text().strip()
        if name:
            self._project.name = name

        self._project.project_number = self._number_edit.text().strip()
        self._project.config.mg_variant = "B" if self._radio_b.isChecked() else "A"
        self._project.config.topology_mode = self._topo_combo.currentText()
        self._project.config.backbone_type = self._backbone_combo.currentText()
        self.accept()
