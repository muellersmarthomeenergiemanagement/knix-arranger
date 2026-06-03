"""
Berichte-Dialog (FA-050)
Ermöglicht die Erzeugung verschiedener Projektberichte.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QFileDialog, QMessageBox, QTextEdit,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from ..styles import KNX_GREEN, KNX_DARK_GREEN
from ..export_worker import run_export
from ...models.project import KnxProject


class ReportsDialog(QDialog):
    """Dialog zur Erzeugung von Projektberichten."""

    def __init__(self, project: KnxProject, parent=None, company_profile=None):
        super().__init__(parent)
        self._project = project
        self._company_profile = company_profile
        self._worker_ref: list = [None]  # GC-Schutz für laufenden Worker
        self.setWindowTitle("Berichte erstellen")
        self.setMinimumSize(520, 580)

        layout = QVBoxLayout(self)

        # Titel
        title = QLabel("Berichte und Dokumentation")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {KNX_DARK_GREEN}; "
            f"padding: 10px;"
        )
        layout.addWidget(title)

        # Kundenprofil-Box
        client_group = QGroupBox("Kundenprofil")
        client_layout = QHBoxLayout()

        self._client_summary = QLabel(self._client_summary_text())
        self._client_summary.setStyleSheet("color: #444; padding: 4px;")
        self._client_summary.setWordWrap(True)
        client_layout.addWidget(self._client_summary, 1)

        btn_edit_client = QPushButton("Kundenprofil bearbeiten…")
        btn_edit_client.setMinimumWidth(180)
        btn_edit_client.clicked.connect(self._edit_client_profile)
        client_layout.addWidget(btn_edit_client)

        client_group.setLayout(client_layout)
        layout.addWidget(client_group)

        # Berichte-Gruppe
        reports_group = QGroupBox("Berichte")
        reports_layout = QGridLayout()

        buttons = [
            ("Validierungsbericht", "Prüfergebnis aller GA-Regeln als PDF",
             self._gen_validation),
            ("GA-Übersicht", "Alle Gruppenadressen mit Details als PDF",
             self._gen_ga_report),
            ("Projektzusammenfassung", "Kompakte Übersicht aller Projektdaten",
             self._gen_summary),
            ("Topologie-Bericht", "Bereiche, Linien und Geräte als PDF",
             self._gen_topology),
            ("Bedienelemente", "Taster/Sensoren mit GA-Zuordnung als PDF",
             self._gen_bedienelemente),
        ]

        for i, (title_text, desc, callback) in enumerate(buttons):
            btn = QPushButton(title_text)
            btn.setMinimumHeight(35)
            btn.clicked.connect(callback)
            lbl = QLabel(desc)
            lbl.setStyleSheet("color: #666;")
            reports_layout.addWidget(btn, i, 0)
            reports_layout.addWidget(lbl, i, 1)

        reports_group.setLayout(reports_layout)
        layout.addWidget(reports_group)

        # Dokumentation-Gruppe
        doc_group = QGroupBox("Dokumentation")
        doc_layout = QGridLayout()

        doc_buttons = [
            ("Inbetriebnahme-Checkliste", "Prüfpunkte pro Raum (PDF)",
             self._gen_checklists_pdf),
            ("Checkliste (Excel)", "Prüfpunkte pro Raum als Excel",
             self._gen_checklists_excel),
            ("Abnahmeprotokoll", "Formelles Abnahmedokument (PDF)",
             self._gen_acceptance),
            ("Bedienungsanleitung", "Raumweise Anleitung für Bauherren",
             self._gen_manual),
            ("Bauherr-Formular", "Funktionsdefinition als Excel",
             self._gen_bauherr_form),
            ("Revisionspaket", "Komplettes Dokumentationspaket",
             self._gen_revision),
        ]

        for i, (title_text, desc, callback) in enumerate(doc_buttons):
            btn = QPushButton(title_text)
            btn.setMinimumHeight(35)
            btn.clicked.connect(callback)
            lbl = QLabel(desc)
            lbl.setStyleSheet("color: #666;")
            doc_layout.addWidget(btn, i, 0)
            doc_layout.addWidget(lbl, i, 1)

        doc_group.setLayout(doc_layout)
        layout.addWidget(doc_group)

        # Log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText("Berichte-Log...")
        layout.addWidget(self._log)

        # Schliessen
        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    # ── Hilfsmethoden ─────────────────────────────────────────────────

    def _log_msg(self, msg: str):
        self._log.append(msg)

    def _client_summary_text(self) -> str:
        """Kurzübersicht des Kundenprofils."""
        cp = self._project.client_profile
        parts = []
        if cp.name:
            parts.append(f"<b>{cp.name}</b>")
        if cp.object_address:
            parts.append(f"Objekt: {cp.object_address}")
        if cp.phone or cp.email:
            contact = "  |  ".join(p for p in [cp.phone, cp.email] if p)
            parts.append(contact)
        if not parts:
            return "<i>Noch kein Kundenprofil hinterlegt.</i>"
        return "  ·  ".join(parts)

    def _edit_client_profile(self):
        """Öffnet den Kundenprofil-Dialog."""
        from .client_profile_dialog import ClientProfileDialog
        dlg = ClientProfileDialog(self._project.client_profile, parent=self)
        if dlg.exec():
            self._project.client_profile = dlg.get_profile()
            cp = self._project.client_profile
            self._project.project_info.client_name = cp.name
            self._project.project_info.project_address = cp.object_address
            self._client_summary.setText(self._client_summary_text())

    def _run(self, label: str, fn, log_msg: str):
        """Wrapper: führt fn() im Hintergrund aus, loggt bei Erfolg."""
        def on_success(_result):
            self._log_msg(log_msg)

        run_export(self, label, fn, on_success, self._worker_ref)

    # ── Berichte ──────────────────────────────────────────────────────

    def _gen_validation(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Validierungsbericht speichern",
            f"{self._project.name}_Validierung.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project = self._project
        company = self._company_profile

        def do():
            from ...services.report_service import ReportService
            svc = ReportService(project, company_profile=company)
            return svc.generate_validation_report(path)

        def on_success(issues):
            self._log_msg(f"Validierungsbericht erstellt: {path} ({len(issues)} Probleme)")

        run_export(self, "Validierungsbericht wird erstellt…", do, on_success, self._worker_ref)

    def _gen_ga_report(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "GA-Übersicht speichern",
            f"{self._project.name}_GA_Übersicht.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project, company = self._project, self._company_profile

        def do():
            from ...services.report_service import ReportService
            ReportService(project, company_profile=company).generate_ga_report(path)

        self._run("GA-Übersicht wird erstellt…", do, f"GA-Übersicht erstellt: {path}")

    def _gen_summary(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Projektzusammenfassung speichern",
            f"{self._project.name}_Zusammenfassung.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project, company = self._project, self._company_profile

        def do():
            from ...services.report_service import ReportService
            ReportService(project, company_profile=company).generate_project_summary(path)

        self._run("Projektzusammenfassung wird erstellt…", do, f"Projektzusammenfassung erstellt: {path}")

    def _gen_topology(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Topologie-Bericht speichern",
            f"{self._project.name}_Topologie.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project, company = self._project, self._company_profile

        def do():
            from ...services.report_service import ReportService
            ReportService(project, company_profile=company).generate_topology_report(path)

        self._run("Topologie-Bericht wird erstellt…", do, f"Topologie-Bericht erstellt: {path}")

    def _gen_checklists_pdf(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Checklisten speichern",
            f"{self._project.name}_Checklisten.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project = self._project

        def do():
            from ...services.documentation_service import DocumentationService
            DocumentationService(project, company_profile=self._company_profile).export_checklists_pdf(path)

        self._run("Checklisten werden erstellt…", do, f"Checklisten erstellt: {path}")

    def _gen_checklists_excel(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Checklisten speichern",
            f"{self._project.name}_Checklisten.xlsx",
            "Excel-Dateien (*.xlsx)",
        )
        if not path:
            return
        project = self._project

        def do():
            from ...services.documentation_service import DocumentationService
            DocumentationService(project, company_profile=self._company_profile).export_checklists_excel(path)

        self._run("Checklisten (Excel) werden erstellt…", do, f"Checklisten Excel erstellt: {path}")

    def _gen_acceptance(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Abnahmeprotokoll speichern",
            f"{self._project.name}_Abnahme.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project = self._project

        def do():
            from ...services.documentation_service import DocumentationService
            DocumentationService(project, company_profile=self._company_profile).export_acceptance_protocol(path)

        self._run("Abnahmeprotokoll wird erstellt…", do, f"Abnahmeprotokoll erstellt: {path}")

    def _gen_manual(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Bedienungsanleitung speichern",
            f"{self._project.name}_Bedienungsanleitung.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project = self._project

        def do():
            from ...services.documentation_service import DocumentationService
            DocumentationService(project, company_profile=self._company_profile).generate_user_manual(path)

        self._run("Bedienungsanleitung wird erstellt…", do, f"Bedienungsanleitung erstellt: {path}")

    def _gen_bauherr_form(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Bauherr-Formular speichern",
            f"{self._project.name}_Funktionsdefinition.xlsx",
            "Excel-Dateien (*.xlsx)",
        )
        if not path:
            return
        project = self._project

        def do():
            from ...services.bauherr_form_service import BauherrFormService
            BauherrFormService(project).generate_form(path)

        self._run("Bauherr-Formular wird erstellt…", do, f"Bauherr-Formular erstellt: {path}")

    def _gen_revision(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "Revisionspaket-Ordner wählen",
        )
        if not dir_path:
            return
        project = self._project

        def do():
            from ...services.documentation_service import DocumentationService
            DocumentationService(project, company_profile=self._company_profile).generate_revision_package(dir_path)

        self._run("Revisionspaket wird erstellt…", do, f"Revisionspaket erstellt in: {dir_path}")

    def _gen_bedienelemente(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Bedienelemente-Bericht speichern",
            f"{self._project.name}_Bedienelemente.pdf",
            "PDF-Dateien (*.pdf);;Text-Dateien (*.txt)",
        )
        if not path:
            return
        project, company = self._project, self._company_profile

        def do():
            from ...services.report_service import ReportService
            ReportService(project, company_profile=company).generate_bedienelemente_report(path)

        self._run("Bedienelemente-Bericht wird erstellt…", do, f"Bedienelemente-Bericht erstellt: {path}")
