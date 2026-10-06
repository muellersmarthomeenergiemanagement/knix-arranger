"""
Gemeinsame Gateways (FA-1307): z.B. ein Revox-Gateway fuer Studio und
Wohnung statt je Linie eines.
"""
from __future__ import annotations
import logging
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Verteiler, Wing,
)
from knix_arranger.models.project import KnxProject, ProjectConfig
from knix_arranger.services.actor_service import ActorService
from knix_arranger.services.topology_engine import TopologyEngine


def _project(hv: bool = True) -> KnxProject:
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="Revox")
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    studio = Apartment(name="Studio", rooms=[Room(
        number="S01", name="Studio Wohnen", gewerk_assignments=[
            GewerkAssignment(gewerk_code="MM"), GewerkAssignment(gewerk_code="LDA")])])
    technik = Room(number="E09", name="Technik",
                   verteiler=[Verteiler(name="HV", verteiler_type="HV")] if hv else [])
    wohnung = Apartment(name="Wohnung", rooms=[
        Room(number="W01", name="Wohnen", gewerk_assignments=[
            GewerkAssignment(gewerk_code="MM"), GewerkAssignment(gewerk_code="LDA")]),
        technik])
    floor.apartments = [studio, wohnung]
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(floors=[floor])])])
    project.topology = TopologyEngine(project.config.topology_mode).calculate_topology(project.areal)
    logging.disable(logging.NOTSET)
    return project


def _gateways(project) -> dict[str, list[str]]:
    TopologyEngine(project.config.topology_mode).populate_devices(
        project.topology, project.all_rooms, project.gewerk_catalog,
        shared_gateways=project.shared_gateways())
    return {line.name: sorted(d.product for d in line.devices if d.device_type == "gateway")
            for area in project.topology.areas for line in area.lines}


def test_defaults():
    config = ProjectConfig()
    assert config.gateway_shared("MM") and config.gateway_shared("WP")
    assert config.gateway_shared("PV") and config.gateway_shared("KL")
    assert not config.gateway_shared("LDA") and not config.gateway_shared("DMX")
    config.gateway_scope = {"MM": "line", "LDA": "project"}
    assert not config.gateway_shared("MM") and config.gateway_shared("LDA")
    restored = ProjectConfig.from_dict(config.to_dict())
    assert restored.gateway_scope == {"MM": "line", "LDA": "project"}
    assert ProjectConfig.from_dict({}).gateway_scope == {}


def test_revox_one_gateway_on_hv_line_dali_per_line():
    gateways = _gateways(_project())
    # MM gemeinsam: ein Gateway mit 2 Zonen auf der Linie mit der HV (Wohnung)
    assert gateways["Wohnung"] == ["DALI-Gateway 16-fach", "KNX-Schnittstelle 2-fach"]
    # DALI bleibt je Linie
    assert gateways["Studio"] == ["DALI-Gateway 16-fach"]


def test_per_line_on_request():
    project = _project()
    project.config.gateway_scope["MM"] = "line"
    gateways = _gateways(project)
    assert "KNX-Schnittstelle 1-fach" in gateways["Studio"]
    assert "KNX-Schnittstelle 1-fach" in gateways["Wohnung"]


def test_chosen_line_and_fallback_without_hv():
    project = _project()
    studio_line = next(ln for a in project.topology.areas for ln in a.lines
                       if ln.name == "Studio")
    project.config.gateway_line["MM"] = studio_line.id
    assert "KNX-Schnittstelle 2-fach" in _gateways(project)["Studio"]

    # ohne HV: erste Linie mit Räumen des Gewerks
    project = _project(hv=False)
    area, line = ActorService.shared_gateway_line(project.topology, project.all_rooms, "MM")
    assert line.name == "Studio"


def test_step_shows_choice_and_changes_recalculate():
    from PySide6.QtWidgets import QApplication, QComboBox
    app = QApplication.instance() or QApplication([])
    from knix_arranger.ui.wizard.step06_actors import Step06Actors
    project = _project()
    step = Step06Actors(project)
    step._calculate()
    assert not step._gateway_group.isHidden()
    combos = step._gateway_group.findChildren(QComboBox)
    labels = [step._gateway_grid.itemAtPosition(r, 0).widget().text()
              for r in range(step._gateway_grid.rowCount())
              if step._gateway_grid.itemAtPosition(r, 0)]
    assert labels == ["LDA – Licht dimmbar DALI (2 Räume)", "MM – Multimedia (2 Räume)"]
    mm_scope = step._gateway_grid.itemAtPosition(1, 1).widget()
    assert mm_scope.currentData() == "project"
    assert "automatisch: Linie" in step._gateway_grid.itemAtPosition(1, 2).widget().itemText(0)

    mm_scope.setCurrentIndex(1)           # je Linie
    app.processEvents()
    assert project.config.gateway_scope == {"MM": "line"}
    mm_scope = step._gateway_grid.itemAtPosition(1, 1).widget()
    mm_scope.setCurrentIndex(0)           # wieder Vorgabe: kein Eintrag
    app.processEvents()
    assert project.config.gateway_scope == {}
    assert len(combos) >= 4
