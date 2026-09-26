"""Tests fuer den Validierungsbericht Gruppenadressen und das gemeinsame PDF-Layout."""
import pytest
from knix_arranger.models.project import KnxProject
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.services.dpt_suggestion import suggest_dpt
from knix_arranger.services.validation_engine import ValidationEngine
from knix_arranger.services.report_service import ReportService
from knix_arranger.utils import fonts
from knix_arranger.utils.pdf_generator import PdfGenerator


class TestDptSuggestion:
    @pytest.mark.parametrize("designation, expected", [
        ("L.OG.05.02+04_ea", "1.001 Schalten"),
        ("HS.OG.05.03_status   ( Grill )", "1.001 Schalten"),
        ("H.EG.01.1_ist Temp ( Carnozet )", "9.001 Temperatur"),
        ("Helligkeit_wert West", "9.004 Helligkeit (Lux)"),
        ("Windgeschwindigkeit_wert km/h", "9.028 Wind (km/h)"),
        ("Raum3_Szeneaufruf LED", "17.001 Szenennummer"),
        ("H.EG.00.1_status Ventil", "1.001 (PWM) / 5.001 (stetig)"),
    ])
    def test_aus_bezeichnung(self, designation, expected):
        assert suggest_dpt(designation) == expected

    def test_funktion_hat_vorrang(self):
        assert suggest_dpt("Irgendwas_status", "DIM") == "3.007 Dimmen"

    def test_ohne_hinweis_kein_vorschlag(self):
        assert suggest_dpt("Allgemeine Adresse") == ""
        assert suggest_dpt("   ") == ""


def _structure(*gas):
    structure = GroupAddressStructure()
    hg = MainGroup(number=2, name="EG")
    mg = MiddleGroup(number=0, name="Licht")
    mg.group_addresses.extend(gas)
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)
    return structure


class TestValidationIssueDetails:
    def test_luecke_ist_hinweis_mit_bereich(self):
        structure = _structure(
            GroupAddress(main_group=2, middle_group=0, sub_group=0,
                         designation="A", datapoint_type="DPST-1-1"),
            GroupAddress(main_group=2, middle_group=0, sub_group=4,
                         designation="B", datapoint_type="DPST-1-1"),
        )
        gap = [i for i in ValidationEngine().validate(structure) if i.rule_id == "FA-605"]
        assert len(gap) == 1
        assert gap[0].level == "info"
        assert gap[0].details == {"mg": "2/0", "start": 1, "end": 3}

    def test_fehlender_dpt_liefert_vorschlag(self):
        structure = _structure(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="L.EG.02.01_ea ( Garage )", datapoint_type="",
        ))
        issue = next(i for i in ValidationEngine().validate(structure) if i.rule_id == "FA-604")
        assert issue.designation == "L.EG.02.01_ea ( Garage )"
        assert issue.details["dpt"] == "1.001 Schalten"
        assert "unbekannt" not in issue.suggestion


@pytest.fixture
def import_like_project():
    """Viele GAs ohne DPT und mit eigenem Namensschema (wie ein ETS-Import)."""
    project = KnxProject(name="Import-Test")
    gas = [
        GroupAddress(main_group=2, middle_group=0, sub_group=n * 2,
                     designation=f"L.EG.{n:02d}.01_ea   ( Raum {n} )", datapoint_type="")
        for n in range(120)
    ]
    project.group_addresses = _structure(*gas)
    return project


class TestValidationReport:
    def test_titel_abschnitte_und_fortsetzung(self, import_like_project, tmp_path):
        fitz = pytest.importorskip("fitz")
        path = str(tmp_path / "val.pdf")
        ReportService(import_like_project).generate_validation_report(path)

        doc = fitz.open(path)
        pages = [p.get_text() for p in doc]
        doc.close()
        text = "\n".join(pages)

        assert "Validierungsbericht Gruppenadressen" in pages[0]
        assert "Fehlender Datenpunkttyp" in text
        assert "unbekannt" not in text
        # Folgeseiten nennen Abschnitt und Regel
        assert any("Warnungen" in p and "(Fortsetzung)" in p for p in pages[1:])
        # Bezeichnungen ohne Mehrfach-Leerzeichen
        assert "L.EG.05.01_ea ( Raum 5 )" in text

    def test_viele_bezeichnungshinweise_nur_beispiele(self, import_like_project, tmp_path):
        fitz = pytest.importorskip("fitz")
        path = str(tmp_path / "val.pdf")
        issues = ReportService(import_like_project).generate_validation_report(path)
        assert sum(1 for i in issues if i.rule_id == "FA-610") == 120

        doc = fitz.open(path)
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        assert "120 von 120 Bezeichnungen" in text
        # Letzte GA erscheint nur in FA-604, nicht mehr in der gekürzten FA-610-Liste
        assert text.count("2/0/238") == 1


class TestGaReportStatistik:
    def test_zentraladressen_ohne_central_flag(self, tmp_path):
        """Importierte Projekte haben kein central-Flag -- gezählt wird HG 0."""
        fitz = pytest.importorskip("fitz")
        project = KnxProject(name="Import")
        structure = GroupAddressStructure()
        hg0 = MainGroup(number=0, name="Zentral")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.extend(
            GroupAddress(main_group=0, middle_group=0, sub_group=n, designation=f"Z{n}")
            for n in range(1, 4))
        hg0.middle_groups.append(mg)
        structure.main_groups.append(hg0)
        project.group_addresses = structure

        path = str(tmp_path / "ga.pdf")
        ReportService(project).generate_ga_report(path)
        doc = fitz.open(path)
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        assert "Zentraladressen (HG 0): 3" in text
        assert "davon belegt: 3" in text


class TestInterFont:
    def test_inter_wird_mitgeliefert(self):
        assert fonts.INTER_REGULAR.endswith("Inter-Regular.ttf")
        assert fonts.INTER_BOLD.endswith("Inter-Bold.ttf")

    def test_pdf_bettet_inter_ein(self, tmp_path):
        fitz = pytest.importorskip("fitz")
        pdf = PdfGenerator(title="Test")
        pdf.add_heading("Abschnitt", level=2)
        pdf.add_table(["A", "B"], [["1", "2"]], col_widths=[0.3, 0.7])
        path = str(tmp_path / "t.pdf")
        pdf.save(path)
        doc = fitz.open(path)
        font_names = {f[3] for f in doc[0].get_fonts()}
        doc.close()
        assert any("Inter" in n for n in font_names)
