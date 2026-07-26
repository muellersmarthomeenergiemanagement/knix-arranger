"""Tests fuer Report-Service und Dokumentation."""
import os
import tempfile
import pytest
from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.services.report_service import ReportService
from knix_arranger.services.documentation_service import DocumentationService
from knix_arranger.utils.pdf_generator import PdfGenerator


@pytest.fixture
def sample_project():
    """Erstellt ein Testprojekt mit Gebaeudestruktur und GAs."""
    project = KnxProject(name="Test-EFH", project_number="P-2026-001")
    project.config.mg_variant = "A"

    floor = Floor(name="EG", short_code="EG", main_group_number=2)
    room1 = Room(number="E01", name="Wohnzimmer")
    room1.gewerk_assignments = [
        GewerkAssignment(gewerk_code="LD", count=1),
        GewerkAssignment(gewerk_code="J", count=2),
        GewerkAssignment(gewerk_code="H", count=1),
    ]
    room2 = Room(number="E02", name="Kueche")
    room2.gewerk_assignments = [
        GewerkAssignment(gewerk_code="L", count=2),
    ]
    apt = Apartment(name="EG", rooms=[room1, room2])
    floor.apartments = [apt]
    building = Building(name="Hauptgebaeude", wings=[Wing(name="Haupt", floors=[floor])])
    project.areal = Areal(name="Test-Areal", buildings=[building])

    # GAs generieren
    gen = AddressGenerator(project.gewerk_catalog, variant="A")
    project.group_addresses = gen.generate(project.areal)

    return project


class TestPdfGenerator:
    def test_save_text_fallback(self):
        pdf = PdfGenerator(title="Test", project_name="Testprojekt")
        pdf.add_heading("Titel", level=1)
        pdf.add_paragraph("Ein Absatz.")
        pdf.add_table(["A", "B"], [["1", "2"], ["3", "4"]])
        pdf.add_separator()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            pdf.save(filepath)
            # Pruefe ob Datei existiert (PDF oder TXT)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)


class TestReportService:
    def test_validation_report(self, sample_project):
        svc = ReportService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            issues = svc.generate_validation_report(filepath)
            assert isinstance(issues, list)
            # Datei sollte existieren
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_ga_report(self, sample_project):
        svc = ReportService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            svc.generate_ga_report(filepath)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_room_gewerk_report(self, sample_project):
        svc = ReportService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            svc.generate_room_gewerk_report(filepath)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_room_gewerk_report_without_gewerk_codes(self, sample_project):
        """Importierte Projekte haben keine ga.room_id/gewerk_code; die
        Raumzuordnung muss dann ueber verknuepfte Geraete funktionieren."""
        from knix_arranger.models.topology import (
            Area, Line, Device, CommunicationObject,
        )

        room1 = sample_project.all_rooms[0]
        for ga in sample_project.group_addresses.all_addresses():
            ga.room_id = ""
            ga.gewerk_code = ""

        first_ga = sample_project.group_addresses.all_addresses()[0]
        device = Device(
            physical_address="1.1.1",
            device_type="actor",
            room_id=room1.id,
            communication_objects=[
                CommunicationObject(connected_gas=[first_ga.address]),
            ],
        )
        area = Area(area_number=1)
        line = Line(line_number=1, devices=[device])
        area.lines.append(line)
        sample_project.topology.areas.append(area)

        svc = ReportService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            svc.generate_room_gewerk_report(filepath)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_project_summary(self, sample_project):
        svc = ReportService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            svc.generate_project_summary(filepath)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_topology_report(self, sample_project):
        svc = ReportService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            svc.generate_topology_report(filepath)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)


class TestDocumentationService:
    def test_create_checklists(self, sample_project):
        svc = DocumentationService(sample_project)
        checklists = svc.create_checklists()

        assert len(checklists) == 2  # E01 und E02
        # E01 hat LD, J, H -> mehr Pruefpunkte
        cl_e01 = checklists[0]
        assert cl_e01.room_name.startswith("E01")
        assert len(cl_e01.items) > 0

    def test_checklist_filters_by_gewerk(self, sample_project):
        svc = DocumentationService(sample_project)
        checklists = svc.create_checklists()

        # E02 hat nur L -> kein Dimmen, Jalousie, Heizung
        cl_e02 = checklists[1]
        check_types = [i.check_type for i in cl_e02.items]
        assert "Funktion Dimmen" not in check_types
        assert "Funktion Jalousie" not in check_types
        assert "Funktion Heizung" not in check_types

    def test_export_checklists_pdf(self, sample_project):
        svc = DocumentationService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            svc.export_checklists_pdf(filepath)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_acceptance_protocol(self, sample_project):
        svc = DocumentationService(sample_project)
        protocol = svc.create_acceptance_protocol(
            integrator_name="Max Muster",
            client_name="Hans Bauherr",
        )

        assert protocol.integrator_name == "Max Muster"
        assert protocol.client_name == "Hans Bauherr"
        assert len(protocol.checklists) == 2

    def test_user_manual(self, sample_project):
        svc = DocumentationService(sample_project)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            filepath = f.name

        try:
            svc.generate_user_manual(filepath)
            txt_path = filepath.rsplit(".", 1)[0] + ".txt"
            assert os.path.exists(filepath) or os.path.exists(txt_path)
        finally:
            for p in [filepath, txt_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_revision_package(self, sample_project):
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = DocumentationService(sample_project)
            result = svc.generate_revision_package(tmpdir)

            assert result == tmpdir
            # Pruefe ob Dateien erstellt wurden
            files = os.listdir(tmpdir)
            assert len(files) >= 5  # Mindestens 5 Dateien

            # Pruefe auf bekannte Dateien
            file_names = " ".join(files)
            assert "Zusammenfassung" in file_names
            assert "GA_Uebersicht" in file_names
            assert "Topologie" in file_names
            assert "Validierung" in file_names
            assert "CSV" in file_names or "Export" in file_names
            # FA-2505: Verknuepfungsmatrix fliesst automatisch in die
            # Revisionsunterlagen ein, wenn Sensor-/Aktor-Daten vorhanden sind.
            assert "Verknuepfungsmatrix" in file_names

    def test_revision_package_ohne_matrix_ohne_sensor_aktor_daten(self):
        """FA-2505: Ohne Sensoren/Aktoren wird kein leerer Matrix-Bericht erzeugt."""
        empty_project = KnxProject(name="Leer")
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = DocumentationService(empty_project)
            svc.generate_revision_package(tmpdir)
            files = " ".join(os.listdir(tmpdir))
            assert "Verknuepfungsmatrix" not in files
