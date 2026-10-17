"""
GA in Szenen aufnehmen (FA-1816): welche Szenen die GA erreichen, Werte
setzen, ändern, entfernen; Dialog aus der Baumansicht.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.operation_check import unoperated_elements
from knix_arranger.services.scene_membership import (
    scene_slots, set_scene_values, value_choices,
)
from knix_arranger.services.topology_engine import TopologyEngine


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _project(gewerk_catalog):
    technik = Room(number="U02", name="Technik")
    technik.gewerk_assignments = [GewerkAssignment(gewerk_code="SF", count=1)]
    studio_room = Room(number="U10", name="Studio")
    wohnung = Apartment(name="Wohnung", rooms=[technik])
    studio = Apartment(name="Studio", rooms=[studio_room])
    floor = Floor(name="UG", short_code="UG", main_group_number=4,
                  apartments=[wohnung, studio])
    project = KnxProject(name="Szenen")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    project.scenes = [
        Scene(name="Anwesend", scene_number=1, scope="apartment", scope_id=wohnung.id),
        Scene(name="Abwesend", scene_number=2, scope="apartment", scope_id=wohnung.id),
        Scene(name="Anwesend", scene_number=1, scope="apartment", scope_id=studio.id),
        Scene(name="Alles aus", scene_number=10, scope="central"),
    ]
    project.topology = TopologyEngine().calculate_topology(project.areal)
    regenerate_addresses(project)
    return project


def _ea(project):
    return next(g for g in project.group_addresses.all_addresses()
                if g.gewerk_code == "SF" and g.function_name == "E/A")


def test_slots_reach_by_scope(gewerk_catalog):
    project = _project(gewerk_catalog)
    slots = {(s.scene.name, s.scene.scope_id == project.scenes[2].scope_id): s
             for s in scene_slots(project, _ea(project))}
    assert slots[("Anwesend", False)].reaches          # Wohnung
    assert slots[("Abwesend", False)].reaches
    assert not slots[("Anwesend", True)].reaches       # Studio
    assert slots[("Alles aus", False)].reaches         # zentral
    assert all(s.value is None for s in slots.values())
    assert value_choices(_ea(project)) == ["Ein", "Aus"]


def test_set_update_remove(gewerk_catalog):
    project = _project(gewerk_catalog)
    ea = _ea(project)
    anwesend, abwesend = project.scenes[0], project.scenes[1]
    assert any(u.ga is ea for u in unoperated_elements(project))

    assert set_scene_values(project, ea, {anwesend.id: "Ein", abwesend.id: "Aus"}) == 2
    assert (anwesend.actions[-1].ga_address, anwesend.actions[-1].value) == (ea.address, "Ein")
    assert not any(u.ga is ea for u in unoperated_elements(project))

    # Wert ändern, keine doppelte Aktion
    assert set_scene_values(project, ea, {anwesend.id: "Aus"}) == 1
    assert [a.value for a in anwesend.actions if a.ga_address == ea.address] == ["Aus"]
    assert set_scene_values(project, ea, {anwesend.id: "Aus"}) == 0

    # entfernen; fremde Aktionen bleiben
    anwesend.actions.append(SceneAction(group_address="Licht", ga_address="4/0/0", value="Ein"))
    assert set_scene_values(project, ea, {anwesend.id: None}) == 1
    assert [a.ga_address for a in anwesend.actions] == ["4/0/0"]


def test_action_by_designation_is_recognised(gewerk_catalog):
    project = _project(gewerk_catalog)
    ea = _ea(project)
    project.scenes[0].actions.append(SceneAction(group_address=ea.designation, value="Ein"))
    slot = next(s for s in scene_slots(project, ea) if s.scene is project.scenes[0])
    assert slot.value == "Ein"
    set_scene_values(project, ea, {project.scenes[0].id: "Aus"})
    assert project.scenes[0].actions[0].ga_address == ea.address    # nachgetragen


def test_dialog(gewerk_catalog):
    from knix_arranger.ui.dialogs.ga_scene_dialog import GaSceneDialog
    project = _project(gewerk_catalog)
    ea = _ea(project)
    dialog = GaSceneDialog(project, ea)
    names = [dialog._table.item(r, 3).text() for r in range(dialog._table.rowCount())
             if not dialog._table.isRowHidden(r)]
    assert sorted(names) == ["Abwesend", "Alles aus", "Anwesend"]     # ohne Studio
    dialog._show_all.setChecked(True)
    assert not any(dialog._table.isRowHidden(r) for r in range(dialog._table.rowCount()))

    row = next(r for r, s in enumerate(dialog._slots) if s.scene is project.scenes[0])
    dialog._boxes[row].setChecked(True)
    dialog._values[row].setEditText("Ein")
    values = dialog.values()
    assert values[project.scenes[0].id] == "Ein"
    assert values[project.scenes[1].id] is None
