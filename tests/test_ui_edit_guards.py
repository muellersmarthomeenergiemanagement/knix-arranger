"""
Tests fuer die zuletzt geschlossenen Sichtbarkeits-/Robustheits-Luecken:
- FA-2704: Secure-inkompatible Geraete in der Topologie-Ansicht markieren
- FA-2603: Leitungslaengen-Warnungen im Topologie-Prinzipschema
- Stille Eingabefehler bei Preis (quotation_view) und Menge (material_list_view)
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.models.knx_secure import KnxSecureConfig, DeviceSecureInfo
from knix_arranger.ui.views.topology_view import TopologyView, _COLOR_SECURE_MISSING
from knix_arranger.ui.views.topology_diagram_view import (
    TopologyDiagramView, _C_LINE, _C_LINE_WARN, _C_LINE_ERROR,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _topo_with_devices() -> Topology:
    topo = Topology()
    line = Line(name="Linie 1", line_number=1)
    dev_insecure = Device(id="d1", device_type="sensor", product="Taster", physical_address="1.1.1")
    dev_secure = Device(id="d2", device_type="actor", product="Schaltaktor", physical_address="1.1.2")
    dev_unchecked = Device(id="d3", device_type="sensor", product="Praesenzmelder", physical_address="1.1.3")
    line.devices = [dev_insecure, dev_secure, dev_unchecked]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    topo.areas = [area]
    return topo


class TestFA2704SecureMarkierung:
    def test_geraet_ohne_secure_wird_rot_markiert(self):
        topo = _topo_with_devices()
        ks = KnxSecureConfig(enabled=True)
        ks.device_infos["d1"] = DeviceSecureInfo(device_id="d1", secure_supported=False)
        ks.device_infos["d2"] = DeviceSecureInfo(device_id="d2", secure_supported=True)

        view = TopologyView()
        view.set_topology(topo)
        view.set_knx_secure(ks)

        colors = self._device_colors(view)
        assert colors["Taster"] == _COLOR_SECURE_MISSING.name()
        assert colors["Schaltaktor"] != _COLOR_SECURE_MISSING.name()

    def test_ungeprueftes_geraet_wird_nicht_markiert(self):
        """Ohne Eintrag in device_infos wird nicht geraten -- keine rote Markierung."""
        topo = _topo_with_devices()
        ks = KnxSecureConfig(enabled=True)  # device_infos bleibt leer
        view = TopologyView()
        view.set_topology(topo)
        view.set_knx_secure(ks)

        colors = self._device_colors(view)
        assert colors["Praesenzmelder"] != _COLOR_SECURE_MISSING.name()

    def test_ohne_aktiviertes_secure_keine_markierung(self):
        topo = _topo_with_devices()
        ks = KnxSecureConfig(enabled=False)
        ks.device_infos["d1"] = DeviceSecureInfo(device_id="d1", secure_supported=False)
        view = TopologyView()
        view.set_topology(topo)
        view.set_knx_secure(ks)

        colors = self._device_colors(view)
        assert colors["Taster"] != _COLOR_SECURE_MISSING.name()

    @staticmethod
    def _device_colors(view: TopologyView) -> dict[str, str]:
        result = {}
        root = view._tree.invisibleRootItem()

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                result[child.text(0)] = child.foreground(0).color().name()
                walk(child)
        walk(root)
        return result


class TestFA2603Kabellaengen:
    def _boxes_by_label(self, view, project):
        view.set_project(project)
        return {
            it.toolTip().splitlines()[0]: it.brush().color()
            for it in view._scene.items()
            if hasattr(it, "toolTip") and it.toolTip()
        }

    def test_linie_ok_bleibt_neutral(self):
        topo = Topology()
        line = Line(name="Linie OK", line_number=1, trunk_length=100.0)
        area = Area(area_number=1, name="Bereich 1")
        area.lines = [line]
        topo.areas = [area]
        project = KnxProject(name="X")
        project.topology = topo

        view = TopologyDiagramView()
        boxes = self._boxes_by_label(view, project)
        label = next(k for k in boxes if "Linie OK" in k)
        assert boxes[label] == _C_LINE

    def test_linie_warnung_wird_orange(self):
        topo = Topology()
        line = Line(name="Linie Warn", line_number=1, trunk_length=600.0)  # > 560 m
        area = Area(area_number=1, name="Bereich 1")
        area.lines = [line]
        topo.areas = [area]
        project = KnxProject(name="X")
        project.topology = topo

        view = TopologyDiagramView()
        boxes = self._boxes_by_label(view, project)
        label = next(k for k in boxes if "Linie Warn" in k)
        assert boxes[label] == _C_LINE_WARN

    def test_linie_fehler_wird_rot(self):
        topo = Topology()
        line = Line(name="Linie Fehler", line_number=1, trunk_length=800.0)  # > 700 m
        area = Area(area_number=1, name="Bereich 1")
        area.lines = [line]
        topo.areas = [area]
        project = KnxProject(name="X")
        project.topology = topo

        view = TopologyDiagramView()
        boxes = self._boxes_by_label(view, project)
        label = next(k for k in boxes if "Linie Fehler" in k)
        assert boxes[label] == _C_LINE_ERROR


class TestStilleEingabefehler:
    def test_quotation_ungueltiger_preis_wird_nicht_still_verworfen(self):
        from knix_arranger.ui.views.quotation_view import QuotationView
        from knix_arranger.models.quotation import QuotationRequest, QuotationItem

        item = QuotationItem(order_number="X1", unit_price=12.5, quantity=2)
        qr = QuotationRequest(items=[item])

        view = QuotationView()
        # QTableWidgetItem.row()/column() liefern -1 ohne Tabellenzugehoerigkeit,
        # daher direkt in eine echte Zelle der (leeren) Tabelle setzen. Signale
        # waehrend des Aufbaus blockieren, damit itemChanged nicht vorzeitig
        # (mit ungemocktem _get_selected_request) feuert.
        view._items_table.blockSignals(True)
        view._items_table.setRowCount(1)
        view._items_table.setColumnCount(7)
        table_item = QTableWidgetItem("nicht-eine-zahl")
        view._items_table.setItem(0, 5, table_item)
        view._items_table.blockSignals(False)

        with patch.object(view, "_get_selected_request", return_value=qr):
            with patch("knix_arranger.ui.views.quotation_view.QMessageBox.warning") as mock_warn:
                view._on_item_changed(table_item)
                mock_warn.assert_called_once()

        assert item.unit_price == 12.5  # unveraendert
        assert table_item.text() == "12.50"  # Anzeige auf Modellwert zurueckgesetzt

    def test_material_list_ungueltige_menge_wird_nicht_still_verworfen(self):
        from knix_arranger.ui.views.material_list_view import MaterialListView
        from knix_arranger.models.material_list import MaterialList, MaterialEntry

        entry = MaterialEntry(quantity=3, category="Sonstiges")
        mat_list = MaterialList(entries=[entry])

        view = MaterialListView()
        view._material_list = mat_list
        view._table.blockSignals(True)
        view._table.setRowCount(1)
        view._table.setColumnCount(1)
        qty_item = QTableWidgetItem("abc")
        qty_item.setData(Qt.UserRole, entry.id)
        view._table.setItem(0, 0, qty_item)
        view._table.blockSignals(False)

        with patch("knix_arranger.ui.views.material_list_view.QMessageBox.warning") as mock_warn:
            with patch.object(view, "_rebuild_table") as mock_rebuild:
                view._on_item_changed(qty_item)
                mock_warn.assert_called_once()
                mock_rebuild.assert_called_once()

        assert entry.quantity == 3  # unveraendert
