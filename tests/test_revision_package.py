"""
Tests fuer das Revisionspaket: Auswahl der Bestandteile (FA-2105),
Revisionsstand (FA-2106), Datenblaetter als Anhang (FA-1204) und
akzeptierte Kundenofferte (FA-2102 Nr. 13).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.documentation import RevisionRecord
from knix_arranger.models.project import KnxProject
from knix_arranger.models.quotation import CustomerQuote
from knix_arranger.services.documentation_service import DocumentationService
from knix_arranger.services.project_service import ProjectService
from knix_arranger.services.revision_package import (
    collect_datasheets, copy_datasheets, next_revision_number, revision_folder_name,
)
from test_revision_check import _complete_project


def _index_text(folder) -> str:
    index = next(f for f in os.listdir(folder) if "Inhaltsverzeichnis" in f)
    with fitz.open(os.path.join(folder, index)) as doc:
        return "".join(page.get_text() for page in doc)


class TestRevisionNumbers:
    def test_next_number(self):
        project = KnxProject(name="T")
        assert next_revision_number(project) == "A"
        project.revisions = [RevisionRecord("A"), RevisionRecord("B")]
        assert next_revision_number(project) == "C"
        project.revisions = [RevisionRecord(chr(ord("A") + i)) for i in range(26)]
        assert next_revision_number(project) == "AA"

    def test_folder_name(self):
        assert revision_folder_name("B") == "Rev_B"
        assert revision_folder_name(" 2/a ") == "Rev_2_a"


class TestDatasheets:
    def test_collect_dedupes_and_names_products(self):
        project, _ = _complete_project()
        project.all_rooms[0].bedienelemente[0].datasheets = ["aks.pdf", "taster.pdf"]
        sheets = {ds.path: ds.products for ds in collect_datasheets(project)}
        assert sheets["aks.pdf"] == ["Schaltaktor 8-fach", "Tastereinheit"]
        assert sheets["taster.pdf"] == ["Tastereinheit"]

    def test_copy_local_keeps_urls_reports_missing(self, tmp_path):
        source = tmp_path / "quelle"
        source.mkdir()
        (source / "a.pdf").write_bytes(b"%PDF-1.4")
        project, _ = _complete_project()
        device = project.topology.areas[0].lines[0].devices[0]
        device.datasheets = ["a.pdf", "https://example.com/b.pdf", str(tmp_path / "fehlt.pdf")]
        out = tmp_path / "paket"
        copied, missing = copy_datasheets(collect_datasheets(project), str(out), str(source))
        assert [os.path.basename(t) for _, t in copied] == ["a.pdf"]
        assert (out / "Datenblaetter" / "a.pdf").exists()
        assert [ds.path for ds in missing] == [str(tmp_path / "fehlt.pdf")]


class TestPackage:
    def test_selected_parts_only(self, tmp_path):
        project, company = _complete_project()
        DocumentationService(project, company_profile=company).generate_revision_package(
            str(tmp_path), parts={"ga_csv", "materialliste"})
        files = sorted(os.listdir(tmp_path))
        assert files == ["Test_GA_Export.csv", "Test_Inhaltsverzeichnis.pdf",
                         "Test_Materialliste.xlsx"]

    def test_revision_recorded_and_in_index(self, tmp_path):
        project, company = _complete_project()
        project.revisions.append(RevisionRecord("A", "01.09.2026", "Erstausgabe"))
        svc = DocumentationService(project, company_profile=company)
        svc.generate_revision_package(str(tmp_path), revision="B", parts={"ga_csv"},
                                      revision_date="06.10.2026", note="Erweiterung OG")
        assert [r.number for r in project.revisions] == ["A", "B"]
        assert project.revisions[1].note == "Erweiterung OG"
        assert project.revisions[1].parts == ["GA-Export (CSV)"]
        text = _index_text(tmp_path)
        assert "Revision: B vom 06.10.2026" in text
        assert "Anlass: Erweiterung OG" in text
        assert "Frühere Revisionen" in text and "Erstausgabe" in text
        assert os.path.exists(tmp_path / "Test_RevB_GA_Export.csv")

        # Dieselbe Revision erneut: ersetzt den Eintrag statt ihn zu doppeln
        svc.generate_revision_package(str(tmp_path), revision="B", parts={"ga_csv"})
        assert [r.number for r in project.revisions] == ["A", "B"]

    def test_datasheets_attached_and_listed(self, tmp_path):
        sheet = tmp_path / "aks.pdf"
        sheet.write_bytes(b"%PDF-1.4")
        project, company = _complete_project()
        project.topology.areas[0].lines[0].devices[0].datasheets = [str(sheet)]
        out = tmp_path / "paket"
        DocumentationService(project, company_profile=company).generate_revision_package(
            str(out), parts={"datenblaetter"})
        assert (out / "Datenblaetter" / "aks.pdf").exists()
        text = _index_text(out)
        assert "Produktdatenblätter" in text and "Schaltaktor 8-fach" in text

    def test_accepted_quote_only(self, tmp_path):
        project, company = _complete_project()
        project.customer_quotes = [CustomerQuote(quote_number="OF-1", status="Entwurf")]
        svc = DocumentationService(project, company_profile=company)
        with patch.object(ProjectService, "load_company_profile", return_value=company):
            svc.generate_revision_package(str(tmp_path / "a"), parts={"offerte"})
            assert not any("Kundenofferte" in f for f in os.listdir(tmp_path / "a"))
            project.customer_quotes[0].status = "Akzeptiert"
            svc.generate_revision_package(str(tmp_path / "b"), parts={"offerte"})
        assert os.path.exists(tmp_path / "b" / "Test_Kundenofferte.pdf")


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class TestDialog:
    def test_defaults(self, qapp):
        from knix_arranger.ui.dialogs.revision_package_dialog import RevisionPackageDialog
        project, _ = _complete_project()
        dlg = RevisionPackageDialog(project)
        assert dlg.revision == "A"
        assert dlg.note == "Erstausgabe"
        assert "offerte" not in dlg.parts           # keine akzeptierte Offerte
        assert {"abnahme", "datenblaetter", "materialliste"} <= dlg.parts

        project.revisions.append(RevisionRecord("A", "01.09.2026"))
        project.customer_quotes = [CustomerQuote(status="Akzeptiert")]
        dlg = RevisionPackageDialog(project)
        assert dlg.revision == "B" and dlg.note == ""
        assert "offerte" in dlg.parts


class TestReportsDialogFlow:
    def test_gen_revision_creates_folder_per_revision(self, qapp, tmp_path):
        from knix_arranger.ui.dialogs import reports_dialog
        from knix_arranger.ui.dialogs.reports_dialog import ReportsDialog
        project, company = _complete_project()
        project._file_path = str(tmp_path / "Test.knxarr")
        dlg = ReportsDialog(project, company_profile=company)

        options = type("Opts", (), {
            "exec": lambda self: reports_dialog.QDialog.Accepted,
            "revision": "A", "revision_date": "06.10.2026", "note": "Erstausgabe",
            "parts": {"ga_csv"}})()

        def run_now(_parent, _text, do, on_success, _ref):
            on_success(do())

        with patch("knix_arranger.ui.dialogs.revision_package_dialog.RevisionPackageDialog",
                   return_value=options), \
             patch.object(ReportsDialog, "_confirm_revision_completeness", return_value=True), \
             patch.object(reports_dialog, "run_export", run_now), \
             patch.object(reports_dialog.os, "startfile", create=True):
            dlg._gen_revision()

        folder = tmp_path / "Revisionen" / "Rev_A"
        assert (folder / "Test_RevA_GA_Export.csv").exists()
        assert [r.number for r in project.revisions] == ["A"]
