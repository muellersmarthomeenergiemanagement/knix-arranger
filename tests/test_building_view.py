"""
Tests fuer BuildingView._devices_for_verteiler (Regression).

Zwei Verteiler desselben Typs (z.B. UV1/UV2) auf derselben physischen
KNX-Linie duerfen sich beim Anzeigen im Gebaeudestruktur-Baum nicht
gegenseitig Geraete "stehlen" -- vorher wurden Geraete ueber einen zu
weiten Praefix-Abgleich auf den bloszen Verteiler-Typ ("UV") gefunden,
der sowohl "UV1 (...)" als auch "UV2 (...)" traf.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Verteiler,
)
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.ui.views.building_view import BuildingView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_pseudo_verteiler_room(name: str, vt_type: str = "UV") -> Room:
    room = Room(number="", name=name)
    room.verteiler.append(Verteiler(name=name, verteiler_type=vt_type))
    return room


def test_two_same_type_verteiler_on_same_line_dont_share_devices():
    """UV1 und UV2, beide auf derselben Linie, muessen ihre jeweils eigenen
    Geraete zeigen -- nicht die des jeweils anderen."""
    uv1_room = _make_pseudo_verteiler_room("UV1   ( Steigzone )")
    uv2_room = _make_pseudo_verteiler_room("UV2   ( Steigzone )")

    dev1 = Device(
        physical_address="1.1.1", device_type="actor", product="Aktor 1",
        installation_location="UV1   ( Steigzone )", room_id=uv1_room.id,
    )
    dev2 = Device(
        physical_address="1.1.2", device_type="actor", product="Aktor 2",
        installation_location="UV2   ( Steigzone )", room_id=uv2_room.id,
    )
    line = Line(line_number=1, name="HL")
    line.devices = [dev1, dev2]
    # Beide Raeume auf derselben Linie -- genau der Fall, der den alten
    # Linien-basierten Abgleich in die Irre fuehrte.
    line.assigned_room_ids = [uv1_room.id, uv2_room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="VT", rooms=[uv1_room, uv2_room])
    floor = Floor(name="Verteiler", short_code="VT", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    uv1_devices = bv._devices_for_verteiler(uv1_room, uv1_room.verteiler[0])
    uv2_devices = bv._devices_for_verteiler(uv2_room, uv2_room.verteiler[0])

    assert [d.physical_address for d in uv1_devices] == ["1.1.1"]
    assert [d.physical_address for d in uv2_devices] == ["1.1.2"]


def test_room_with_single_verteiler_shows_only_its_own_devices():
    room = _make_pseudo_verteiler_room("HV  HV", vt_type="HV")
    dev = Device(
        physical_address="1.1.1", device_type="actor", product="Aktor",
        installation_location="HV  HV", room_id=room.id,
    )
    line = Line(line_number=1, name="HL")
    line.devices = [dev]
    line.assigned_room_ids = [room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="VT", rooms=[room])
    floor = Floor(name="Verteiler", short_code="VT", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    devices = bv._devices_for_verteiler(room, room.verteiler[0])
    assert [d.physical_address for d in devices] == ["1.1.1"]


def test_device_outside_room_never_matches():
    """Ein Geraet mit anderer device.room_id darf nie auftauchen, egal was
    sein Einbauort-Text sagt (Kandidaten kommen ausschliesslich ueber
    device.room_id == room.id)."""
    uv1_room = _make_pseudo_verteiler_room("UV1   ( Steigzone )")
    other_room = Room(number="01", name="Technikraum")

    # Geraet gehoert laut room_id NICHT zu UV1, hat aber zufaellig einen
    # Einbauort-Text, der mit "UV1" beginnen wuerde.
    dev = Device(
        physical_address="1.1.9", device_type="actor", product="Fremdaktor",
        installation_location="UV1-Ersatzteil-Lager", room_id=other_room.id,
    )
    line = Line(line_number=1, name="HL")
    line.devices = [dev]
    line.assigned_room_ids = [uv1_room.id, other_room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="VT", rooms=[uv1_room, other_room])
    floor = Floor(name="Verteiler", short_code="VT", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    uv1_devices = bv._devices_for_verteiler(uv1_room, uv1_room.verteiler[0])
    assert uv1_devices == []


# ---------------------------------------------------------------------------
# _refresh_tree -- Geräte, die bereits als Bedienelement dargestellt werden,
# dürfen nicht zusätzlich als eigene Geräte-Zeile erscheinen (Regression:
# ein importierter Leckage-Sensor erschien zweimal -- einmal roh als
# "Sensor", einmal als davon abgeleitetes Bedienelement). Passive Melde-
# geräte (Wassermelder, Fensterkontakt, ...) werden zudem als "Sensor" statt
# "Bedienelement" ausgewiesen, da sie keine echte Bedienung haben.
# ---------------------------------------------------------------------------

from PySide6.QtCore import Qt as _Qt
from knix_arranger.models.building import Bedienelement


def _room_tree_item(bv: BuildingView, room: Room):
    """Findet den QTreeWidgetItem des angegebenen Raums im Baum."""

    def _walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            data = child.data(0, _Qt.UserRole)
            if data and data[0] == "room" and data[1] is room:
                return child
            found = _walk(child)
            if found is not None:
                return found
        return None

    return _walk(bv._tree.invisibleRootItem())


def test_leak_sensor_not_shown_twice_and_labeled_as_sensor():
    room = Room(number="04", name="Liftschacht")
    device = Device(
        physical_address="1.1.24", device_type="sensor", product="Leak KNX 2.0",
        room_id=room.id,
    )
    room.bedienelemente.append(Bedienelement(
        element_type="Wassermelder", channels=1, participant_number="1.1.24",
    ))

    line = Line(line_number=1, name="HL")
    line.devices = [device]
    line.assigned_room_ids = [room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="UG", rooms=[room])
    floor = Floor(name="Untergeschoss", short_code="UG", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    room_item = _room_tree_item(bv, room)
    assert room_item is not None
    assert room_item.childCount() == 1  # nur das Bedienelement, nicht zusaetzlich das Rohgeraet

    device_item = room_item.child(0)
    assert device_item.text(0) == "Wassermelder"
    assert device_item.text(1) == "Sensor"  # nicht "Bedienelement" -- kein Bediengeraet
    assert device_item.text(2) == "1.1.24"


def test_taster_bedienelement_still_labeled_as_bedienelement():
    room = Room(number="00", name="Galerie")
    device = Device(
        physical_address="1.1.53", device_type="sensor", product="Taster EDIZIOdue 1-8fach",
        room_id=room.id,
    )
    room.bedienelemente.append(Bedienelement(
        element_type="Tastereinheit", channels=3, participant_number="1.1.53",
    ))

    line = Line(line_number=1, name="HL")
    line.devices = [device]
    line.assigned_room_ids = [room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="DG", rooms=[room])
    floor = Floor(name="Dachgeschoss", short_code="DG", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    room_item = _room_tree_item(bv, room)
    assert room_item.childCount() == 1

    device_item = room_item.child(0)
    assert device_item.text(0) == "Tastereinheit"
    assert device_item.text(1) == "Bedienelement"


# ---------------------------------------------------------------------------
# _refresh_tree -- Geräte-Gesamtzahl eines Raums mit im Raum verschachteltem
# Verteiler (Regression: "X Geräte" in der Raumzusammenfassung zählte die
# Verteiler-Geräte doppelt -- einmal über die volle room_devices-Liste,
# einmal nochmal über shown_ids -- z.B. ein Technikraum mit Hauptverteiler
# und dessen 9 Geräten zeigte "21 Geräte" statt der tatsächlichen 12).
# ---------------------------------------------------------------------------

def test_room_device_count_not_doubled_for_nested_verteiler():
    room = Room(number="01", name="Technikraum")
    room.verteiler.append(Verteiler(name="HV  HV", verteiler_type="HV"))

    line = Line(line_number=1, name="HL")
    for i in range(1, 4):
        line.devices.append(Device(
            physical_address=f"1.1.{i}", device_type="sensor", product=f"Sensor {i}",
            installation_location="01  Technikraum", room_id=room.id,
        ))
    for i in range(10, 19):
        line.devices.append(Device(
            physical_address=f"1.1.{i}", device_type="actor", product=f"Aktor {i}",
            installation_location="HV  HV", room_id=room.id,
        ))
    line.assigned_room_ids = [room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="UG", rooms=[room])
    floor = Floor(name="Untergeschoss", short_code="UG", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    room_item = _room_tree_item(bv, room)
    assert "12 Geräte" in room_item.text(3)
    assert "21 Geräte" not in room_item.text(3)
