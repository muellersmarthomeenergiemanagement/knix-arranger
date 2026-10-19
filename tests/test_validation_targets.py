"""
Validierung: Sprung zur Korrektur (FA-615a) und lesbare Spalten.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services import validation_targets as vt
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.ga_edit import set_element_profile
from knix_arranger.services.validation_engine import ValidationEngine
from knix_arranger.ui.views.validation_view import ValidationView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _project(gewerk_catalog) -> KnxProject:
    room = Room(number="U02", name="Technik")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="H", count=1),
                               GewerkAssignment(gewerk_code="L", count=1)]
    floor = Floor(name="UG", short_code="UG", main_group_number=4,
                  apartments=[Apartment(name="Wohnung", rooms=[room])])
    project = KnxProject(name="Sprung")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    line = Line(name="Linie 1", line_number=1, assigned_room_ids=[room.id])
    line.devices = [Device(device_type="actor", product="Schaltaktor 4-fach",
                           physical_address="1.1.1")]
    project.topology = Topology(areas=[Area(area_number=1, lines=[line])])
    regenerate_addresses(project)
    return project


def _issue(rule, address="", message=""):
    return {"rule_id": rule, "address": address, "message": message,
            "level": "warning", "suggestion": "", "designation": "", "details": {}}


def test_targets_by_address_kind(gewerk_catalog):
    project = _project(gewerk_catalog)
    room = project.all_rooms[0]
    assert vt.targets_for(_issue("FA-603", "4/0/0"), project)[0] == vt.Target(
        vt.GA, "4/0/0", "GA 4/0/0 in den Gruppenadressen zeigen")
    assert vt.targets_for(_issue("FA-612", "1.1.1"), project)[0].kind == vt.DEVICE
    assert vt.targets_for(_issue("FA-613", "1.1"), project)[0].kind == vt.LINE
    assert vt.targets_for(_issue("FA-411", "HG 4"), project)[0] == vt.Target(
        vt.FLOOR, "4", "Stockwerk mit HG 4 im Gebäude zeigen")
    room_targets = vt.targets_for(_issue("FA-625", "U02"), project)
    assert [t.kind for t in room_targets] == [vt.ROOM, vt.BAUHERR, vt.VIEW]
    assert room_targets[0].key == room.id
    assert vt.targets_for(_issue("FA-1813"), project)[0].key == "scenes"
    # Gerät aus dem Meldungstext (z.B. FA-611: GA fehlt in der Struktur)
    targets = vt.targets_for(_issue("FA-611", "9/9/9", "Schaltaktor 1.1.1, KO 3: ..."), project)
    assert [t.kind for t in targets] == [vt.DEVICE, vt.GA]     # Gerät, dann Mittelgruppe
    assert "Mittelgruppe 9/9" in targets[1].label
    assert vt.targets_for(_issue("FA-623"), project) == []


def test_unoperated_element_targets(gewerk_catalog):
    project = _project(gewerk_catalog)
    room = project.all_rooms[0]
    light = next(g for g in project.group_addresses.all_addresses()
                 if g.gewerk_code == "L" and g.function_name == "E/A" and g.element_number)
    targets = vt.targets_for(_issue("FA-619", light.address), project)
    assert [(t.kind, t.key) for t in targets] == [(vt.BAUHERR, room.id), (vt.GA, light.address)]

    heating = next(g for g in project.group_addresses.all_addresses()
                   if g.gewerk_code == "H" and g.element_number)
    set_element_profile(project, heating, "schalten_rm")
    ea = next(g for g in project.group_addresses.all_addresses()
              if g.gewerk_code == "H" and g.function_name == "E/A")
    targets = vt.targets_for(_issue("FA-619", ea.address), project)
    assert targets[0] == vt.Target(vt.VIEW, "scenes", "Szenen öffnen")


def _issue_items(view):
    from knix_arranger.ui.views.validation_view import _ISSUE_ROLE
    it = QTreeWidgetItemIterator(view._tree)
    while it.value():
        if isinstance(it.value().data(0, _ISSUE_ROLE), dict):
            yield it.value()
        it += 1


def test_view_jumps_and_wraps(gewerk_catalog):
    project = _project(gewerk_catalog)
    issues = ValidationEngine(project.gewerk_catalog).validate(project.group_addresses, project)
    long = "Sehr lange Meldung " * 30
    issues.append(type(issues[0])("warning", "FA-603", long, "4/0/0", "DPT ändern")
                  if issues else None)
    view = ValidationView()
    view.resize(1200, 600)
    view.set_target_provider(lambda issue: vt.targets_for(issue, project))
    jumped = []
    view.jump_requested.connect(jumped.append)
    view.set_issues([i for i in issues if i is not None])
    view.show()
    QTest.qWait(150)          # verzögerte Neuberechnung der Zeilenhöhen

    item = next(i for i in _issue_items(view) if i.text(1) == long)
    view._jump(item)
    assert jumped and jumped[0].kind == vt.GA and jumped[0].key == "4/0/0"

    assert view._tree.wordWrap()
    tree = view._tree
    used = sum(tree.columnWidth(c) for c in range(3))
    assert used < tree.viewport().width()                # keine Spalte ragt hinaus
    assert tree.visualItemRect(item).height() > tree.fontMetrics().height() * 2   # umgebrochen
    view.close()


def test_views_select_target(gewerk_catalog):
    from unittest.mock import MagicMock
    from knix_arranger.ui.views.address_tree_view import AddressTreeView
    from knix_arranger.ui.views.topology_view import TopologyView
    project = _project(gewerk_catalog)

    tree = AddressTreeView()
    tree.set_bus(MagicMock())
    tree.set_project(project)
    tree.set_structure(project.group_addresses)
    assert tree.select_address("4/0/0")
    assert tree._tree.currentItem().text(0) == "4/0/0"
    assert tree.select_address("4/0/99")                 # Lücke: Mittelgruppe 4/0
    assert tree._tree.currentItem().data(0, tree.MG_ROLE) == (4, 0)
    assert not tree.select_address("9/9/9")

    topology = TopologyView()
    topology.set_project(project)
    assert topology.select_device("1.1.1")
    assert topology.select_line("1.1")
    assert not topology.select_device("1.1.99")


def test_building_and_bauherr_select_room(gewerk_catalog):
    from knix_arranger.ui.views.bauherr_form_view import BauherrFormView
    from knix_arranger.ui.views.building_view import BuildingView
    project = _project(gewerk_catalog)
    room = project.all_rooms[0]

    building = BuildingView()
    building.set_gewerk_catalog(gewerk_catalog)
    building.set_areal(project.areal)
    assert building.select_room(room.id)
    assert building._tree.currentItem().data(0, 256)[1] is room
    assert building.select_floor(4)
    assert not building.select_room("gibt-es-nicht")

    bauherr = BauherrFormView()
    bauherr.set_project(project)
    assert bauherr.show_room(room.id)
    assert not bauherr.show_room("gibt-es-nicht")


def test_scene_action_by_address_counts_as_operation(gewerk_catalog, monkeypatch):
    """Szenen-Aktion mit eingetippter Adresse: Bezeichnung und Adresse werden
    übernommen, FA-619 gilt als erledigt."""
    from knix_arranger.models.scene import Scene
    from knix_arranger.services.operation_check import unoperated_elements
    from knix_arranger.ui.views.scene_view import SceneView
    project = _project(gewerk_catalog)
    heating = next(g for g in project.group_addresses.all_addresses()
                   if g.gewerk_code == "H" and g.element_number)
    set_element_profile(project, heating, "schalten_rm")
    ea = next(g for g in project.group_addresses.all_addresses()
              if g.gewerk_code == "H" and g.function_name == "E/A")
    scene = Scene(name="Anwesend")
    project.scenes.append(scene)
    assert any(u.ga.address == ea.address for u in unoperated_elements(project))

    view = SceneView()
    view.set_project(project)
    monkeypatch.setattr(view, "_get_selected_scene", lambda: scene)
    monkeypatch.setattr(view, "_refresh_table", lambda **_k: None)
    view._action_ga.setText(ea.address)
    view._action_value.setText("Ein")
    view._add_action()
    assert (scene.actions[-1].ga_address, scene.actions[-1].group_address) == (
        ea.address, ea.designation)
    assert not any(u.ga.address == ea.address for u in unoperated_elements(project))


def test_generated_duplicate_designation_leads_to_product(gewerk_catalog):
    """FA-625: gleiche Bezeichnungen aus den KOs eines Produkts -- KNiX ist
    die Ursache, der Sprung führt zur Produkt-/KO-Auswahl der Zuweisung."""
    project = _project(gewerk_catalog)
    room = project.all_rooms[0]
    light = next(a for a in room.gewerk_assignments if a.gewerk_code == "L")
    light.linked_product = {"manufacturer": "X", "order_number": "1", "com_objects": []}
    gas = [g for g in project.group_addresses.all_addresses() if g.assignment_id == light.id]
    gas[0].designation = gas[1].designation = "L_U02 Wert"
    issue = next(i for i in ValidationEngine(gewerk_catalog).validate(
        project.group_addresses, project=project)
        if i.rule_id == "FA-625" and i.designation == "L_U02 Wert")
    assert "von KNiX aus den KOs des Produkts erzeugt" in issue.message
    assert "Schritt 5" in issue.suggestion
    targets = vt.targets_for(issue.to_dict(), project)
    assert (targets[0].kind, targets[0].key) == (vt.PRODUCT, light.id)
    assert targets[1].kind == vt.GA
    # von Hand angelegt: wie bisher
    gas[1].is_manual = True
    issue = next(i for i in ValidationEngine(gewerk_catalog).validate(
        project.group_addresses, project=project)
        if i.rule_id == "FA-625" and i.designation == "L_U02 Wert")
    assert issue.suggestion == "Bezeichnungen eindeutig machen"
    assert vt.targets_for(issue.to_dict(), project)[0].kind == vt.GA


def test_wizard_step5_opens_product_of_assignment(gewerk_catalog, monkeypatch):
    from knix_arranger.ui.wizard.step05_gewerke import Step05Gewerke
    project = _project(gewerk_catalog)
    light = next(a for a in project.all_rooms[0].gewerk_assignments if a.gewerk_code == "L")
    step = Step05Gewerke(project)
    step.on_enter()
    opened = []
    monkeypatch.setattr(step, "_select_product", lambda room, ga: opened.append((room, ga)))
    assert step.show_focus("assignment", light.id)
    assert opened == [(project.all_rooms[0], light)]
    assert not step.show_focus("assignment", "gibt-es-nicht")
