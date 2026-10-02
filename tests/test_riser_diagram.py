"""
Tests fuer das Steigschema (FA-905a): Stockwerk-Reihenfolge, Linienverlauf
vom Verteiler, Nebengebaeude mit Erdleitung, Hervorheben, PDF im
Querformat und App-Ansicht.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Verteiler, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.riser_diagram import (
    Dot, Label, LINE_COLORS, Path, Rect, blend, build_riser_diagram, floor_rank, _floor_ranks,
)
from knix_arranger.services.topology_engine import TopologyEngine


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project(with_halle: bool = True) -> KnxProject:
    hv = Verteiler(name="HV Technik", verteiler_type="HV")
    ug = Floor(name="Untergeschoss", short_code="UG", main_group_number=1, apartments=[
        Apartment(name="Wohnung", rooms=[Room(number="CUG01", name="Technik", verteiler=[hv])])])
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2, apartments=[
        Apartment(name="Wohnung", rooms=[Room(number="CEG01", name="Eingang", gewerk_assignments=[
            GewerkAssignment(gewerk_code="L", count=2)])])])
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3, apartments=[
        Apartment(name="Wohnung", rooms=[Room(number="COG01", name="Wohnen", gewerk_assignments=[
            GewerkAssignment(gewerk_code="L", count=3)])])])
    buildings = [Building(name="Chalet", wings=[Wing(floors=[ug, eg, og])])]   # unten -> oben
    if with_halle:
        buildings.append(Building(name="Einstellhalle", wings=[Wing(floors=[
            Floor(name="Erdgeschoss", short_code="EG", main_group_number=4, apartments=[
                Apartment(name="Halle", rooms=[Room(number="EEG01", name="Garage",
                          gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)])])])])]))
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=buildings)
    engine = TopologyEngine(project.config.topology_mode)
    engine.update_device_estimates(project.all_rooms, project.gewerk_catalog)
    project.topology = engine.calculate_topology(project.areal)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    return project


def _label_y(diagram, text) -> float:
    return next(s.y for s in diagram.shapes if isinstance(s, Label) and s.text == text)


class TestStockwerke:

    @pytest.mark.parametrize("code, rank", [
        ("EG", 0), ("OG", 1), ("1.OG", 1), ("2.OG", 2), ("OG2", 2), ("DG", 50),
        ("UG", -1), ("KG", -1), ("2.UG", -2), ("XY", None)])
    def test_hoehenlage(self, code, rank):
        assert floor_rank(code) == rank

    def test_unbekanntes_kuerzel_zwischen_nachbarn(self):
        floors = [Floor(short_code="EG"), Floor(short_code="Galerie"), Floor(short_code="DG")]
        ranks = _floor_ranks(floors)
        assert ranks[floors[0].id] < ranks[floors[1].id] < ranks[floors[2].id]

    def test_dach_oben_keller_unten(self):
        diagram = build_riser_diagram(_project(with_halle=False))
        assert _label_y(diagram, "OG") < _label_y(diagram, "EG") < _label_y(diagram, "UG")


class TestLinien:

    def test_linie_startet_am_verteiler(self):
        project = _project(with_halle=False)
        diagram = build_riser_diagram(project)
        vt = next(s for s in diagram.shapes if isinstance(s, Rect) and s.ref.startswith("vt:"))
        line = project.topology.areas[0].lines[0]
        stubs = [s for s in diagram.shapes if isinstance(s, Path)
                 and s.ref == f"line:{line.id}" and s.points[0][0] == vt.x + vt.w]
        assert stubs, "Abgang vom Verteiler fehlt"

    def test_punkt_je_raum_mit_teilnehmern(self):
        project = _project(with_halle=False)
        diagram = build_riser_diagram(project)
        dots = [s for s in diagram.shapes if isinstance(s, Dot)]
        assert len(dots) == 2      # CEG01 und COG01, nicht der Technikraum

    def test_nebengebaeude_mit_erdleitung(self):
        diagram = build_riser_diagram(_project())
        assert any(isinstance(s, Path) and s.dash for s in diagram.shapes)
        eg_labels = [s.y for s in diagram.shapes if isinstance(s, Label) and s.text == "EG"]
        assert len(eg_labels) == 2 and eg_labels[0] == eg_labels[1]   # gleiche Höhe

    def test_hervorheben(self):
        project = _project()
        lines = [l for a in project.topology.areas for l in a.lines]
        diagram = build_riser_diagram(project, highlight=f"line:{lines[0].id}")
        colors = {s.color for s in diagram.shapes if isinstance(s, Path) and s.ref == f"line:{lines[1].id}"}
        assert colors == {blend(LINE_COLORS[1], 0.78)}
        assert diagram.legend[1].color == LINE_COLORS[1]   # Liste behält die Farbe

    def test_leeres_projekt(self):
        project = KnxProject(name="Leer")
        project.areal = Areal()
        assert build_riser_diagram(project).is_empty


class TestPdf:

    def test_eigener_bericht_im_querformat(self, tmp_path):
        fitz = pytest.importorskip("fitz")
        from knix_arranger.services.report_service import ReportService
        path = str(tmp_path / "steig.pdf")
        ReportService(_project()).generate_riser_report(path)
        doc = fitz.open(path)
        sizes = [(int(p.rect.width), int(p.rect.height)) for p in doc]
        text = doc[-1].get_text()
        doc.close()
        assert sizes[-1] == (842, 595)
        assert all(w == 842 for w, _h in sizes[sizes.index((842, 595)):])
        assert "Einstellhalle" in text and "CEG01" in text

    def test_topologie_bericht_danach_wieder_hochformat(self, tmp_path):
        fitz = pytest.importorskip("fitz")
        from knix_arranger.services.report_service import ReportService
        path = str(tmp_path / "topo.pdf")
        ReportService(_project()).generate_topology_report(path)
        doc = fitz.open(path)
        widths = [int(p.rect.width) for p in doc]
        toc = [t for _lvl, t, _p in doc.get_toc()]
        doc.close()
        assert widths.count(842) == 1 and widths[-1] == 595
        assert "Steigschema" in toc


class TestAnsicht:

    def test_klick_auf_linie_hebt_hervor(self):
        from knix_arranger.ui.views.riser_diagram_view import RiserDiagramView
        project = _project()
        view = RiserDiagramView()
        view.set_project(project)
        assert view._scene.items()
        assert view._lines.count() == 1 + len(build_riser_diagram(project).legend)
        ref = view._lines.item(1).data(0x0100)
        view._on_click(ref)
        assert view._highlight == ref
        view._on_click("room:x")
        assert view._highlight == ""
