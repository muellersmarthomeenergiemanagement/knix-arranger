"""
Tests fuer den von Hand festgelegten GA-Bedarf in der Materialliste
(frei belegbare Gateways, z.B. Viessmann Vitogate) und den Erhalt der
Produktwerte beim Neuaufbau aus der Topologie.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication

from knix_arranger.models.material_list import MaterialEntry, MaterialList
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.ui.views.material_list_view import MaterialListView, _COL_GA


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_gateway() -> KnxProject:
    project = KnxProject(name="Test")
    device = Device(device_type="other", product="Gateway", physical_address="1.1.1",
                    manufacturer="Viessmann Werke", order_number="Z012827")
    line = Line(name="Linie 1", line_number=1)
    line.devices = [device]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    project.topology = Topology()
    project.topology.areas = [area]
    return project


def _gateway_entry(view: MaterialListView) -> MaterialEntry:
    return next(e for e in view._material_list.entries if e.order_number == "Z012827")


def _select(view: MaterialListView, entry: MaterialEntry) -> None:
    for row in range(view._table.rowCount()):
        if view._table.item(row, 0).data(0x0100) == entry.id:  # Qt.UserRole
            view._table.selectRow(row)
            return
    raise AssertionError("Zeile nicht gefunden")


class TestModel:
    def test_override_roundtrip(self):
        entry = MaterialEntry(ga_min=1500, ga_max=1500, ga_override=40)
        assert MaterialEntry.from_dict(entry.to_dict()).ga_override == 40

    def test_old_project_files_have_no_override(self):
        data = MaterialEntry(ga_min=3, ga_max=5).to_dict()
        del data["ga_override"]
        assert MaterialEntry.from_dict(data).ga_override is None


class TestView:
    def _view(self):
        view = MaterialListView()
        view.set_project(_project_with_gateway())
        entry = _gateway_entry(view)
        entry.ga_min = entry.ga_max = 1500
        view._rebuild_table()
        return view, entry

    def test_set_override_via_dialog(self):
        view, entry = self._view()
        _select(view, entry)
        assert view._btn_ga.isEnabled()
        with patch("knix_arranger.ui.views.material_list_view.QInputDialog.getText",
                   return_value=("40", True)):
            view._set_ga_override()
        entry = _gateway_entry(view)
        assert entry.ga_override == 40
        assert entry.ga_min == 1500  # KNXPROD-Wert bleibt erhalten
        _select(view, entry)
        row = view._table.selectionModel().selectedRows()[0].row()
        assert view._table.item(row, _COL_GA).text() == "40 (manuell)"

    def test_empty_input_restores_knxprod_value(self):
        view, entry = self._view()
        entry.ga_override = 40
        view._rebuild_table()
        _select(view, entry)
        with patch("knix_arranger.ui.views.material_list_view.QInputDialog.getText",
                   return_value=("", True)):
            view._set_ga_override()
        assert _gateway_entry(view).ga_override is None

    def test_invalid_input_keeps_value(self):
        view, entry = self._view()
        entry.ga_override = 40
        view._rebuild_table()
        _select(view, entry)
        with patch("knix_arranger.ui.views.material_list_view.QInputDialog.getText",
                   return_value=("viele", True)), \
             patch("knix_arranger.ui.views.material_list_view.QMessageBox.warning"):
            view._set_ga_override()
        assert _gateway_entry(view).ga_override == 40

    def test_values_survive_rebuild_from_topology(self):
        """Regression: set_project() baut die Topologie-Positionen neu auf --
        dabei gingen Kanäle und GA-Bedarf (inkl. manuellem Wert) verloren."""
        view, entry = self._view()
        entry.ga_override = 40
        entry.assigned_channels = 1
        project = view._project

        reopened = MaterialListView()
        reopened.set_project(project)
        entry = _gateway_entry(reopened)
        assert (entry.ga_min, entry.ga_max, entry.ga_override, entry.assigned_channels) == (
            1500, 1500, 40, 1)
