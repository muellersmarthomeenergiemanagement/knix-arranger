"""
Baumansicht: GAs bearbeiten in der Zelle und im Sammeldialog (FA-1003b).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.ui.dialogs.ga_bulk_edit_dialog import GaBulkEditDialog
from knix_arranger.ui.dialogs.ga_edit_dialog import GaEditDialog
from knix_arranger.ui.views.address_tree_view import (
    COL_FUNCTION, REWORKED_MARK, AddressTreeView,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _project(gewerk_catalog) -> KnxProject:
    room = Room(number="U02", name="Technik")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="H", count=1),
                               GewerkAssignment(gewerk_code="L", count=2)]
    floor = Floor(name="UG", short_code="UG", main_group_number=4,
                  apartments=[Apartment(name="Wohnung", rooms=[room])])
    project = KnxProject(name="Bearbeiten")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    regenerate_addresses(project)
    return project


def _view(project) -> AddressTreeView:
    view = AddressTreeView()
    view.set_bus(MagicMock())
    view.set_project(project)
    view.set_structure(project.group_addresses)
    return view


def _items(tree):
    it = QTreeWidgetItemIterator(tree)
    while it.value():
        yield it.value()
        it += 1


def _item(view, function: str, gewerk: str = "H"):
    return next(i for i in _items(view._tree)
                if (ga := i.data(0, view.GA_OBJECT_ROLE)) is not None
                and ga.gewerk_code == gewerk and ga.function_name == function)


def test_function_column_and_inline_edit_for_selection(gewerk_catalog):
    project = _project(gewerk_catalog)
    view = _view(project)
    item = _item(view, "STELLGROESSE")
    assert item.text(COL_FUNCTION) == "STELLGROESSE"
    assert "Befehl" in item.toolTip(COL_FUNCTION)
    address = item.text(0)

    view._commit_inline(item, "function_name", "E/A")
    QApplication.processEvents()
    item = _item(view, "E/A")
    assert item.text(0) == address
    assert item.text(COL_FUNCTION) == f"{REWORKED_MARK} E/A"
    assert "STELLGROESSE" in item.toolTip(COL_FUNCTION)

    # zwei markierte Leuchten: Beschreibung für beide
    first, second = (next(i for i in _items(view._tree)
                          if (ga := i.data(0, view.GA_OBJECT_ROLE)) is not None
                          and ga.gewerk_code == "L" and ga.function_name == "E/A"
                          and ga.element_number == n) for n in (1, 2))
    first.setSelected(True)
    second.setSelected(True)
    view._commit_inline(first, "description", "Aussen")
    QApplication.processEvents()
    lights = [g for g in project.group_addresses.all_addresses()
              if g.gewerk_code == "L" and g.function_name == "E/A" and g.element_number]
    assert {g.description for g in lights} == {"Aussen"}


def test_reset_via_view(gewerk_catalog):
    project = _project(gewerk_catalog)
    view = _view(project)
    view._commit_inline(_item(view, "IST"), "function_name", "RM")
    QApplication.processEvents()
    ga = _item(view, "RM").data(0, view.GA_OBJECT_ROLE)
    view._reset_to_plan([ga])
    assert _item(view, "IST").text(COL_FUNCTION) == "IST"


def test_bulk_dialog_only_touched_fields(gewerk_catalog):
    project = _project(gewerk_catalog)
    gas = [g for g in project.group_addresses.all_addresses()
           if g.gewerk_code == "H" and g.function_name in ("STOERUNG", "SPERREN")]
    dialog = GaBulkEditDialog(project, gas)
    assert dialog.changes() == {}
    dialog._description.setText("Rohrbegleitheizung")
    dialog._description.textEdited.emit("Rohrbegleitheizung")
    assert dialog.changes() == {"description": "Rohrbegleitheizung"}
    dialog._save()
    assert {g.description for g in gas} == {"Rohrbegleitheizung"}
    assert not dialog._gewerk.isEnabled()       # Gewerk kommt aus der Planung


def test_edit_dialog_locks_planning_fields(gewerk_catalog):
    project = _project(gewerk_catalog)
    ga = next(g for g in project.group_addresses.all_addresses()
              if g.gewerk_code == "H" and g.function_name == "STELLGROESSE")
    address = ga.address
    dialog = GaEditDialog(ga, project=project)
    assert dialog._function.isEnabled() and not dialog._room.isEnabled()
    assert not dialog._hg_spin.isEnabled()
    dialog._function.setEditText("E/A")
    assert dialog._dpt.currentText() == "DPST-1-1"
    assert dialog._role.text() == "Befehl"
    dialog._save()
    assert ga.function_name == "E/A" and ga.address == address
    assert ga.plan_function == "STELLGROESSE"
