"""
Projekteigenschaften bearbeiten
Ermöglicht die nachträgliche Bearbeitung aller Projekt-Metadaten.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QComboBox, QPushButton, QRadioButton,
    QButtonGroup, QCheckBox, QMessageBox, QSpinBox,
)
from PySide6.QtCore import Qt
from ..styles import KNX_GREEN, KNX_DARK_GREEN, KNX_PRIMARY
from ...models.project import KnxProject
from ...services.scene_numbering import scene_range_problem


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
        # Umbrechender Text im Formular: ohne Mindestbreite rechnet Qt die
        # Höhe für eine zu schmale Spalte, der Text wurde abgeschnitten
        kind_lbl.setMinimumWidth(380)
        form.addRow("Projektart:", kind_lbl)

        # Projektstatus (nur geplante Projekte): Adressen in die ETS übertragen
        self._ets_check = None
        if not project.topology.is_imported:
            since = f" (seit {project.ets_transferred})" if project.ets_transferred else ""
            self._ets_check = QCheckBox(f"Gruppenadressen in die ETS übertragen{since}")
            self._ets_check.setChecked(bool(project.ets_transferred))
            self._ets_check.setToolTip(
                "Ab der Übertragung stehen die Adressen fest: «Adressen neu ordnen» "
                "ist gesperrt. Zurücksetzen nur, solange in der ETS noch nichts "
                "verknüpft ist.")
            form.addRow("Status:", self._ets_check)

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

        # ── Szenennummern je Ebene (FA-1814) ──
        from ...services.scene_numbering import LEVEL_LABELS, scene_ranges
        scene_group = QGroupBox("Szenennummern")
        scene_form = QFormLayout()
        scene_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hint = QLabel("Getrennte Bereiche je Ebene: ein Aktor unterscheidet nicht, "
                      "über welche Szenen-Adresse eine Nummer kommt.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        scene_form.addRow(hint)
        self._scene_ranges: dict[str, tuple[QSpinBox, QSpinBox]] = {}
        for level, (first, last) in scene_ranges(project).items():
            row = QHBoxLayout()
            spin_from, spin_to = QSpinBox(), QSpinBox()
            for spin, value in ((spin_from, first), (spin_to, last)):
                spin.setRange(1, 64)
                spin.setValue(value)
                spin.setFixedWidth(80)
            row.addWidget(spin_from)
            row.addWidget(QLabel("bis"))
            row.addWidget(spin_to)
            row.addStretch()
            scene_form.addRow(f"{LEVEL_LABELS[level]}:", row)
            self._scene_ranges[level] = (spin_from, spin_to)
        scene_group.setLayout(scene_form)
        layout.addWidget(scene_group)

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
        # Mit der Gruppe Szenennummern ist der Inhalt höher als die Mindestgrösse
        self.resize(max(self.width(), 520), self.sizeHint().height())

    # ------------------------------------------------------------------

    def _apply(self):
        """Schreibt alle Änderungen ins Projekt-Objekt."""
        ranges = {level: (a.value(), b.value()) for level, (a, b) in self._scene_ranges.items()}
        problem = scene_range_problem(ranges)
        if problem:
            QMessageBox.warning(self, "Szenennummern", problem)
            return
        name = self._name_edit.text().strip()
        if name:
            self._project.name = name

        self._project.project_number = self._number_edit.text().strip()
        self._project.config.mg_variant = "B" if self._radio_b.isChecked() else "A"
        self._project.config.topology_mode = self._topo_combo.currentText()
        self._project.config.backbone_type = self._backbone_combo.currentText()
        from ...services.scene_numbering import DEFAULT_RANGES
        # Nur Abweichungen von der Vorgabe speichern
        self._project.config.scene_number_ranges = {
            level: list(r) for level, r in ranges.items() if r != DEFAULT_RANGES[level]}
        if self._ets_check is not None:
            from ...services.renumber_service import mark_ets_transferred
            if (not self._ets_check.isChecked() and self._project.ets_transferred
                    and QMessageBox.question(
                        self, "Status zurücksetzen",
                        "Status «in ETS übertragen» zurücksetzen?\n\nNur sinnvoll, "
                        "solange in der ETS noch keine Gruppenadressen verknüpft sind – "
                        "danach dürfen sich die Adressen wieder verschieben.",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes):
                return
            mark_ets_transferred(self._project, self._ets_check.isChecked())
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


def offer_ets_transferred(parent, project) -> bool:
    """Nach dem GA-Export für die ETS: Projektstatus «in ETS übertragen»
    anbieten (nur geplante Projekte, noch nicht übertragen). True, wenn
    gesetzt."""
    if project is None or project.addresses_fixed:
        return False
    answer = QMessageBox.question(
        parent, "In die ETS übertragen?",
        "Werden diese Gruppenadressen jetzt in die ETS importiert?\n\n"
        "Dann das Projekt als «in ETS übertragen» markieren: KNiX verschiebt ab "
        "jetzt keine Adressen mehr («Adressen neu ordnen» gesperrt). Zurücksetzen "
        "unter Datei → Projekteigenschaften.",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    if answer != QMessageBox.Yes:
        return False
    from ...services.renumber_service import mark_ets_transferred
    mark_ets_transferred(project, True)
    return True
