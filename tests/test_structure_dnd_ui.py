"""
Oberflaechen-Pfade von Ziehen und Ablegen (FA-1015 a-d): die Ansichten
liefern die richtigen Nutzdaten und fuehren das Ablegen mit Undo-Punkt aus.
Das Ziehen selbst (QDrag.exec) laeuft ohne Bildschirm nicht; geprueft werden
die Rueckrufe, die das Drag-Widget aufruft.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import Apartment, Floor
from knix_arranger.ui.views.address_tree_view import AddressTreeView
from knix_arranger.ui.views.building_view import BuildingView
from knix_arranger.ui.views.gewerk_view import GewerkView
from knix_arranger.ui.widgets.drag_drop import _HIGHLIGHT

from tests.test_renumber_service import _project, _by_designation


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _items(tree):
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.child(i) for i in range(item.childCount()))


def test_building_view_room_to_other_floor():
    project = _project()
    og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3)
    og.apartments = [Apartment(name="OG")]
    project.areal.buildings[0].wings[0].floors.append(og)
    view = BuildingView()
    bus = MagicMock()
    view.set_bus(bus)
    view.set_areal(project.areal)
    changed = MagicMock()
    view.structure_changed.connect(changed)

    tree = view._tree
    room_item = next(i for i in _items(tree) if i.text(1) == "Raum" and "Kueche" in i.text(0))
    floor_item = next(i for i in _items(tree) if i.text(1) == "Stockwerk" and "OG" in i.text(0))
    kueche = view._drag_data(room_item)
    assert kueche is project.all_rooms[1]
    assert view._drag_data(floor_item) is None

    target = tree.target_data(floor_item)
    assert view._can_drop([kueche], target)
    view._on_drop([kueche], target)
    assert kueche in og.apartments[0].rooms
    bus.begin_change.assert_called_once()
    changed.assert_called_once()


def test_gewerk_view_catalog_and_row_drop():
    project = _project()
    view = GewerkView()
    view.set_bus(MagicMock())
    view.set_project(project)
    wohnen, kueche = project.all_rooms

    table = view._table
    row = next(r for r in range(table.rowCount())
               if table.item(r, 2).text() == "Kueche")
    target = table.target_data(table.item(row, 3))
    assert target is kueche

    assert view._can_drop([("code", "J")], kueche)
    view._on_drop([("code", "J")], kueche)
    assert [g.gewerk_code for g in kueche.gewerk_assignments] == ["LD", "J"]

    # Jalousie aus dem Wohnen ziehen: Küche hat jetzt schon J -> nicht erlaubt
    wohnen_j = next(r for r in range(table.rowCount())
                    if table.item(r, 2).text() == "Wohnen" and table.item(r, 4).text() == "J")
    payload = view._drag_data(table.item(wohnen_j, 5))
    assert payload[0] == "assignment" and payload[1] is wohnen
    assert not view._can_drop([payload], kueche)


def test_address_tree_swap_and_highlight():
    project = _project()
    view = AddressTreeView()
    bus = MagicMock()
    view.set_bus(bus)
    view.set_project(project)
    view.set_structure(project.group_addresses)
    modified = MagicMock()
    view.ga_modified.connect(modified)

    tree = view._tree
    by_addr = {i.text(0): i for i in _items(tree)}
    ea = view._drag_data(by_addr["2/0/0"])
    assert ea is _by_designation(project, "LD_E01_01 E/A (Wohnen)")
    assert view._drag_data(by_addr["0/0/1"]) is None   # Zentral-GA

    target = tree.target_data(by_addr["2/0/2"])
    assert view._can_drop([ea], target)
    view._on_drop([ea], target)
    assert ea.address == "2/0/2"
    modified.assert_called_once()

    # Ziel-Hervorhebung wird wieder entfernt
    item = next(i for i in _items(view._tree) if i.text(0) == "2/0/5")
    before = item.background(1)
    tree._set_hover(item)
    assert item.background(1).color() == _HIGHLIGHT
    tree._set_hover(None)
    assert item.background(1) == before


def test_address_tree_no_drag_when_transferred():
    project = _project()
    project.ets_transferred = "2026-10-07"
    view = AddressTreeView()
    view.set_project(project)
    view.set_structure(project.group_addresses)
    item = next(i for i in _items(view._tree) if i.text(0) == "2/0/0")
    assert view._drag_data(item) is None
    assert "Ziehen" not in view._hint.text()


def test_topology_view_device_to_other_line():
    from knix_arranger.ui.views.topology_view import TopologyView
    from tests.test_structure_dnd import _topology
    project = _project()
    project.topology, l1, l2, sensor = _topology(imported=True)
    view = TopologyView()
    view.set_bus(MagicMock())
    view.set_project(project)

    tree = view._tree
    dev_item = next(i for i in _items(tree) if i.text(1) == "1.1.101")
    other = next(i for i in _items(tree) if i.text(1) == "1.2.101")
    assert view._drag_data(dev_item) is sensor
    assert tree.target_data(other) is l2          # Gerät steht für seine Linie
    assert view._can_drop([sensor], l2)
    view._apply_line_move([sensor], l2)
    assert sensor in l2.devices and sensor.physical_address == "1.2.1"
