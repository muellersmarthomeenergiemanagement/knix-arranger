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

    def test_szenen_report_ohne_szenen(self, sample_project, tmp_path):
        """Ohne definierte Szenen darf der Bericht nicht abstuerzen."""
        path = str(tmp_path / "szenen.pdf")
        ReportService(sample_project).generate_szenen_report(path)
        txt_path = path.rsplit(".", 1)[0] + ".txt"
        assert os.path.exists(path) or os.path.exists(txt_path)


class TestSzenenReport:
    """Regressionstests fuer generate_szenen_report (FA-1811).

    Deckt insbesondere den Fehler ab, dass 'Betroffene Gewerke' urspruenglich
    ueber BelegungsplanService._gewerke_for_device(device.product) ermittelt
    wurde -- das liefert die volle Typ-Faehigkeitsmenge eines 'Schaltaktor'
    (L/S/V/G/DF/BW/BL/P), nicht das im Projekt tatsaechlich zugewiesene
    Gewerk. Korrekt ist die Ableitung aus den echten Belegungsplan-Zeilen
    des Geraets.
    """

    def test_betroffene_gewerke_zeigt_nur_tatsaechlich_zugewiesenes_gewerk(
        self, sample_project, tmp_path
    ):
        fitz = pytest.importorskip("fitz")
        from knix_arranger.models.scene import Scene
        from knix_arranger.models.topology import Area, Line, Device, CommunicationObject

        project = sample_project
        room2 = next(r for r in project.all_rooms if r.number == "E02")  # Gewerk "L"
        project.scenes.append(
            Scene(name="Kueche An", scene_number=1, scope="room", scope_id=room2.id)
        )

        gen = AddressGenerator(project.gewerk_catalog, variant="A")
        project.group_addresses = gen.generate(
            project.areal, scenes=project.scenes, project=project
        )
        for ga in project.group_addresses.all_addresses():
            if ga.gewerk_code == "L" and ga.central != "true" and ga.room_number == "E02":
                ga.room_id = room2.id
        szenen_ga = next(
            ga for ga in project.group_addresses.all_addresses()
            if ga.designation == "Szenenaufruf Kueche"
        )

        device = Device(
            physical_address="1.1.1", device_type="actor", product="Schaltaktor 4-fach",
            communication_objects=[
                CommunicationObject(object_number=1, name="8-Bit-Szene",
                                     data_type="DPST-17-1", connected_gas=[szenen_ga.address]),
            ],
        )
        line = Line(line_number=1, name="Linie 1", assigned_room_ids=[room2.id], devices=[device])
        area = Area(area_number=1, name="Bereich 1", lines=[line])
        project.topology.areas = [area]

        path = str(tmp_path / "szenen.pdf")
        ReportService(project).generate_szenen_report(path)

        doc = fitz.open(path)
        text = "\n".join(p.get_text() for p in doc)
        doc.close()

        gewerke_line = next(l for l in text.splitlines() if l.startswith("Betroffene Gewerke"))
        assert "Beamer-Lift" not in gewerke_line
        assert "Bewaesserung" not in gewerke_line
        assert "Dachfenster" not in gewerke_line

    def test_ausgeloest_durch_zeigt_alle_taster_einer_szene(
        self, sample_project, tmp_path
    ):
        """Zwei Taster in unterschiedlichen Raeumen rufen dieselbe Szene auf
        (SensorFunktion.scene_id, Schritt 8) -- der Report muss beide auflisten,
        nicht nur den zuletzt gefundenen (Ausgangspunkt dieses Fixes: Scene.trigger
        ist ein einzelnes Freitextfeld und kann mehrere Taster nicht abbilden)."""
        fitz = pytest.importorskip("fitz")
        from knix_arranger.models.scene import Scene
        from knix_arranger.models.building import Bedienelement, SensorFunktion

        project = sample_project
        room1 = next(r for r in project.all_rooms if r.number == "E01")
        room2 = next(r for r in project.all_rooms if r.number == "E02")

        scene = Scene(name="Kino", scene_number=1, scope="central")
        project.scenes.append(scene)
        gen = AddressGenerator(project.gewerk_catalog, variant="A")
        project.group_addresses = gen.generate(
            project.areal, scenes=project.scenes, project=project
        )
        szenen_ga = next(
            ga for ga in project.group_addresses.all_addresses()
            if ga.designation == "ZENTRAL Szenenaufruf"
        )

        # button_channel ("Taste N") wird nicht hier vorgegeben, sondern von
        # generate_szenen_report ueber BelegungsplanService -> auto_assign_functions
        # aus den Sensorfunktionen der BE neu berechnet (siehe sensor_service.
        # _expand_funktionen) -- deshalb je BE zwei Funktionen, sonst faellt die
        # Nummerierung auf das Freitext-Label zurueck (nur bei genau einer
        # Funktion je BE).
        sf1 = SensorFunktion(
            label="Kino", ga_designation=szenen_ga.designation,
            bedienart="Szene abrufen", scene_id=scene.id,
        )
        room1.bedienelemente.append(Bedienelement(
            element_type="Tastereinheit", product_name="Taster Sofa", is_auto=False,
            participant_number="1.1.5",
            funktionen=[
                SensorFunktion(ga_designation="Dummy GA 1", label="Dummy 1"),
                SensorFunktion(ga_designation="Dummy GA 2", label="Dummy 2"),
                sf1,
            ],
        ))
        sf2 = SensorFunktion(
            label="Kino", ga_designation=szenen_ga.designation,
            bedienart="Szene abrufen", scene_id=scene.id,
        )
        room2.bedienelemente.append(Bedienelement(
            element_type="Tastereinheit", product_name="Taster Tuer", is_auto=False,
            participant_number="1.1.9",
            funktionen=[
                sf2,
                SensorFunktion(ga_designation="Dummy GA 3", label="Dummy 3"),
            ],
        ))

        # generate_szenen_report expandiert be.funktionen -> function_assignments
        # als Seiteneffekt (ueber BelegungsplanService -> auto_assign_functions);
        # erst danach ist button_channel ("Taste N") auf den BEs verfuegbar.
        path = str(tmp_path / "szenen.pdf")
        rs = ReportService(project)
        rs.generate_szenen_report(path)

        # Kernlogik deterministisch pruefen (unabhaengig vom PDF-Zeilenumbruch,
        # der eine lange Adresse wie "1.1.9" mitten im Wort umbrechen kann --
        # normale Formatierung, aber ungeeignet fuer einen Text-Zeilen-Vergleich).
        buttons = rs._scene_trigger_buttons_index()[scene.id]
        assert len(buttons) == 2
        assert any(
            b.startswith("Raum E01 Wohnzimmer") and "Taster 1.1.5" in b and "Taste 3" in b
            for b in buttons
        )
        assert any(
            b.startswith("Raum E02 Kueche") and "Taster 1.1.9" in b and "Taste 1" in b
            for b in buttons
        )

        # Smoke-Test: sicherstellen, dass die berechneten Zuweisungen auch
        # tatsaechlich im PDF landen (nicht nur im Hilfsmethoden-Ergebnis).
        doc = fitz.open(path)
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        assert "Ausgelöst durch (Taster-Zuweisung)" in text

    def test_legacy_zuordnung_ohne_scene_id_wird_nur_bei_eindeutigem_kanal_aufgeloest(
        self, sample_project,
    ):
        """Vor Einfuehrung von SensorFunktion.scene_id angelegte 'Szene abrufen'-
        Zuweisungen kennen nur den geteilten Kanal (ga_designation), nicht die
        konkrete Szene. Teilen sich mehrere Szenen denselben Kanal, darf der
        Report NICHT raten (Gefahr einer stillen Falschzuordnung im Bauherren-
        Dokument) -- nur bei genau einer Szene auf dem Kanal ist es sicher."""
        from knix_arranger.models.scene import Scene
        from knix_arranger.models.building import Bedienelement, SensorFunktion

        project = sample_project
        room1 = next(r for r in project.all_rooms if r.number == "E01")

        scene_a = Scene(name="Anwesend", scene_number=1, scope="central")
        scene_b = Scene(name="Abwesend", scene_number=2, scope="central")
        project.scenes += [scene_a, scene_b]
        gen = AddressGenerator(project.gewerk_catalog, variant="A")
        project.group_addresses = gen.generate(
            project.areal, scenes=project.scenes, project=project
        )
        szenen_ga = next(
            ga for ga in project.group_addresses.all_addresses()
            if ga.designation == "ZENTRAL Szenenaufruf"
        )

        # Alte Zuweisung ohne scene_id -- mehrdeutig, da beide Szenen denselben
        # Kanal teilen.
        room1.bedienelemente.append(Bedienelement(
            element_type="Tastereinheit", product_name="Taster Sofa", is_auto=False,
            participant_number="1.1.5",
            funktionen=[SensorFunktion(
                label="Anwesenheit", ga_designation=szenen_ga.designation,
                bedienart="Szene abrufen",
            )],
        ))

        idx = ReportService(project)._scene_trigger_buttons_index()
        assert idx.get(scene_a.id, []) == []
        assert idx.get(scene_b.id, []) == []


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
