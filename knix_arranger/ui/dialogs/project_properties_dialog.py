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
from ..styles import KNX_GREEN, KNX_DARK_GREEN, KNX_PRIMARY
from ...models.project import KnxProject


class ProjectPropertiesDialog(QDialog):
    """Dialog zum Bearbeiten aller Projekteigenschaften."""

    def __init__(self, project: KnxProject, parent=None, bus=None):
        super().__init__(parent)
        self._project = project
        self._bus = bus
        self.setWindowTitle("Projekteigenschaften")
        self.setMinimumSize(480, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Titel
        title_lbl = QLabel("Projekteigenschaften bearbeiten")
        title_lbl.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {KNX_DARK_GREEN};"
        )
        layout.addWidget(title_lbl)

        # ── Allgemeine Angaben ──
        general_group = QGroupBox("Allgemeine Angaben")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._name_edit = QLineEdit(project.name)
        self._name_edit.setPlaceholderText("z.B. Neubau EFH Müller")
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

        # Projektart: bestimmt, wie streng die Projektrichtlinien gelten
        if project.topology.is_imported:
            kind = ("<b>Aus der ETS importiert</b> – die ETS bleibt massgebend. "
                    "KNiX dokumentiert; Abweichungen von den Projektrichtlinien "
                    "werden als Hinweis gezeigt, Korrekturen nur in KNiX gespeichert.")
        else:
            kind = ("<b>Mit KNiX geplant</b> – die Projektrichtlinien gelten "
                    "verbindlich; Abweichungen meldet die Validierung als Fehler.")
        kind_lbl = QLabel(kind)
        kind_lbl.setWordWrap(True)
        kind_lbl.setTextFormat(Qt.RichText)
        form.addRow("Projektart:", kind_lbl)

        general_group.setLayout(form)
        layout.addWidget(general_group)

        # ── Kunde / Bauherr (Kundenprofil: Offerte, Anleitung, Berichtsköpfe) ──
        client_group = QGroupBox("Kunde / Bauherr")
        client_row = QHBoxLayout()
        self._client_summary = QLabel()
        self._client_summary.setWordWrap(True)
        self._client_summary.setTextFormat(Qt.RichText)
        client_row.addWidget(self._client_summary, 1)
        btn_client = QPushButton("Kundenprofil bearbeiten…")
        btn_client.setToolTip("Name, Objekt- und Postadresse, Anrede, Kontakt und Foto. "
                              "Wird für Kundenofferte, Bedienungsanleitung und Berichte verwendet.")
        btn_client.clicked.connect(self._edit_client)
        client_row.addWidget(btn_client)
        client_group.setLayout(client_row)
        layout.addWidget(client_group)
        self._update_client_summary()

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
            f"background-color: {KNX_PRIMARY}; color: white; "
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

    def _update_client_summary(self) -> None:
        cp = self._project.client_profile
        parts = [f"<b>{cp.name}</b>" if cp.name else ""]
        if cp.object_address:
            parts.append(f"Objekt: {cp.object_address}")
        if cp.contact_address:
            parts.append(f"Post: {cp.contact_address}")
        text = "<br>".join(p for p in parts if p)
        self._client_summary.setText(
            text or "<i>Noch kein Kundenprofil erfasst.</i>")

    def _edit_client(self) -> None:
        from .client_profile_dialog import edit_client_profile
        if edit_client_profile(self._project, self, self._bus):
            self._update_client_summary()
