"""
Tests fuer "Weitere Szene auf dieser GA" in der Szenen-Verwaltung: neue Szene
mit naechster freier Nummer auf derselben Szenen-GA, fest an eine bestehende
(importierte) GA gebunden -- ohne dass beim Generieren eine zusaetzliche
Szenenaufruf-GA entsteht.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.services.scene_addressing import (
    group_named_scenes, is_bound_scene, scene_target_designation,
    build_scope_label_lookup,
)
from knix_arranger.ui.views.scene_view import SceneView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project() -> KnxProject:
    """Nachbau "Test Musik": erkannte Szene "Komponieren" (Nr. 1) auf der
    importierten GA 1/0/15 "LDA_M01_01 SZENE", Wohnung "Studio"."""
    project = KnxProject(name="Test Musik")
    apt = Apartment(name="Studio")
    apt.rooms = [Room(number="M01", name="Musikzimmer")]
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Test")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])

    mg = MiddleGroup(number=0, name="Licht")
    mg.group_addresses = [GroupAddress(
        main_group=1, middle_group=0, sub_group=15,
        designation="LDA_M01_01 SZENE", gewerk_code="LDA", function_name="SZENE",
    )]
    hg = MainGroup(number=1, name="EG")
    hg.middle_groups = [mg]
    project.group_addresses = GroupAddressStructure()
    project.group_addresses.main_groups = [hg]

    project.scenes = [
        Scene(name="ZENTRAL Szenenaufruf", scene_number=0, scope="central",
              is_detected=True, detection_kind="dpt", source_ga_addresses=["0/4/2"]),
        Scene(name="Komponieren", scene_number=1, scope="apartment", scope_id=apt.id,
              trigger="Taster", is_detected=True, detection_kind="dpt",
              source_ga_addresses=["1/0/15"],
              actions=[SceneAction(group_address="LDA_M01_01 SZENE", ga_address="1/0/15")]),
    ]
    return project


def _view(project: KnxProject) -> SceneView:
    view = SceneView()
    view.set_project(project)
    return view


def _select(view: SceneView, scene: Scene) -> None:
    view._table.setCurrentCell(view._project.scenes.index(scene), 0)


class TestAddSceneOnSameGa:
    def test_new_scene_is_bound_to_same_ga_with_next_number(self):
        project = _project()
        view = _view(project)
        komponieren = project.scenes[1]
        _select(view, komponieren)

        view._add_scene_on_same_ga()

        new = project.scenes[2]
        assert new.scene_number == 2
        assert new.scope == "apartment" and new.scope_id == komponieren.scope_id
        assert new.source_ga_addresses == ["1/0/15"]
        assert not new.is_detected and is_bound_scene(new)
        assert [(a.group_address, a.ga_address) for a in new.actions] == [
            ("LDA_M01_01 SZENE", "1/0/15")
        ]
        # Neue Szene ist ausgewählt, Quelle zeigt die gebundene GA
        assert view._get_selected_scene() is new
        assert view._table.item(2, 5).text() == "Manuell → 1/0/15"

    def test_repeated_use_fills_next_free_numbers(self):
        project = _project()
        view = _view(project)
        _select(view, project.scenes[1])
        view._add_scene_on_same_ga()        # Nr. 2, danach ausgewählt
        view._add_scene_on_same_ga()        # Nr. 3 (von der neuen Szene aus)
        numbers = [s.scene_number for s in project.scenes
                   if s.source_ga_addresses == ["1/0/15"]]
        assert numbers == [1, 2, 3]

    def test_manual_scene_with_action_on_ga_blocks_its_number(self):
        # "Üben" wurde von Hand mit Nr. 2 und Aktion auf 1/0/15 angelegt
        project = _project()
        apt_id = project.scenes[1].scope_id
        project.scenes.append(Scene(
            name="Üben", scene_number=2, scope="apartment", scope_id=apt_id,
            actions=[SceneAction(group_address="Licht", ga_address="1/0/15")],
        ))
        view = _view(project)
        _select(view, project.scenes[1])
        view._add_scene_on_same_ga()
        new = next(s for s in project.scenes if s.name.startswith("Neue Szene"))
        assert new.scene_number == 3

    def test_bound_scene_gets_no_generated_ga_but_existing_designation(self):
        project = _project()
        view = _view(project)
        _select(view, project.scenes[1])
        view._add_scene_on_same_ga()
        new = project.scenes[2]
        new.name = "Üben"

        assert group_named_scenes(project.scenes, project.areal) == {}
        label_lookup = build_scope_label_lookup(project.areal)
        assert scene_target_designation(
            new, label_lookup, project.group_addresses
        ) == "LDA_M01_01 SZENE"

    def test_unbound_manual_scene_shares_generated_ga(self):
        project = _project()
        apt_id = project.scenes[1].scope_id
        manual = Scene(name="Kino", scene_number=1, scope="apartment", scope_id=apt_id)
        project.scenes.append(manual)
        view = _view(project)
        _select(view, manual)

        view._add_scene_on_same_ga()

        new = project.scenes[-1]
        assert new.scene_number == 2
        assert new.source_ga_addresses == [] and new.actions == []
        new.name = "Lesen"
        groups = group_named_scenes(project.scenes, project.areal)
        assert [s.name for s in groups[apt_id][1]] == ["Kino", "Lesen"]

    def test_without_selection_shows_hint(self):
        project = _project()
        view = _view(project)
        view._table.setCurrentCell(-1, -1)
        with patch("knix_arranger.ui.views.scene_view.QMessageBox.information") as info:
            view._add_scene_on_same_ga()
        info.assert_called_once()
        assert len(project.scenes) == 2
