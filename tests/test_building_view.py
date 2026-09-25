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


def test_device_in_different_room_than_its_bedienelement_not_shown_twice():
    """Regression Chalet Franziska 2005, Taster 1.1.30: das importierte
    Topologie-Geraet zeigt via device.room_id auf einen anderen Raum als das
    daraus abgeleitete Bedienelement (link_rooms_to_lines und die KO-basierte
    Bedienelement-Erzeugung koennen zu unterschiedlichen Raum-Ergebnissen
    kommen). Die Dedup-Pruefung muss projektweit greifen, nicht nur
    raumintern -- sonst erscheint das Geraet zusaetzlich als leere, eigene
    Sensor-Zeile in SEINEM Raum, obwohl es im ANDEREN Raum bereits als
    vollstaendig befuelltes Bedienelement dargestellt wird."""
    be_room = Room(number="00", name="Haupteingang")
    be_room.bedienelemente.append(Bedienelement(
        element_type="Tastereinheit", channels=4, participant_number="1.1.30",
    ))
    device_room = Room(number="01", name="Eingang / Studio")
    device = Device(
        physical_address="1.1.30", device_type="sensor", product="Taster EDIZIOdue 1-8fach",
        room_id=device_room.id,
    )

    line = Line(line_number=1, name="HL")
    line.devices = [device]
    line.assigned_room_ids = [be_room.id, device_room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="EG", rooms=[be_room, device_room])
    floor = Floor(name="Erdgeschoss", short_code="EG", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    be_room_item = _room_tree_item(bv, be_room)
    assert be_room_item.childCount() == 1
    assert be_room_item.child(0).text(1) == "Bedienelement"

    device_room_item = _room_tree_item(bv, device_room)
    assert device_room_item.childCount() == 0  # kein leeres Sensor-Duplikat


def test_actor_gets_channel_children_in_building_view():
    """Symmetrie-Fix (FA-1007): Aktoren zeigten in der Topologie-Ansicht schon
    Kanal-Details, in der Gebaeude-Ansicht blieben sie immer flache Blaetter.
    Jetzt gruppiert building_view.py Device.communication_objects genauso
    nach physischem Kanal wie topology_view.py."""
    from knix_arranger.models.topology import CommunicationObject
    from knix_arranger.models.group_address import GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress

    room = Room(number="01", name="Technikraum")
    room.verteiler.append(Verteiler(name="HV  HV", verteiler_type="HV"))
    device = Device(
        physical_address="1.1.1", device_type="actor", product="Schaltaktor 8fach",
        installation_location="HV  HV", room_id=room.id,
    )
    device.communication_objects = [
        CommunicationObject(object_number=0, name="Ausgang A, Schalten", connected_gas=["3/0/1"]),
        CommunicationObject(object_number=1, name="Ausgang A, Status", connected_gas=["3/7/1"]),
    ]

    line = Line(line_number=1, name="HL")
    line.devices = [device]
    line.assigned_room_ids = [room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    apt = Apartment(name="EG", rooms=[room])
    floor = Floor(name="Erdgeschoss", short_code="EG", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    ga_structure = GroupAddressStructure()
    hg = MainGroup(number=3, name="Licht")
    mg = MiddleGroup(number=0, name="EG")
    hg.middle_groups.append(mg)
    ga_structure.main_groups.append(hg)
    mg.group_addresses.append(GroupAddress(main_group=3, middle_group=0, sub_group=1,
                                            designation="L.EG.01.1_ea"))

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)
    bv.set_group_addresses(ga_structure)

    room_item = _room_tree_item(bv, room)
    vt_item = room_item.child(0)
    dev_item = vt_item.child(0)
    assert dev_item.text(0) == "Schaltaktor 8fach"
    assert dev_item.childCount() == 1  # ein Kanal "Ausgang A"

    ch_item = dev_item.child(0)
    assert ch_item.text(0) == "Ausgang A"
    assert ch_item.childCount() == 2
    ga_texts = {ch_item.child(i).text(2) for i in range(2)}
    assert ga_texts == {"3/0/1", "3/7/1"}


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


# ---------------------------------------------------------------------------
# "Adresse"-Spalte einer Funktionszeile (FA-1502c): wizard-geplante (Gewerk-
# basierte) function_assignments speichern in function_ga nur die GA-
# Bezeichnung, keine Adressnummer (SensorService._expand_funktionen uebernimmt
# GroupAddress.designation direkt) -- ohne Aufloesung ueber
# build_ga_by_designation/resolve_ga_display fehlte die Gruppenadressnummer in
# der Gebaeude-Ansicht bei Projekten ohne ETS-Import (anders als importierte
# Direkte-GA-Zuordnungen, die schon "Adresse  Bezeichnung" kombiniert
# speichern).
# ---------------------------------------------------------------------------

def test_function_row_shows_address_for_wizard_planned_ga():
    from knix_arranger.models.building import Bedienelement, FunctionAssignment
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
    )

    room = Room(number="E01", name="Wohnzimmer")
    be = Bedienelement(element_type="Tastereinheit", channels=1, participant_number="1.1.5")
    be.function_assignments = [
        FunctionAssignment(button_channel="Taste", function_ga="LD_E01_01 E/A",
                            description="Licht schalten", role="befehl"),
    ]
    room.bedienelemente.append(be)
    apt = Apartment(name="EG", rooms=[room])
    floor = Floor(name="EG", short_code="EG", apartments=[apt])
    wing = Wing(name="Haupt", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    ga_structure = GroupAddressStructure()
    hg = MainGroup(number=2, name="Licht")
    mg = MiddleGroup(number=0, name="EG")
    hg.middle_groups.append(mg)
    ga_structure.main_groups.append(hg)
    mg.group_addresses.append(GroupAddress(
        main_group=2, middle_group=0, sub_group=0, designation="LD_E01_01 E/A",
    ))

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(Topology())
    bv.set_group_addresses(ga_structure)

    room_item = _room_tree_item(bv, room)
    be_item = room_item.child(0)
    fa_item = be_item.child(0)
    assert fa_item.text(2) == "2/0/0  LD_E01_01 E/A"


def test_function_row_keeps_already_combined_import_ga_unchanged():
    """Importierte Direkte-GA-Zuordnungen (XlsxImportService.backfill_
    function_assignments) speichern function_ga schon als "Adresse
    Bezeichnung" -- resolve_ga_display darf das nicht doppelt voranstellen,
    selbst wenn die GA-Struktur zufaellig eine passende Bezeichnung kennt."""
    from knix_arranger.models.building import Bedienelement, FunctionAssignment
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
    )

    room = Room(number="02", name="Waschkeller")
    be = Bedienelement(element_type="Tastereinheit", channels=1, participant_number="1.1.28")
    be.function_assignments = [
        FunctionAssignment(button_channel="Taste 1, links",
                            function_ga="1/0/0  L.UG.01.1_ea  ( Technikraum )",
                            description="Taste 1, links", role="befehl"),
    ]
    room.bedienelemente.append(be)
    apt = Apartment(name="UG", rooms=[room])
    floor = Floor(name="UG", short_code="UG", apartments=[apt])
    wing = Wing(name="Haupt", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(Topology())
    bv.set_group_addresses(GroupAddressStructure())  # keine getaggten GAs

    room_item = _room_tree_item(bv, room)
    fa_item = room_item.child(0).child(0)
    assert fa_item.text(2) == "1/0/0  L.UG.01.1_ea  ( Technikraum )"


def test_channel_tag_in_brackets_groups_objects_into_one_channel():
    """Griesser JAX-9 (Chalet Franziska 1.1.11): jedes Objekt heisst anders,
    der Kanal steht nur als Klammer-Tag im Namen ("Bedienung Storen (M1),
    Endlage"). Vorher wurde jedes Objekt ein eigener Knoten "CO 2", "CO 3"..."""
    from knix_arranger.models.topology import CommunicationObject

    room = Room(number="01", name="Technikraum")
    device = Device(physical_address="1.1.11", device_type="actor",
                    product="JAX-9", room_id=room.id)
    device.communication_objects = [
        CommunicationObject(object_number=2, name="Bedienung Storen (M1), Endlage",
                            connected_gas=["2/1/10", "0/1/115"]),
        CommunicationObject(object_number=9, name="Sonnenschutz (M1), Rückmeldung Höhe",
                            connected_gas=["2/6/12"]),
        CommunicationObject(object_number=24, name="Bedienung Storen (M2), Endlage",
                            connected_gas=["2/1/5"]),
    ]
    line = Line(line_number=1, devices=[device], assigned_room_ids=[room.id])
    topology = Topology(areas=[Area(area_number=1, lines=[line])])
    floor = Floor(name="EG", short_code="EG", apartments=[Apartment(name="EG", rooms=[room])])
    areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])

    bv = BuildingView()
    bv.set_areal(areal)
    bv.set_topology(topology)

    dev_item = _room_tree_item(bv, room).child(0)
    channels = {dev_item.child(i).text(0): dev_item.child(i) for i in range(dev_item.childCount())}
    assert set(channels) == {"Kanal M1", "Kanal M2"}
    assert channels["Kanal M1"].childCount() == 3
    assert channels["Kanal M1"].text(3) == "3 GA(s)"


def test_objects_without_channel_grouped_by_function_or_shown_directly():
    """Vitogate 200 (Chalet Franziska 1.1.32): 62 Datenpunkte ohne Kanal --
    vorher je ein Knoten "CO n" mit einem einzigen Kind."""
    from knix_arranger.models.topology import CommunicationObject

    room = Room(number="01", name="Technik")
    device = Device(physical_address="1.1.32", device_type="actor",
                    product="Vitogate 200", room_id=room.id)
    device.communication_objects = [
        CommunicationObject(object_number=1, name="Raumtemperatur Soll HK1",
                            object_function="Bedienung / Heizkreis A1/HK1", connected_gas=["0/2/101"]),
        CommunicationObject(object_number=2, name="Red. Raumtemperatur Soll HK1",
                            object_function="Bedienung / Heizkreis A1/HK1", connected_gas=["0/2/102"]),
        CommunicationObject(object_number=8, name="Außentemperatur",
                            object_function="Überblick / Anlage", connected_gas=["0/2/108"]),
    ]
    line = Line(line_number=1, devices=[device], assigned_room_ids=[room.id])
    floor = Floor(name="UG", short_code="UG", apartments=[Apartment(name="UG", rooms=[room])])
    bv = BuildingView()
    bv.set_areal(Areal(buildings=[Building(wings=[Wing(floors=[floor])])]))
    bv.set_topology(Topology(areas=[Area(area_number=1, lines=[line])]))

    dev_item = _room_tree_item(bv, room).child(0)
    assert dev_item.childCount() == 2
    group, single = dev_item.child(0), dev_item.child(1)
    assert group.text(0) == "Bedienung / Heizkreis A1/HK1" and group.childCount() == 2
    assert single.text(0).startswith("Außentemperatur") and single.text(2) == "0/2/108"
