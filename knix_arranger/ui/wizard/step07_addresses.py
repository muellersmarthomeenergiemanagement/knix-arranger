"""
Wizard Schritt 7: Gruppenadressen generieren
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QGroupBox, QTreeWidget,
    QTreeWidgetItem, QTextEdit, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QBrush, QColor, QFont

from ...models.project import KnxProject
from ...models.group_address import GroupAddress, MainGroup, MiddleGroup
from ...services.address_generator import AddressGenerator
from ...services.validation_engine import ValidationEngine
from ...services import ga_library_service
from ..dialogs.ga_edit_dialog import GaEditDialog
from ..dialogs.ga_library_dialog import GALibraryDialog
from ..column_utils import fit_columns

_MANUAL_COLOR = QColor("#1565C0")   # Blau für manuelle GAs


class Step07Addresses(QWidget):
    """Variante A/B wählen, GA generieren, manuell erweitern (FA-400)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project

        layout = QVBoxLayout(self)

        info = QLabel(
            "Generieren Sie die Gruppenadressen.\n"
            "Wählen Sie die Mittelgruppen-Variante und starten Sie die Generierung.\n"
            "Manuelle Ergänzungen (blau) bleiben bei erneuter Generierung erhalten."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Variante
        variant_group = QGroupBox("Mittelgruppen-Variante")
        variant_layout = QHBoxLayout()
        self._variant_group = QButtonGroup(self)
        self._variant_a = QRadioButton("Variante A (RM in gleicher MG)")
        self._variant_a.setToolTip(
            "Variante A – Rückmeldungs-GAs in derselben Mittelgruppe wie die Steuerbefehle.\n"
            "Beispiel: Licht-Steuerung (2/0/5) und Licht-Status (2/0/6) beide in MG 0.\n"
            "Empfohlen für: EFH und kleine Projekte (kompakte GA-Struktur, 5er-Blöcke)."
        )
        self._variant_b = QRadioButton("Variante B (RM in MG 6/7)")
        self._variant_b.setToolTip(
            "Variante B – Rückmeldungs-GAs in separaten Mittelgruppen 6 und 7.\n"
            "Beispiel: Licht-Steuerung (2/0/5) in MG 0, Licht-Status (2/6/5) in MG 6.\n"
            "Empfohlen für: MFH und größere Projekte (übersichtliche Trennung, 10er-Blöcke)."
        )
        self._variant_group.addButton(self._variant_a)
        self._variant_group.addButton(self._variant_b)
        self._variant_a.setChecked(True)
        variant_layout.addWidget(self._variant_a)
        variant_layout.addWidget(self._variant_b)
        variant_group.setLayout(variant_layout)
        layout.addWidget(variant_group)

        # Haupt-Buttons: Generieren + Validieren
        btn_layout = QHBoxLayout()
        self._btn_generate = QPushButton("Gruppenadressen generieren")
        self._btn_generate.setToolTip(
            "Generiert die vollständige GA-Struktur basierend auf Gebäude, Topologie und Gewerken.\n"
            "Bereits vorhandene manuelle GAs (blau) bleiben erhalten."
        )
        self._btn_generate.clicked.connect(self._generate)
        btn_layout.addWidget(self._btn_generate)

        self._btn_validate = QPushButton("Validieren")
        self._btn_validate.setObjectName("secondary")
        self._btn_validate.setToolTip(
            "Prüft die GA-Struktur auf Konformität mit den KNX Swiss Richtlinien.\n"
            "Findet doppelte Adressen, fehlende DPTs und Lücken in Blöcken."
        )
        self._btn_validate.clicked.connect(self._validate)
        btn_layout.addWidget(self._btn_validate)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Manuelle GA-Verwaltung
        manual_layout = QHBoxLayout()

        self._btn_add = QPushButton("+ Manuell hinzufügen")
        self._btn_add.setToolTip(
            "Fügt eine zusätzliche GA manuell hinzu (blau markiert).\n"
            "Manuelle GAs bleiben bei erneuter Generierung erhalten."
        )
        self._btn_add.clicked.connect(self._add_ga)
        manual_layout.addWidget(self._btn_add)

        self._btn_edit = QPushButton("Bearbeiten")
        self._btn_edit.setObjectName("secondary")
        self._btn_edit.setEnabled(False)
        self._btn_edit.clicked.connect(self._edit_ga)
        manual_layout.addWidget(self._btn_edit)

        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("secondary")
        self._btn_remove.setEnabled(False)
        self._btn_remove.clicked.connect(self._remove_ga)
        manual_layout.addWidget(self._btn_remove)

        manual_layout.addSpacing(20)

        self._btn_from_library = QPushButton("Aus Vorlagen einfügen")
        self._btn_from_library.setObjectName("secondary")
        self._btn_from_library.clicked.connect(self._insert_from_library)
        manual_layout.addWidget(self._btn_from_library)

        self._btn_save_template = QPushButton("Als Vorlage speichern")
        self._btn_save_template.setObjectName("secondary")
        self._btn_save_template.setEnabled(False)
        self._btn_save_template.clicked.connect(self._save_to_library)
        manual_layout.addWidget(self._btn_save_template)

        manual_layout.addStretch()
        layout.addLayout(manual_layout)

        # Summary
        self._summary = QLabel("")
        self._summary.setObjectName("subtitle")
        layout.addWidget(self._summary)

        # Vorschau
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels(["Adresse", "Bezeichnung", "DPT", "Gewerk"])
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.installEventFilter(self)
        layout.addWidget(self._tree)

        # Log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(100)
        layout.addWidget(self._log)

    def eventFilter(self, obj, event):
        if obj is self._tree and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Delete:
                self._remove_ga()
                return True
            if key == Qt.Key.Key_F2 or key == Qt.Key.Key_Return:
                self._edit_ga()
                return True
        return super().eventFilter(obj, event)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def on_enter(self):
        if self._project.config.mg_variant == "B":
            self._variant_b.setChecked(True)
        else:
            self._variant_a.setChecked(True)

        # Automatisch (neu) generieren wenn Gewerk-Zuweisungen vorhanden –
        # analog zu Step06 (Aktoren) und Step08 (Sensoren).
        has_gewerke = any(r.gewerk_assignments for r in self._project.all_rooms)
        if has_gewerke:
            self._generate()
        elif self._project.group_addresses.main_groups:
            self._display_preview(self._project.group_addresses)
            self._update_summary()

    # ── Haupt-Aktionen ─────────────────────────────────────────────────────

    def _generate(self):
        variant = "B" if self._variant_b.isChecked() else "A"
        self._project.config.mg_variant = variant

        # Manuell hinzugefügte GAs sichern
        manual_gas = [
            ga for ga in self._project.group_addresses.all_addresses()
            if ga.is_manual
        ]

        catalog = self._project.gewerk_catalog
        gen = AddressGenerator(catalog, variant=variant)
        structure = gen.generate(self._project.areal, scenes=self._project.scenes)
        self._project.group_addresses = structure

        # Manuelle GAs wieder einfügen
        for ga in manual_gas:
            self._insert_ga_into_structure(ga)

        self._display_preview(structure)
        self._update_summary()

        self._log.clear()
        ga_count = len(structure.all_addresses())
        self._log.append(f"Generierung abgeschlossen: {ga_count} GAs")
        if manual_gas:
            self._log.append(f"{len(manual_gas)} manuelle GA(s) beibehalten.")

    def _validate(self):
        if not self._project.group_addresses.main_groups:
            self._log.append("Keine Gruppenadressen vorhanden. Bitte zuerst generieren.")
            return

        validator = ValidationEngine(self._project.gewerk_catalog)
        issues = validator.validate(self._project.group_addresses)

        _LEVEL_COLOR = {
            "error":   "#c62828",
            "warning": "#e65100",
            "info":    "#1565c0",
        }
        _LEVEL_LABEL = {
            "error":   "FEHLER",
            "warning": "WARNUNG",
            "info":    "INFO",
        }

        lines: list[str] = []
        if not issues:
            lines.append('<span style="color:#2e7d32;font-weight:bold;">✓ Validierung OK – keine Probleme gefunden.</span>')
        else:
            errors   = [i for i in issues if i.level == "error"]
            warnings = [i for i in issues if i.level == "warning"]
            infos    = [i for i in issues if i.level == "info"]
            summary_parts = []
            if errors:
                summary_parts.append(f'<b style="color:#c62828">{len(errors)} Fehler</b>')
            if warnings:
                summary_parts.append(f'<b style="color:#e65100">{len(warnings)} Warnungen</b>')
            if infos:
                summary_parts.append(f'<b style="color:#1565c0">{len(infos)} Hinweise</b>')
            lines.append("Validierungsergebnis: " + ", ".join(summary_parts))
            lines.append("")

            for issue in issues:
                color = _LEVEL_COLOR.get(issue.level, "#333")
                label = _LEVEL_LABEL.get(issue.level, issue.level.upper())
                lines.append(
                    f'<span style="color:{color};font-weight:bold;">[{label}]</span> '
                    f'<span style="color:#555;">{issue.rule_id}</span> – {issue.message}'
                )
                if issue.address:
                    lines.append(
                        f'&nbsp;&nbsp;&nbsp;→ <b>Betroffene Adresse:</b> '
                        f'<tt>{issue.address}</tt>'
                    )
                if issue.suggestion:
                    lines.append(
                        f'&nbsp;&nbsp;&nbsp;→ <b>Abhilfe:</b> {issue.suggestion}'
                    )

        self._log.setHtml("<br>".join(lines))

        # GA-Bedarf-Validierung gegen KNXPROD-ComObjects
        self._validate_ga_vs_comobjects()

    # ── Manuelle GA-Verwaltung ──────────────────────────────────────────────

    def _add_ga(self):
        """Öffnet Dialog zum manuellen Hinzufügen einer neuen GA."""
        hg_default, mg_default, ug_default = self._default_address_from_selection()
        new_ga = GroupAddress(
            main_group=hg_default,
            middle_group=mg_default,
            sub_group=ug_default,
            is_manual=True,
        )
        dlg = GaEditDialog(new_ga, self)
        dlg.setWindowTitle("Neue GA manuell hinzufügen")
        if dlg.exec():
            new_ga.is_manual = True  # sicherstellen nach Dialog
            self._insert_ga_into_structure(new_ga)
            self._display_preview(self._project.group_addresses)
            self._update_summary()
            self._log.append(f"Hinzugefügt: {new_ga.address} – {new_ga.designation}")

    def _edit_ga(self):
        """Öffnet Bearbeitungsdialog für die ausgewählte GA."""
        ga = self._selected_ga()
        if not ga:
            return
        dlg = GaEditDialog(ga, self)
        if dlg.exec():
            self._display_preview(self._project.group_addresses)

    def _remove_ga(self):
        """Entfernt eine manuell hinzugefügte GA."""
        ga = self._selected_ga()
        if not ga:
            return
        if not ga.is_manual:
            QMessageBox.information(
                self, "Hinweis",
                "Nur manuell hinzugefügte GAs (blau) können hier entfernt werden.\n"
                "Automatisch generierte GAs werden durch erneutes Generieren aktualisiert.",
            )
            return
        structure = self._project.group_addresses
        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                mg.group_addresses = [g for g in mg.group_addresses if g.id != ga.id]
        self._display_preview(structure)
        self._update_summary()
        self._log.append(f"Entfernt: {ga.address} – {ga.designation}")

    def _save_to_library(self):
        """Speichert die ausgewählte GA als projektübergreifende Vorlage."""
        ga = self._selected_ga()
        if not ga:
            return
        default_name = ga.designation or ga.address
        name, ok = QInputDialog.getText(
            self, "Vorlage speichern", "Name der Vorlage:", text=default_name,
        )
        if ok and name.strip():
            ga_library_service.add_entry(name.strip(), ga)
            self._log.append(f"Vorlage gespeichert: \"{name.strip()}\"")

    def _insert_from_library(self):
        """Öffnet die Vorlagen-Bibliothek und fügt ausgewählte GAs ein."""
        entries = ga_library_service.load_library()
        if not entries:
            QMessageBox.information(
                self, "Vorlagen-Bibliothek",
                "Keine Vorlagen vorhanden.\n"
                "Wählen Sie eine GA aus und klicken Sie \"Als Vorlage speichern\".",
            )
            return
        dlg = GALibraryDialog(entries, self)
        if dlg.exec() and dlg.selected_entries:
            hg_default, mg_default, _ = self._default_address_from_selection()
            for entry in dlg.selected_entries:
                new_ga = GroupAddress(
                    main_group=entry.get("main_group", hg_default),
                    middle_group=entry.get("middle_group", mg_default),
                    sub_group=entry.get("sub_group", 0),
                    designation=entry.get("designation", ""),
                    datapoint_type=entry.get("datapoint_type", ""),
                    gewerk_code=entry.get("gewerk_code", ""),
                    function_name=entry.get("function_name", ""),
                    description=entry.get("description", ""),
                    central=entry.get("central", ""),
                    is_manual=True,
                )
                self._insert_ga_into_structure(new_ga)
            self._display_preview(self._project.group_addresses)
            self._update_summary()
            self._log.append(
                f"{len(dlg.selected_entries)} Vorlage(n) eingefügt."
            )

    def _validate_ga_vs_comobjects(self):
        """
        Vergleicht generierte GA-Anzahl mit dem erwarteten GA-Bedarf aus KNXPROD-ComObjects.
        Zeigt Warnungen wenn Geräte mit ComObject-Daten vorhanden sind.
        """
        # Geräte mit ComObjects aus der Topologie sammeln
        devices_with_cos = []
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.communication_objects:
                        devices_with_cos.append(device)

        if not devices_with_cos:
            return  # Keine KNXPROD-Daten vorhanden → keine Prüfung

        # GA-Bedarf schätzen (über alle Devices mit ComObjects)
        total_ga_min = 0
        total_ga_max = 0
        for device in devices_with_cos:
            for co in device.communication_objects:
                flags = co.flags or ""
                if "K" in flags and any(f in flags for f in ("Ü", "S")):
                    total_ga_min += 1
                if "K" in flags and any(f in flags for f in ("Ü", "S", "L", "U")):
                    total_ga_max += 1

        total_generated = len(self._project.group_addresses.all_addresses())
        n_devices = len(devices_with_cos)

        lines = [
            "",
            f"<b>[GA-KNXPROD]</b> {n_devices} Gerät(e) mit ComObject-Daten:",
            f"&nbsp;&nbsp;Erwarteter GA-Bedarf: {total_ga_min} (Min.) – {total_ga_max} (Max.)",
            f"&nbsp;&nbsp;Generierte GAs: {total_generated}",
        ]

        if total_generated < total_ga_min:
            lines.append(
                f'<span style="color:#e65100;font-weight:bold;">[WARNUNG]</span> '
                f"Generierte GAs ({total_generated}) &lt; Mindestbedarf ({total_ga_min}).<br>"
                f"&nbsp;&nbsp;→ <b>Abhilfe:</b> Prüfen Sie ob alle Gewerke vollständig zugewiesen sind."
            )
        elif total_generated > total_ga_max and total_ga_max > 0:
            lines.append(
                f'<span style="color:#1565c0;">[HINWEIS]</span> '
                f"Generierte GAs ({total_generated}) &gt; ComObject-Kapazität ({total_ga_max}).<br>"
                f"&nbsp;&nbsp;→ Reservierte oder ungenutzte GAs können entfernt werden."
            )
        else:
            lines.append('<span style="color:#2e7d32;">[GA-KNXPROD]</span> GA-Anzahl im erwarteten Bereich. ✓')

        # HTML an bestehenden Inhalt anhängen
        cursor = self._log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._log.setTextCursor(cursor)
        self._log.insertHtml("<br>" + "<br>".join(lines))

    # ── Hilfsmethoden ──────────────────────────────────────────────────────

    def _insert_ga_into_structure(self, ga: GroupAddress) -> None:
        """Fügt eine GA in die passende HG/MG der Struktur ein (legt sie an falls nötig)."""
        structure = self._project.group_addresses

        hg = next((h for h in structure.main_groups if h.number == ga.main_group), None)
        if not hg:
            hg = MainGroup(number=ga.main_group, name=f"HG {ga.main_group}")
            structure.main_groups.append(hg)
            structure.main_groups.sort(key=lambda h: h.number)

        mg = next((m for m in hg.middle_groups if m.number == ga.middle_group), None)
        if not mg:
            mg = MiddleGroup(number=ga.middle_group, name=f"MG {ga.middle_group}")
            hg.middle_groups.append(mg)
            hg.middle_groups.sort(key=lambda m: m.number)

        mg.group_addresses.append(ga)

    def _selected_ga(self) -> GroupAddress | None:
        """Gibt das GA-Objekt der aktuell ausgewählten Tree-Zeile zurück."""
        items = self._tree.selectedItems()
        if not items:
            return None
        data = items[0].data(0, Qt.UserRole)
        return data if isinstance(data, GroupAddress) else None

    def _default_address_from_selection(self) -> tuple[int, int, int]:
        """Leitet HG/MG/nächste-UG aus der Baumauswahl ab."""
        items = self._tree.selectedItems()
        if not items:
            return 1, 0, 1
        data = items[0].data(0, Qt.UserRole)
        if isinstance(data, GroupAddress):
            return data.main_group, data.middle_group, data.sub_group + 1
        if isinstance(data, tuple) and data[0] == "mg":
            hg_n, mg_n = data[1], data[2]
            structure = self._project.group_addresses
            hg = next((h for h in structure.main_groups if h.number == hg_n), None)
            if hg:
                mg_obj = next((m for m in hg.middle_groups if m.number == mg_n), None)
                if mg_obj and mg_obj.group_addresses:
                    return hg_n, mg_n, max(g.sub_group for g in mg_obj.group_addresses) + 1
            return hg_n, mg_n, 1
        if isinstance(data, tuple) and data[0] == "hg":
            return data[1], 0, 1
        return 1, 0, 1

    def _update_summary(self):
        structure = self._project.group_addresses
        all_gas = structure.all_addresses()
        manual_count = sum(1 for g in all_gas if g.is_manual)
        text = f"Variante {structure.variant}: {len(all_gas)} Gruppenadressen"
        if manual_count:
            text += f" ({manual_count} manuell)"
        self._summary.setText(text)

    # ── Tree-Interaktion ───────────────────────────────────────────────────

    def _on_selection_changed(self):
        ga = self._selected_ga()
        has_ga = ga is not None
        self._btn_edit.setEnabled(has_ga)
        self._btn_remove.setEnabled(has_ga and ga.is_manual)
        self._btn_save_template.setEnabled(has_ga)

    def _on_double_click(self, item, _column):
        ga = item.data(0, Qt.UserRole)
        if isinstance(ga, GroupAddress):
            dlg = GaEditDialog(ga, self)
            if dlg.exec():
                self._display_preview(self._project.group_addresses)

    def _display_preview(self, structure):
        self._tree.clear()
        italic_font = QFont()
        italic_font.setItalic(True)
        manual_brush = QBrush(_MANUAL_COLOR)

        for hg in sorted(structure.main_groups, key=lambda m: m.number):
            hg_item = QTreeWidgetItem(self._tree, [
                f"HG {hg.number}", hg.name, "", "",
            ])
            hg_item.setData(0, Qt.UserRole, ("hg", hg.number))
            hg_item.setExpanded(hg.number <= 2)

            for mg in sorted(hg.middle_groups, key=lambda m: m.number):
                mg_item = QTreeWidgetItem(hg_item, [
                    f"MG {mg.number}", mg.name,
                    f"{len(mg.group_addresses)} GAs", "",
                ])
                mg_item.setData(0, Qt.UserRole, ("mg", hg.number, mg.number))

                for ga in sorted(mg.group_addresses, key=lambda g: g.sub_group):
                    ga_item = QTreeWidgetItem(mg_item, [
                        ga.address,
                        ga.designation if not ga.is_placeholder else "(Reserve)",
                        ga.datapoint_type,
                        ga.gewerk_code,
                    ])
                    ga_item.setData(0, Qt.UserRole, ga)
                    if ga.is_manual:
                        for col in range(self._tree.columnCount()):
                            ga_item.setForeground(col, manual_brush)
                        ga_item.setFont(1, italic_font)

        fit_columns(self._tree)
