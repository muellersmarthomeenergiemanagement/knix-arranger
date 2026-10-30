"""
Tests FA-1011a: aus der Topologie zur Gruppenadresse springen und aus den
Gruppenadressen zu den verknüpften Geräten in der Topologie.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.topology import (
    Topology, Area, Line, Device, CommunicationObject,
)
from knix_arranger.ui.topology_jump import add_topology_menu
from knix_arranger.ui.views.address_tree_view import AddressTreeView
from knix_arranger.ui.views.topology_view import TopologyView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _setup():
    actor = Device(physical_address="1.1.1", device_type="actor", product="Schaltaktor")
    actor.communication_objects = [
        CommunicationObject(object_number=1, name="Ausgang A", object_function="Schalten",
                            connected_gas=["1/0/0"]),
        CommunicationObject(object_number=2, name="Ausgang A", object_function="Status",
                            connected_gas=["1/1/0"]),
    ]
    # zweiter Aktor, der dieselben GAs mithört (Sensoren zeigen ihre GAs
    # nur über die Tastenbelegung, siehe test_topology_view)
    sensor = Device(physical_address="1.1.2", device_type="actor", product="Dimmaktor")
    sensor.communication_objects = [
        CommunicationObject(object_number=5, name="Kanal 1", connected_gas=["1/0/0", "1/1/0"]),
    ]
    line = Line(line_number=1, name="HL")
    line.devices = [actor, sensor]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area], is_imported=True)

    structure = GroupAddressStructure()
    hg = MainGroup(number=1, name="Licht")
    for nr in (0, 1):
        mg = MiddleGroup(number=nr, name=f"MG {nr}")
        mg.group_addresses.append(GroupAddress(
            main_group=1, middle_group=nr, sub_group=0, designation=f"L_EG_01_01 {nr}"))
        hg.middle_groups.append(mg)
    structure.main_groups.append(hg)

    view = TopologyView()
    view.set_group_addresses(structure)
    view.set_topology(topology)
    return view, actor, sensor, structure


def _row(view, device, address):
    from knix_arranger.services.multi_ga_check import ga_address_of
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(view._tree)
    while it.value():
        item = it.value()
        d = item.data(0, 256)
        if (isinstance(d, tuple) and d[0] == "ko_ga" and d[1] is device
                and ga_address_of(item.text(1)) == address):
            return item
        it += 1
    return None


class TestTopologyToGa:
    def test_jump_entry_on_ga_row(self):
        view, actor, _s, _st = _setup()
        menu = QMenu()
        act, address = view._add_jump_to_ga(menu, _row(view, actor, "1/0/0"))
        assert address == "1/0/0"
        assert act.text() == "Zur Gruppenadresse 1/0/0 springen"

    def test_no_jump_entry_on_device_row(self):
        view, actor, _s, _st = _setup()
        from knix_arranger.ui.views.topology_view import _device_item_of
        dev_item = _device_item_of(_row(view, actor, "1/0/0"))
        assert view._add_jump_to_ga(QMenu(), dev_item) is None

    def test_tree_view_selects_jumped_ga(self):
        _v, _a, _s, structure = _setup()
        tree = AddressTreeView()
        tree.set_structure(structure)
        assert tree.select_address("1/1/0")
        assert tree._tree.currentItem().text(0) == "1/1/0"


class TestGaToTopology:
    def test_linked_devices_lists_each_device_and_ko(self):
        view, actor, sensor, _st = _setup()
        found = view.linked_devices("1/0/0")
        assert [d for d, _l in found] == [actor, sensor]
        assert found[0][1].startswith("1.1.1 ")
        assert "Ausgang A" in found[0][1]

    def test_unlinked_address_has_no_devices(self):
        view, *_ = _setup()
        assert view.linked_devices("1/5/0") == []

    def test_select_ga_row_marks_ko_row_under_device(self):
        view, _a, sensor, _st = _setup()
        assert view.select_ga_row(sensor, "1/1/0")
        current = view._tree.currentItem()
        assert current is _row(view, sensor, "1/1/0")

    def test_select_ga_row_falls_back_to_device(self):
        view, actor, _s, _st = _setup()
        assert view.select_ga_row(actor, "1/5/0")
        assert view._tree.currentItem().text(1) == "1.1.1"

    def test_submenu_fills_on_open_and_picks_device(self):
        view, actor, sensor, _st = _setup()
        picked = []
        menu = QMenu()
        sub = add_topology_menu(menu, "1/1/0", view.linked_devices,
                                lambda d, a: picked.append((d, a)))
        sub.aboutToShow.emit()
        actions = sub.actions()
        assert len(actions) == 2
        actions[1].trigger()
        assert picked == [(sensor, "1/1/0")]

    def test_submenu_without_devices_shows_disabled_hint(self):
        view, *_ = _setup()
        menu = QMenu()
        sub = add_topology_menu(menu, "1/5/0", view.linked_devices, lambda d, a: None)
        sub.aboutToShow.emit()
        [only] = sub.actions()
        assert only.text() == "keine verknüpften Geräte"
        assert not only.isEnabled()

    def test_no_submenu_without_provider(self):
        assert add_topology_menu(QMenu(), "1/0/0", None, lambda d, a: None) is None


def test_planned_sensor_found_over_key_assignment():
    """Geplanter Taster: die GA steht in der Tastenbelegung, nicht im KO."""
    from knix_arranger.models.building import (
        Areal, Building, Wing, Floor, Apartment, Room, Bedienelement, FunctionAssignment,
    )
    room = Room(number="01", name="Wohnen")
    be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.30", channels=1)
    be.function_assignments = [FunctionAssignment(
        button_channel="Taste 1", function_ga="1/0/0", description="Licht", role="befehl",
        sf_id="sf1")]
    room.bedienelemente.append(be)
    areal = Areal(buildings=[Building(name="Haus", wings=[Wing(name="H", floors=[Floor(
        name="EG", short_code="EG", apartments=[Apartment(name="EG", rooms=[room])])])])])
    taster = Device(physical_address="1.1.30", device_type="sensor", product="Taster",
                    room_id=room.id)
    line = Line(line_number=1, name="HL")
    line.devices = [taster]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    view = TopologyView()
    view._areal = areal
    view.set_topology(Topology(areas=[area]))
    [(device, label)] = view.linked_devices("1/0/0")
    assert device is taster
    assert label == "1.1.30 Taster – Befehl: Licht"
    assert view.select_ga_row(taster, "1/0/0")
    assert view._tree.currentItem().text(0) == "Befehl: Licht"
