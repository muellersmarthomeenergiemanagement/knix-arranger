"""
Tests fuer Szenen mit Zonen-Geltungsbereich: jede Zone einmal in der
Auswahl (auch ueber mehrere Stockwerke), eine gemeinsame Szenen-GA je Zone,
Loesen einer bestehenden Szenen-GA in der Planung und feste
Zentraladressen mit eigenem Namen.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene
from knix_arranger.services.address_generator import AddressGenerator, regenerate_addresses
from knix_arranger.services.scene_addressing import (
    build_scope_label_lookup, canonical_zone_id, normalize_scene_scopes, zone_choices,
)
from knix_arranger.ui.views.scene_view import SceneView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project() -> KnxProject:
    """Chalet: Zone ueber EG und OG, Studio nur EG; Einstellhalle mit Zone EG."""
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=3, apartments=[
        Apartment(name="Chalet Wohnung", rooms=[Room(number="CEG01", name="Eingang")]),
        Apartment(name="Chalet Studio", rooms=[Room(number="SEG01", name="Eingang")]),
    ])
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=2, apartments=[
        Apartment(name="Chalet Wohnung", rooms=[Room(number="COG01", name="Halle")]),
    ])
    halle = Floor(name="Erdgeschoss", short_code="EG", main_group_number=5, apartments=[
        Apartment(name="EG", rooms=[Room(number="EEG01", name="Garage")])])
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[
        Building(name="Chalet", wings=[Wing(floors=[og, eg])]),
        Building(name="Einstellhalle", wings=[Wing(floors=[halle])]),
    ])
    return project


def _zone_apts(project, name):
    return [a for f in project.all_floors for a in f.apartments if a.name == name]


class TestZonen:

    def test_jede_zone_einmal(self):
        labels = [label for label, _id in zone_choices(_project().areal)]
        assert labels == ["Chalet Wohnung", "Chalet Studio", "Einstellhalle / EG"]

    def test_kanonische_id_der_zone(self):
        project = _project()
        og_apt, eg_apt = _zone_apts(project, "Chalet Wohnung")
        assert canonical_zone_id(project.areal, eg_apt.id) == og_apt.id
        assert canonical_zone_id(project.areal, "unbekannt") == "unbekannt"

    def test_beschriftung_fuer_alle_stockwerke(self):
        project = _project()
        lookup = build_scope_label_lookup(project.areal)
        assert {lookup[a.id] for a in _zone_apts(project, "Chalet Wohnung")} == {"Chalet Wohnung"}
        assert lookup[_zone_apts(project, "EG")[0].id] == "Einstellhalle / EG"

    def test_normalisierung(self):
        project = _project()
        og_apt, eg_apt = _zone_apts(project, "Chalet Wohnung")
        project.scenes = [
            Scene(name="A", scene_number=1, scope="zone", scope_id=eg_apt.id),
            Scene(name="B", scene_number=2, scope="apartment", scope_id=og_apt.id),
            Scene(name="C", scene_number=1, scope="central"),
        ]
        assert normalize_scene_scopes(project) == 1
        assert [(s.scope, s.scope_id) for s in project.scenes[:2]] == \
            [("apartment", og_apt.id)] * 2

    def test_eine_szenen_ga_je_zone(self):
        project = _project()
        og_apt, eg_apt = _zone_apts(project, "Chalet Wohnung")
        project.scenes = [
            Scene(name="Morgen", scene_number=1, scope="apartment", scope_id=eg_apt.id),
            Scene(name="Abend", scene_number=2, scope="apartment", scope_id=og_apt.id),
        ]
        regenerate_addresses(project, variant="B")
        mg4 = next(mg for mg in project.group_addresses.main_groups[0].middle_groups
                   if mg.number == 4)
        channels = [ga for ga in mg4.group_addresses if ga.designation.startswith("Szenenaufruf")]
        assert [ga.designation for ga in channels] == ["Szenenaufruf Chalet Wohnung"]
        assert channels[0].description == "0=Morgen, 1=Abend"


class TestFesteZentraladressen:

    def test_umbenannte_bezeichnung_bleibt(self):
        project = _project()
        gen = AddressGenerator(project.gewerk_catalog, variant="B")
        first = gen.generate(project.areal)
        ga = next(g for g in first.all_addresses() if g.address == "0/4/1")
        ga.designation = "ZENTRAL Szene Abwesenheit Komplex"
        second = gen.generate(project.areal, existing=first)
        again = next(g for g in second.all_addresses() if g.address == "0/4/1")
        assert again.designation == "ZENTRAL Szene Abwesenheit Komplex"
        assert again.id == ga.id


def _view_with_existing_address(imported: bool = False):
    """Projekt mit manueller Szenen-GA 0/4/2 und daran gebundener Szene."""
    project = _project()
    project.topology.is_imported = imported
    structure = GroupAddressStructure(variant="B")
    hg0 = MainGroup(number=0, name="Zentral")
    hg0.middle_groups.append(MiddleGroup(number=4, name="Szenen", group_addresses=[
        GroupAddress(main_group=0, middle_group=4, sub_group=2,
                     designation="ZENTRAL Szene Anwesenheit Chalet",
                     datapoint_type="DPST-17-1", is_manual=True)]))
    structure.main_groups.append(hg0)
    project.group_addresses = structure
    project.scenes = [
        Scene(name="ZENTRAL Szene Anwesenheit Chalet", scene_number=0, scope="central",
              is_detected=True, detection_kind="dpt", source_ga_addresses=["0/4/2"]),
        Scene(name="Komplex belegt", scene_number=1, scope="central",
              source_ga_addresses=["0/4/2"]),
    ]
    view = SceneView()
    view.set_project(project)
    group = next(g for g in view._overview.addresses if g.ga and g.ga.address == "0/4/2")
    view._get_selected_address = lambda: group
    view._scene_target.setCurrentIndex(view._scene_target.findText("Zone Chalet Wohnung"))
    return project, view


class TestBestehendeSzenenAdresse:

    def test_auswahl_ohne_doppelte_eintraege(self):
        _project_, view = _view_with_existing_address()
        texts = [view._scene_target.itemText(i) for i in range(view._scene_target.count())]
        assert texts.count("Zone Chalet Wohnung") == 1

    def test_neu_erzeugen_loest_szenen(self):
        project, view = _view_with_existing_address()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._apply_address_changes()
        zone_id = _zone_apts(project, "Chalet Wohnung")[0].id
        assert [(s.name, s.scene_number, s.scope, s.scope_id, s.source_ga_addresses)
                for s in project.scenes] == [
            ("Komplex belegt", 1, "apartment", zone_id, [])]
        assert not any(ga.address == "0/4/2" for ga in project.group_addresses.all_addresses())
        regenerate_addresses(project, variant="B")
        ga = next(g for g in project.group_addresses.all_addresses() if g.address == "0/4/2")
        assert ga.designation == "Szenenaufruf Chalet Wohnung"

    def test_nein_nur_beschriftung(self):
        project, view = _view_with_existing_address()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            view._apply_address_changes()
        assert all(s.scope == "apartment" for s in project.scenes)
        assert all(s.source_ga_addresses == ["0/4/2"] for s in project.scenes)
        assert any(ga.address == "0/4/2" for ga in project.group_addresses.all_addresses())

    def test_importiertes_projekt_ohne_rueckfrage(self):
        project, view = _view_with_existing_address(imported=True)
        with patch.object(QMessageBox, "question") as question:
            view._apply_address_changes()
        question.assert_not_called()
        assert all(s.source_ga_addresses == ["0/4/2"] for s in project.scenes)
