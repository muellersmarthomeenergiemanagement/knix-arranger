"""
Tests fuer frei stehende Nebengebaeude: eindeutige Hauptgruppen im Areal
(FA-411), Validierung bei mehrfach vergebener HG und gemeinsame
Gebaeudeauswahl der Wizard-Schritte 1-3 (FA-101a).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.project import KnxProject
from knix_arranger.services.building_service import BuildingService
from knix_arranger.services.room_numbering import suggest_room_number
from knix_arranger.services.validation_engine import ValidationEngine
from knix_arranger.ui.wizard.building_bar import BuildingSelection
from knix_arranger.ui.wizard.step01_building import Step01Building
from knix_arranger.ui.wizard.step02_apartments import Step02Apartments
from knix_arranger.ui.wizard.step03_rooms import Step03Rooms


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _chalet_project() -> KnxProject:
    """Chalet mit EG (HG 3) und OG (HG 2), Zone C mit Raeumen."""
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=3)
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=2)
    eg.apartments = [Apartment(name="Chalet Wohnung", rooms=[
        Room(number="CEG01", name="Eingang", floor_id=eg.id)])]
    og.apartments = [Apartment(name="Chalet Wohnung", rooms=[
        Room(number="COG01", name="Halle", floor_id=og.id)])]
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[
        Building(name="Chalet", wings=[Wing(name="Haupt", floors=[og, eg])])])
    return project


class TestHauptgruppen:

    def test_bevorzugte_hg_wenn_frei(self):
        areal = _chalet_project().areal
        assert BuildingService.next_free_main_group(areal, 7) == 7

    def test_belegte_hg_wird_ersetzt(self):
        areal = _chalet_project().areal
        assert BuildingService.next_free_main_group(areal, 2) == 1

    def test_add_floor_im_nebengebaeude(self):
        """EG waere laut FLOOR_TO_MAIN_GROUP HG 2 -- die gehoert dem Chalet-OG."""
        areal = _chalet_project().areal
        halle = Building(name="Einstellhalle", wings=[Wing()])
        areal.buildings.append(halle)
        floor = BuildingService.add_floor(halle.wings[0], "Erdgeschoss", "EG", areal=areal)
        assert floor.main_group_number == 1
        assert BuildingService.shared_main_groups(areal) == {}

    def test_add_floor_ohne_areal_wie_bisher(self):
        wing = Wing()
        assert BuildingService.add_floor(wing, "Erdgeschoss", "EG").main_group_number == 2

    def test_mehrfach_vergebene_hg(self):
        areal = _chalet_project().areal
        halle = Building(name="Einstellhalle", wings=[Wing(floors=[
            Floor(short_code="EG", main_group_number=2)])])
        areal.buildings.append(halle)
        shared = BuildingService.shared_main_groups(areal)
        assert list(shared) == [2]
        assert [b.name for b, _f in shared[2]] == ["Chalet", "Einstellhalle"]


class TestValidierung:

    def _issues(self, project):
        return [i for i in ValidationEngine().validate(project.group_addresses, project)
                if i.rule_id == "FA-411"]

    def test_warnung_bei_geteilter_hg(self):
        project = _chalet_project()
        project.areal.buildings.append(Building(name="Chalet Momo", wings=[Wing(floors=[
            Floor(short_code="EG", main_group_number=2)])]))
        issues = self._issues(project)
        assert len(issues) == 1
        assert issues[0].level == "warning"
        assert "Chalet OG" in issues[0].message and "Chalet Momo EG" in issues[0].message

    def test_keine_warnung_bei_eindeutigen_hg(self):
        assert self._issues(_chalet_project()) == []

    def test_importiertes_projekt_ohne_pruefung(self):
        project = _chalet_project()
        project.topology.is_imported = True
        project.areal.buildings[0].wings[0].floors[1].main_group_number = 2
        assert self._issues(project) == []


class TestRaumnummerNebengebaeude:

    def test_praefix_aus_anderem_gebaeude(self):
        project = _chalet_project()
        areal = project.areal
        halle = Building(name="Einstellhalle", wings=[Wing()])
        areal.buildings.append(halle)
        floor = BuildingService.add_floor(halle.wings[0], "Erdgeschoss", "EG", areal=areal)
        floor.apartments = [Apartment(name="Einstellhalle")]
        assert suggest_room_number(areal, halle.wings[0], floor.apartments[0], floor) == "EEG01"


class TestGebaeudeauswahl:

    def test_auswahl_faellt_auf_erstes_gebaeude_zurueck(self):
        project = _chalet_project()
        selection = BuildingSelection(project)
        assert selection.building() is project.areal.buildings[0]
        selection.building_id = "geloescht"
        assert selection.building() is project.areal.buildings[0]

    def test_leeres_projekt_erhaelt_gebaeude_und_fluegel(self):
        project = KnxProject(name="Neu")
        project.areal = Areal()
        wing = BuildingSelection(project).wing()
        assert project.areal.buildings[0].name == "Neu"
        assert project.areal.buildings[0].wings == [wing]

    def test_schritte_bearbeiten_gewaehltes_gebaeude(self):
        project = _chalet_project()
        halle = Building(name="Einstellhalle", wings=[Wing(name="Haupt")])
        project.areal.buildings.append(halle)
        selection = BuildingSelection(project)
        steps = [Step01Building(project, selection=selection),
                 Step02Apartments(project, selection=selection),
                 Step03Rooms(project, selection=selection)]

        selection.building_id = halle.id
        for step in steps:
            step.on_enter()
            assert step._get_wing() is halle.wings[0]

        # Stockwerk im Nebengebaeude erhaelt eine freie HG (nicht 2 fuer EG)
        steps[0]._add_floor()
        new_floor = halle.wings[0].floors[0]
        assert new_floor.main_group_number == 1
        assert steps[0]._floor_list.count() == 1
        # Chalet bleibt unveraendert
        assert len(project.areal.buildings[0].wings[0].floors) == 2
