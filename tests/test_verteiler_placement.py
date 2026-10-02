"""
Tests fuer den Einbauort der Aktoren (FA-1305a): Verteiler je Linie
(automatisch oder gewaehlt) und je Aktortyp, Uebernahme bei Neuberechnung,
Schritt 8 und Topologie-Ansicht.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Verteiler, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Line
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.services.verteiler_service import (
    VerteilerPlacement, apply_device_locations, carry_over_line_verteiler,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project() -> KnxProject:
    """Chalet mit HV im UG und UV Halle im OG; Studio ohne eigenen Verteiler."""
    hv = Verteiler(name="HV Technikraum", verteiler_type="HV")
    uv = Verteiler(name="UV Halle", verteiler_type="UV")
    technik = Room(number="CUG01", name="Technik", verteiler=[hv])
    halle = Room(number="COG01", name="Halle", verteiler=[uv])
    wohnen = Room(number="COG02", name="Wohnen", gewerk_assignments=[
        GewerkAssignment(gewerk_code="L", count=6), GewerkAssignment(gewerk_code="J", count=4)])
    studio = Room(number="SEG01", name="Studio", gewerk_assignments=[
        GewerkAssignment(gewerk_code="L", count=2)])
    ug = Floor(name="Untergeschoss", short_code="UG", main_group_number=1,
               apartments=[Apartment(name="Chalet Wohnung", rooms=[technik])])
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3,
               apartments=[Apartment(name="Chalet Wohnung", rooms=[halle, wohnen])])
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2,
               apartments=[Apartment(name="Chalet Studio", rooms=[studio])])
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[Building(name="Chalet", wings=[Wing(floors=[ug, eg, og])])])
    engine = TopologyEngine(project.config.topology_mode)
    engine.update_device_estimates(project.all_rooms, project.gewerk_catalog)
    project.topology = engine.calculate_topology(project.areal)
    return project


def _line(project, name) -> Line:
    return next(l for a in project.topology.areas for l in a.lines if l.name == name)


def _vt(project, name) -> Verteiler:
    return next(vt for r in project.all_rooms for vt in r.verteiler if vt.name == name)


def _populate(project):
    TopologyEngine(project.config.topology_mode).populate_devices(
        project.topology, project.all_rooms, project.gewerk_catalog)


def _actor_locations(line) -> dict[str, str]:
    return {d.product: d.installation_location for d in line.devices
            if d.device_type in ("actor", "gateway")}


class TestZuordnung:

    def test_automatisch_erster_verteiler_der_linie(self):
        project = _project()
        placement = VerteilerPlacement(project.all_rooms)
        vt, _room = placement.for_line(_line(project, "Chalet Wohnung"))
        assert vt.name == "HV Technikraum"

    def test_linie_ohne_verteiler_bekommt_hv(self):
        project = _project()
        _populate(project)
        line = _line(project, "Chalet Studio")
        assert line.uv_location == "HV (HV Technikraum)"
        assert set(_actor_locations(line).values()) == {"HV (HV Technikraum)"}

    def test_gewaehlter_verteiler_und_abweichung_je_aktortyp(self):
        project = _project()
        line = _line(project, "Chalet Wohnung")
        _populate(project)
        jalousie = next(p for p in _actor_locations(line) if p.startswith("Jalousie"))
        line.verteiler_id = _vt(project, "UV Halle").id
        line.actor_verteiler[jalousie] = _vt(project, "HV Technikraum").id
        _populate(project)
        locations = _actor_locations(line)
        assert locations[jalousie] == "HV (HV Technikraum)"
        assert {loc for p, loc in locations.items() if p != jalousie} == {"UV (UV Halle)"}
        assert line.uv_location == "UV (UV Halle)"

    def test_freitext_der_linie_bleibt(self):
        project = _project()
        line = _line(project, "Chalet Studio")
        line.uv_location = "Steigzone 2"
        _populate(project)
        assert line.uv_location == "Steigzone 2"
        assert set(_actor_locations(line).values()) == {"Steigzone 2"}

    def test_nachfuehren_ohne_neuberechnung(self):
        project = _project()
        _populate(project)
        line = _line(project, "Chalet Studio")
        line.verteiler_id = _vt(project, "UV Halle").id
        apply_device_locations(project.topology, project.all_rooms)
        assert set(_actor_locations(line).values()) == {"UV (UV Halle)"}
        coupler = next(d for d in line.devices if d.device_type == "coupler")
        assert coupler.installation_location == "UV (UV Halle)"

    def test_programmiertes_geraet_bleibt(self):
        project = _project()
        _populate(project)
        line = _line(project, "Chalet Studio")
        device = next(d for d in line.devices if d.device_type == "actor")
        device.is_programmed = True
        line.verteiler_id = _vt(project, "UV Halle").id
        apply_device_locations(project.topology, project.all_rooms)
        assert device.installation_location == "HV (HV Technikraum)"

    def test_wahl_ueberlebt_neuberechnung_der_topologie(self):
        project = _project()
        _line(project, "Chalet Studio").verteiler_id = _vt(project, "UV Halle").id
        old = project.topology
        engine = TopologyEngine(project.config.topology_mode)
        project.topology = engine.calculate_topology(project.areal)
        carry_over_line_verteiler(old, project.topology)
        assert _line(project, "Chalet Studio").verteiler_id == _vt(project, "UV Halle").id

    def test_speichern_und_laden(self):
        line = Line(name="Chalet", verteiler_id="vt1", actor_verteiler={"Jalousieaktor 8-fach": "vt2"})
        again = Line.from_dict(line.to_dict())
        assert (again.verteiler_id, again.actor_verteiler) == ("vt1", {"Jalousieaktor 8-fach": "vt2"})


class TestSchritt8:

    def test_verteiler_inhalt_folgt_der_wahl(self):
        from knix_arranger.ui.wizard.step06_actors import Step06Actors
        project = _project()
        step = Step06Actors(project)
        step.on_enter()
        hv, uv = _vt(project, "HV Technikraum"), _vt(project, "UV Halle")
        assert hv.actor_assignments and not uv.actor_assignments

        step._set_line_verteiler(_line(project, "Chalet Studio"), uv.id)
        QApplication.processEvents()
        studio_types = {a.actor_type for a in uv.actor_assignments}
        assert studio_types
        assert set(_actor_locations(_line(project, "Chalet Studio")).values()) == {"UV (UV Halle)"}


class TestTopologieAnsicht:

    def test_einbauort_je_aktortyp_waehlen(self):
        from knix_arranger.ui.views.topology_view import TopologyView
        project = _project()
        _populate(project)
        view = TopologyView()
        view.set_project(project)
        line = _line(project, "Chalet Studio")
        device = next(d for d in line.devices if d.device_type == "actor")
        with patch.object(QInputDialog, "getItem", return_value=("UV (UV Halle)", True)):
            view._edit_device_location(device)
        assert line.actor_verteiler[device.product] == _vt(project, "UV Halle").id
        assert device.installation_location == "UV (UV Halle)"
