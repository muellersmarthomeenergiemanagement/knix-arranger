"""
Wizard Schritt 10: Export und Zusammenfassung
"""
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QFileDialog, QMessageBox, QTextEdit,
)
from PySide6.QtCore import Qt
from ...models.project import KnxProject
from ...services.csv_export_service import CsvExportService
from ..styles import KNX_GREEN
from ..export_worker import run_export


class Step10Export(QWidget):
    """Export und Zusammenfassung (FA-800)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._worker_ref: list = [None]  # GC-Schutz für laufenden Worker

        layout = QVBoxLayout(self)

        # Zusammenfassung
        summary_group = QGroupBox("Projektzusammenfassung")
        summary_layout = QGridLayout()
        self._labels = {}
        fields = [
            ("name", "Projekt:", 0, 0),
            ("floors", "Stockwerke:", 1, 0),
            ("rooms", "Räume:", 2, 0),
            ("variant", "MG-Variante:", 0, 2),
            ("gas", "Gruppenadressen:", 1, 2),
            ("lines", "Linien:", 2, 2),
        ]
        for key, text, row, col in fields:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-weight: bold;")
            val = QLabel("-")
            self._labels[key] = val
            summary_layout.addWidget(lbl, row, col)
            summary_layout.addWidget(val, row, col + 1)

        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)

        # ── ETS6-Import (funktioniert) ────────────────────────────────
        ets_group = QGroupBox("ETS6-Import (empfohlen)")
        ets_layout = QVBoxLayout()

        ets_hint = QLabel(
            "Gruppenadressen können direkt in ETS6 importiert werden:\n"
            "ETS6 → Topologie → Gerät → Gruppenadressen → Importieren → CSV wählen"
        )
        ets_hint.setStyleSheet("color: #555; font-size: 11px; padding: 2px 0 6px 0;")
        ets_hint.setWordWrap(True)
        ets_layout.addWidget(ets_hint)

        btn_csv = QPushButton("CSV für ETS6 exportieren  (Gruppenadressen)")
        btn_csv.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; "
            "font-weight: bold; padding: 5px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #388E3C; }"
        )
        btn_csv.setToolTip(
            "Exportiert alle Gruppenadressen als CSV.\n"
            "Import in ETS6: Gruppenadressen → Importieren → CSV wählen."
        )
        btn_csv.clicked.connect(self._export_csv)
        ets_layout.addWidget(btn_csv)

        btn_belegungsplan = QPushButton("ETS-Belegungsplan exportieren (.xlsx)")
        btn_belegungsplan.setToolTip(
            "Exportiert eine Excel-Tabelle mit den empfohlenen GA-Zuordnungen\n"
            "für Sensoren und Taster als Vorlage für die ETS-Programmierung."
        )
        btn_belegungsplan.clicked.connect(self._export_belegungsplan)
        ets_layout.addWidget(btn_belegungsplan)

        ets_group.setLayout(ets_layout)
        layout.addWidget(ets_group)

        # ── KNXPROJ-Archiv ────────────────────────────────────────────
        knxproj_group = QGroupBox("KNXPROJ-Archiv (für andere KNX-Tools / Dokumentation)")
        knxproj_layout = QVBoxLayout()

        knxproj_hint = QLabel(
            "Hinweis: ETS6 verlangt eine kryptographische Signatur, die nur ETS6 selbst\n"
            "erzeugen kann. Die exportierte Datei kann nicht direkt in ETS6 geöffnet werden,\n"
            "eignet sich aber als Archiv oder für andere KNX-kompatible Werkzeuge."
        )
        knxproj_hint.setStyleSheet("color: #888; font-size: 11px; padding: 2px 0 6px 0;")
        knxproj_hint.setWordWrap(True)
        knxproj_layout.addWidget(knxproj_hint)

        btn_knxproj = QPushButton("KNXPROJ exportieren (.knxproj)")
        btn_knxproj.setToolTip(
            "Enthält: Gruppenadressen, Topologie, Gebäudestruktur.\n"
            "Nicht direkt in ETS6 öffnbar (fehlende ETS6-Signatur).\n"
            "Geeignet für Archivierung und andere KNX-Werkzeuge."
        )
        btn_knxproj.clicked.connect(self._export_knxproj)
        knxproj_layout.addWidget(btn_knxproj)

        knxproj_group.setLayout(knxproj_layout)
        layout.addWidget(knxproj_group)

        # ── Projekt speichern ─────────────────────────────────────────
        btn_save = QPushButton("Projekt speichern (.knxarr)")
        btn_save.clicked.connect(self._save_project)
        layout.addWidget(btn_save)

        # Log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(150)
        layout.addWidget(self._log)

        layout.addStretch()

        # Erfolg-Label
        self._success = QLabel("")
        self._success.setAlignment(Qt.AlignCenter)
        self._success.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {KNX_GREEN}; padding: 15px;"
        )
        layout.addWidget(self._success)

    def on_enter(self):
        p = self._project
        self._labels["name"].setText(p.name or "-")
        self._labels["floors"].setText(str(len(p.all_floors)))
        self._labels["rooms"].setText(str(len(p.all_rooms)))
        self._labels["variant"].setText(p.config.mg_variant)
        self._labels["gas"].setText(str(len(p.group_addresses.all_addresses())))

        lines = sum(len(a.lines) for a in p.topology.areas)
        self._labels["lines"].setText(str(lines))

    # ── Export-Aktionen ───────────────────────────────────────────────

    def _default_dir(self, subdir: str = "Berichte") -> str:
        folder = self._project.folder_path
        if folder:
            candidate = os.path.join(folder, subdir)
            return candidate if os.path.isdir(candidate) else folder
        return ""

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV exportieren",
            os.path.join(self._default_dir(), f"{self._project.name or 'export'}.csv"),
            "CSV-Dateien (*.csv)",
        )
        if not path:
            return

        project = self._project

        def do_export():
            exporter = CsvExportService()
            exporter.export_csv(project.group_addresses, path, overwrite=True)
            return len(project.group_addresses.all_addresses())

        def on_success(ga_count: int):
            self._log.append(f"CSV exportiert: {ga_count} GAs → {path}")
            self._success.setText("CSV erfolgreich exportiert!")

        run_export(self, "Gruppenadressen werden exportiert…", do_export, on_success, self._worker_ref)

    def _export_belegungsplan(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "ETS-Belegungsplan exportieren",
            os.path.join(self._default_dir(), f"{self._project.name or 'Belegungsplan'}_ETS.xlsx"),
            "Excel-Dateien (*.xlsx)",
        )
        if not path:
            return

        project = self._project

        def do_export():
            from ...services.belegungsplan_service import BelegungsplanService
            from ...services.belegungsplan_export_service import BelegungsplanExportService
            data = BelegungsplanService().generate(project)
            BelegungsplanExportService().export_xlsx(data, path)
            return len(data.sensor_rows)

        def on_success(row_count: int):
            self._log.append(
                f"ETS-Belegungsplan exportiert: {row_count} Zeilen → {path}"
            )
            self._success.setText("ETS-Belegungsplan erfolgreich exportiert!")

        run_export(self, "ETS-Belegungsplan wird erstellt…", do_export, on_success, self._worker_ref)

    def _export_knxproj(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "KNXPROJ exportieren",
            os.path.join(self._default_dir(), f"{self._project.name or 'projekt'}.knxproj"),
            "ETS6-Projekt (*.knxproj)",
        )
        if not path:
            return

        project = self._project

        def do_export():
            from ...services.knxproj_export_service import KnxprojExportService
            return KnxprojExportService().export(project, path)

        def on_success(summary):
            self._log.append(f"KNXPROJ exportiert: {path}")
            self._success.setText("KNXPROJ exportiert (Archiv).")
            QMessageBox.information(
                self, "KNXPROJ exportiert",
                summary.as_text() + f"\n\nDatei: {path}",
            )

        run_export(self, "KNXPROJ-Archiv wird erstellt…", do_export, on_success, self._worker_ref)

    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Projekt speichern",
            os.path.join(self._default_dir(""), f"{self._project.name or 'projekt'}.knxarr"),
            "KNiX Arranger (*.knxarr)",
        )
        if not path:
            return

        try:
            self._project.save(path)
            self._log.append(f"Projekt gespeichert: {path}")
            self._success.setText("Projekt erfolgreich gespeichert!")
        except Exception as e:
            QMessageBox.critical(self, "Speicher-Fehler", str(e))
