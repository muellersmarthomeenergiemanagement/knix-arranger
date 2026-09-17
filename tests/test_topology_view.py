"""
Tests fuer TopologyView._add_sensor_function_items (FA-1007).

Aktoren zeigten in der Topologie-Ansicht schon Kanal-Details, Sensoren/Taster
blieben aber immer flache Blaetter ohne Kinder -- Regression/Symmetrie-Fix:
Sensoren zeigen jetzt dieselben Funktions-Details wie in Schritt 9, gruppiert
nach physischer Taste (sf_id), inkl. der Fremdsteuerung-Rolle.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Bedienelement, FunctionAssignment,
)
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.ui.views.topology_view import TopologyView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_areal_topology():
    room = Room(number="02", name="Waschkeller")
    be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.28", channels=4)
    be.function_assignments = [
        FunctionAssignment(button_channel="Taste 1, links", function_ga="1/0/0",
                            description="Taste 1, links", role="befehl", sf_id="sf1"),
        FunctionAssignment(button_channel="Taste 1, links", function_ga="1/7/0",
                            description="Taste 1, links, Signal-LED", role="rueckmeldung", sf_id="sf1"),
        FunctionAssignment(button_channel="Nachtabsenkung LED's", function_ga="0/4/250",
                            description="Nachtabsenkung LED's", role="fremdsteuerung", sf_id="sf2"),
    ]
    room.bedienelemente.append(be)
    apt = Apartment(name="UG", rooms=[room])
    floor = Floor(name="Untergeschoss", short_code="UG", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    device = Device(physical_address="1.1.28", device_type="sensor",
                     product="Taster EDIZIOdue 1-8fach", room_id=room.id)
    line = Line(line_number=1, name="HL")
    line.devices = [device]
    line.assigned_room_ids = [room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    return areal, topology


def _find_device_item(tree, addr: str):
    def walk(item):
        if item.text(1) == addr:
            return item
        for i in range(item.childCount()):
            found = walk(item.child(i))
            if found is not None:
                return found
        return None

    for i in range(tree.topLevelItemCount()):
        found = walk(tree.topLevelItem(i))
        if found is not None:
            return found
    return None


class TestTopologyViewSensorFunctionItems:
    def test_sensor_device_gets_channel_children(self):
        areal, topology = _project_areal_topology()
        view = TopologyView()
        view._areal = areal
        view.set_topology(topology)

        dev_item = _find_device_item(view._tree, "1.1.28")
        assert dev_item is not None
        assert dev_item.childCount() == 2  # Taste 1, links + Fremdsteuerung

    def test_button_and_feedback_grouped_under_one_channel(self):
        areal, topology = _project_areal_topology()
        view = TopologyView()
        view._areal = areal
        view.set_topology(topology)

        dev_item = _find_device_item(view._tree, "1.1.28")
        taste1 = next(
            dev_item.child(i) for i in range(dev_item.childCount())
            if dev_item.child(i).text(0) == "Taste 1, links"
        )
        assert taste1.childCount() == 2
        assert {taste1.child(0).text(0)[:6], taste1.child(1).text(0)[:6]} == {"Befehl", "Rückme"[:6]}

    def test_fremdsteuerung_labeled_separately(self):
        areal, topology = _project_areal_topology()
        view = TopologyView()
        view._areal = areal
        view.set_topology(topology)

        dev_item = _find_device_item(view._tree, "1.1.28")
        fremd = next(
            dev_item.child(i) for i in range(dev_item.childCount())
            if dev_item.child(i).text(0) == "Fremdsteuerung: Nachtabsenkung LED's"
        )
        assert fremd.childCount() == 1
        assert fremd.child(0).text(0) == "Fremdsteuerung: Nachtabsenkung LED's"

    def test_no_areal_leaves_sensor_as_flat_leaf(self):
        """Ohne areal (z.B. set_topology() allein, kein set_project()) bleibt
        der Sensor ein flaches Blatt -- kein Absturz, kein falscher Zustand."""
        _, topology = _project_areal_topology()
        view = TopologyView()
        view.set_topology(topology)

        dev_item = _find_device_item(view._tree, "1.1.28")
        assert dev_item is not None
        assert dev_item.childCount() == 0


class TestTopologyViewGaAddressResolution:
    """FA-1502c: wizard-geplante (Gewerk-basierte) function_assignments
    speichern in function_ga nur die GA-Bezeichnung, keine Adressnummer --
    ohne Aufloesung ueber die GA-Struktur fehlte die Gruppenadressnummer bei
    Projekten ohne ETS-Import."""

    def test_pure_designation_gets_address_prefixed(self):
        from knix_arranger.models.group_address import (
            GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
        )

        room = Room(number="E01", name="Wohnzimmer")
        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.5", channels=1)
        be.function_assignments = [
            FunctionAssignment(button_channel="Taste", function_ga="LD_E01_01 E/A",
                                description="Licht schalten", role="befehl", sf_id="sf1"),
        ]
        room.bedienelemente.append(be)
        apt = Apartment(name="EG", rooms=[room])
        floor = Floor(name="EG", short_code="EG", apartments=[apt])
        wing = Wing(name="Haupt", floors=[floor])
        building = Building(name="Haus", wings=[wing])
        areal = Areal(buildings=[building])

        device = Device(physical_address="1.1.5", device_type="sensor", room_id=room.id)
        line = Line(line_number=1, name="HL")
        line.devices = [device]
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        ga_structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="Licht")
        mg = MiddleGroup(number=0, name="EG")
        hg.middle_groups.append(mg)
        ga_structure.main_groups.append(hg)
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0, designation="LD_E01_01 E/A",
        ))

        view = TopologyView()
        view._areal = areal
        view.set_topology(topology)
        view.set_group_addresses(ga_structure)

        dev_item = _find_device_item(view._tree, "1.1.5")
        ch_item = dev_item.child(0)
        fa_row = ch_item.child(0)
        assert fa_row.text(1) == "2/0/0  LD_E01_01 E/A"
