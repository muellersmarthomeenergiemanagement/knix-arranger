"""
Tests fuer den beidseitigen Abgleich DALI-Szenen <-> Szenen-Verwaltung:
Die Szenen-Verwaltung (project.scenes) ist die Quelle, der DALI-Tab zeigt alle
Szenen auf der Szenenabruf-GA des Gateways (KNX-Szene N = DALI-Szene N-1) und
schreibt Aenderungen dorthin zurueck.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.dali_config import DaliGateway, DaliScene
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.services.dali_service import DaliService
from knix_arranger.services.scene_addressing import group_named_scenes
from knix_arranger.ui.views.dali_config_view import DaliConfigView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project() -> KnxProject:
    """Nachbau "Test Musik": Szene "Komponieren" (Nr. 1, erkannt) und die
    von Hand angelegte "Üben" (Nr. 2, Aktion auf 1/0/15)."""
    project = KnxProject(name="Test Musik")
    mg = MiddleGroup(number=0, name="Licht")
    mg.group_addresses = [GroupAddress(
        main_group=1, middle_group=0, sub_group=15, designation="LDA_M01_01 SZENE",
        gewerk_code="LDA", function_name="SZENE", room_id="room-m01",
    )]
    hg = MainGroup(number=1, name="EG")
    hg.middle_groups = [mg]
    project.group_addresses = GroupAddressStructure()
    project.group_addresses.main_groups = [hg]
    project.scenes = [
        Scene(name="ZENTRAL Szenenaufruf", scene_number=0, scope="central",
              is_detected=True, source_ga_addresses=["0/4/2"]),
        Scene(name="Komponieren", scene_number=1, scope="apartment", scope_id="apt-1",
              is_detected=True, source_ga_addresses=["1/0/15"]),
        Scene(name="Üben", scene_number=2, scope="apartment", scope_id="apt-1",
              actions=[SceneAction(group_address="Licht", ga_address="1/0/15")]),
    ]
    return project


def _gw(scenes=None) -> DaliGateway:
    gw = DaliGateway(gateway_device_id="dev-1", name="GW", ga_scene="1/0/15")
    gw.scenes = scenes or []
    return gw


def _dali(gw) -> list[tuple[int, str]]:
    return [(s.number, s.name) for s in gw.scenes]


class TestSyncScenes:
    def test_project_scenes_appear_as_dali_scenes(self):
        project, gw = _project(), _gw()
        DaliService().sync_scenes(project, gw)
        assert _dali(gw) == [(0, "Komponieren"), (1, "Üben")]
        assert gw.scenes_synced

    def test_default_placeholders_are_not_migrated(self):
        project = _project()
        gw = _gw([DaliScene(0, "Präsenz"), DaliScene(1, "Putzen"),
                  DaliScene(2, "Nacht"), DaliScene(3, "Aus")])
        DaliService().sync_scenes(project, gw)
        assert _dali(gw) == [(0, "Komponieren"), (1, "Üben")]
        assert len(project.scenes) == 3

    def test_own_dali_scenes_are_migrated_once_project_wins_on_conflict(self):
        project = _project()
        gw = _gw([DaliScene(0, "Hell"), DaliScene(5, "Konzert")])
        svc = DaliService()
        svc.sync_scenes(project, gw)
        # "Hell" kollidiert mit Komponieren (KNX 1) -> Szenen-Verwaltung gilt
        assert _dali(gw) == [(0, "Komponieren"), (1, "Üben"), (5, "Konzert")]
        konzert = next(s for s in project.scenes if s.name == "Konzert")
        assert konzert.scene_number == 6
        assert konzert.source_ga_addresses == ["1/0/15"]
        assert (konzert.scope, konzert.scope_id) == ("apartment", "apt-1")
        # In der Szenen-Verwaltung gelöscht -> bleibt gelöscht (keine Wiederbelebung)
        project.scenes.remove(konzert)
        svc.sync_scenes(project, gw)
        assert _dali(gw) == [(0, "Komponieren"), (1, "Üben")]

    def test_without_scene_ga_nothing_changes(self):
        project = _project()
        gw = _gw([DaliScene(0, "Lokal")])
        gw.ga_scene = ""
        DaliService().sync_scenes(project, gw)
        assert _dali(gw) == [(0, "Lokal")]
        assert not gw.scenes_synced

    def test_only_knx_scenes_1_to_16_are_mirrored(self):
        project = _project()
        project.scenes.append(Scene(name="Weit", scene_number=20,
                                    source_ga_addresses=["1/0/15"]))
        gw = _gw()
        DaliService().sync_scenes(project, gw)
        assert [n for n, _ in _dali(gw)] == [0, 1]


class TestDaliTabEditsGoToSceneManagement:
    def test_add_rename_remove_default(self):
        project, gw, svc = _project(), _gw(), DaliService()
        svc.sync_scenes(project, gw)

        new = svc.add_scene(project, gw)
        assert new.scene_number == 3 and new.name == "Neue Szene"
        assert new in project.scenes
        # an 1/0/15 gebunden -> keine zusätzlich generierte Szenenaufruf-GA
        assert "Neue Szene" not in [
            s.name for _, (_, grp) in group_named_scenes(project.scenes, None).items()
            for s in grp
        ]

        svc.rename_scene(project, gw, 2, "Aufnahme")
        assert new.name == "Aufnahme"
        assert (2, "Aufnahme") in _dali(gw)

        assert svc.remove_scenes(project, gw, {2}) == 1
        assert new not in project.scenes

        added = svc.add_default_scenes(project, gw)
        # DALI 0/1 sind durch Komponieren/Üben belegt -> nur Nacht, Aus
        assert added == 2
        assert _dali(gw) == [(0, "Komponieren"), (1, "Üben"), (2, "Nacht"), (3, "Aus")]

    def test_fallback_scope_from_ga_room(self):
        project = KnxProject(name="Leer")
        project.group_addresses = _project().group_addresses
        gw, svc = _gw(), DaliService()
        scene = svc.add_scene(project, gw)
        assert (scene.scope, scene.scope_id) == ("room", "room-m01")
        assert scene.actions[0].group_address == "LDA_M01_01 SZENE"


class TestDaliConfigView:
    def _view(self):
        project = _project()
        view = DaliConfigView(project)
        gw = _gw()
        view._current_gw = gw
        view._populate_scenes_table(gw)
        return view, project, gw

    def test_table_shows_synced_scenes_with_knx_number(self):
        view, _, _ = self._view()
        t = view._scenes_table
        rows = [(t.item(r, 0).text(), t.item(r, 1).text(), t.item(r, 2).text())
                for r in range(t.rowCount())]
        assert rows == [("0", "Komponieren", "1"), ("1", "Üben", "2")]
        assert "Szenen-Verwaltung" in view._scenes_hint.text()

    def test_inline_rename_writes_to_scene_management(self):
        view, project, _ = self._view()
        view._scenes_table.item(1, 1).setText("Proben")
        assert project.scenes[2].name == "Proben"

    def test_remove_asks_and_removes_from_scene_management(self):
        view, project, gw = self._view()
        view._scenes_table.selectRow(1)
        with patch("knix_arranger.ui.views.dali_config_view.QMessageBox.question",
                   return_value=QMessageBox.Yes) as ask:
            view._remove_scene()
        ask.assert_called_once()
        assert [s.name for s in project.scenes] == ["ZENTRAL Szenenaufruf", "Komponieren"]
        assert _dali(gw) == [(0, "Komponieren")]
