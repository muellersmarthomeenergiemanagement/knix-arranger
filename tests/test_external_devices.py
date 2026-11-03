"""
Geräte am Bus ausserhalb des ETS-Projekts und Teilnehmer je Segment (FA-609b).
Chalet: Z-Server 1.1.200 der Visualisierung fehlt in der ETS, Linie 1.1 hat
mit ihm 64 Teilnehmer.
"""
from __future__ import annotations
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.line_segments import segment_load
from knix_arranger.services.project_reconcile_service import reconcile_reimport
from knix_arranger.services.topology_validation import check_topology


def _line(count: int, *extra: Device) -> Line:
    devices = [Device(physical_address=f"1.1.{n}", device_type="sensor", product="Taster")
               for n in range(1, count + 1)]
    devices.append(Device(physical_address="1.1.-", device_type="power_supply",
                          product="Spannungsversorgung 640mA"))
    return Line(line_number=1, devices=devices + list(extra))


def _zserver() -> Device:
    return Device(physical_address="1.1.200", product="Z-Server", device_type="other",
                  external=True, manually_added=True)


def _project(line: Line, imported=True) -> KnxProject:
    project = KnxProject(name="Test")
    project.topology = Topology(is_imported=imported,
                                areas=[Area(area_number=1, lines=[line])])
    return project


def test_external_device_counts_in_segment():
    load = segment_load(_line(63, _zserver()))
    assert (load.count, load.capacity, load.external) == (64, 64, 1)
    assert load.low_reserve and not load.overloaded
    assert load.summary() == "64 / 64 Teilnehmer"


def test_repeater_adds_segment():
    repeater = Device(physical_address="1.1.64", device_type="coupler",
                      product="Linienverstärker REG")
    load = segment_load(_line(70, repeater))
    assert (load.count, load.segments, load.capacity) == (71, 2, 128)
    assert not (load.overloaded or load.low_reserve)


def test_validation_segment():
    issues = [i for i in check_topology(_project(_line(63, _zserver())))
              if i.rule_id == "FA-609b"]
    assert [(i.level, i.message) for i in issues] == [
        ("warning", "Linie 1.1: 64 / 64 Teilnehmer, davon 1 nicht im ETS-Projekt")]
    issues = [i for i in check_topology(_project(_line(66))) if i.rule_id == "FA-609b"]
    assert [i.level for i in issues] == ["error"]
    assert not [i for i in check_topology(_project(_line(40))) if i.rule_id == "FA-609b"]


def test_external_device_round_trip():
    device = Device.from_dict(_zserver().to_dict())
    assert device.external and device.physical_address == "1.1.200"


def test_reimport_keeps_external_device():
    old = _project(_line(3, _zserver()))
    new = _project(_line(3))
    diff = reconcile_reimport(old, new)
    devices = new.topology.areas[0].lines[0].devices
    assert [d.physical_address for d in devices if d.external] == ["1.1.200"]
    assert "1.1.200" not in diff.devices_removed


def test_reimport_prefers_ets_device():
    """Steht die Adresse inzwischen im ETS-Projekt, gilt das ETS-Gerät."""
    old = _project(_line(3, _zserver()))
    ets = Device(physical_address="1.1.200", product="Z-Server Dummy", device_type="other")
    new = _project(_line(3, ets))
    reconcile_reimport(old, new)
    devices = new.topology.areas[0].lines[0].devices
    assert [d.product for d in devices if d.physical_address == "1.1.200"] == ["Z-Server Dummy"]


def test_reimport_new_line_for_external_device():
    old = _project(_line(3))
    old.topology.areas[0].lines.append(Line(line_number=0, devices=[
        Device(physical_address="1.0.200", product="Z-Server", external=True)]))
    new = _project(_line(3))
    reconcile_reimport(old, new)
    main = [l for l in new.topology.areas[0].lines if l.line_number == 0]
    assert [d.physical_address for d in main[0].devices] == ["1.0.200"]


def test_dialog_creates_external_device():
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.dialogs.external_device_dialog import ExternalDeviceDialog
    QApplication.instance() or QApplication([])
    line = _line(3)
    dlg = ExternalDeviceDialog(1, line)
    assert dlg.physical_address == "1.1.200"          # Vorschlag am Ende des Bereichs
    dlg._name.setText("Z-Server Visualisierung")
    device = dlg.apply()
    assert device.external and device.manually_added
    assert (device.physical_address, device.application_program) == (
        "1.1.200", "Visualisierung / Server")
    edit = ExternalDeviceDialog(1, line, device)
    assert edit.physical_address == "1.1.200" and edit._kind.currentIndex() == 0


def test_topology_view_marks_external_device():
    from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator
    from knix_arranger.ui.views.topology_view import TopologyView
    QApplication.instance() or QApplication([])
    view = TopologyView()
    view.set_project(_project(_line(63, _zserver())))
    view._tree.expandAll()
    texts = {}
    it = QTreeWidgetItemIterator(view._tree)
    while it.value():
        texts[it.value().text(1)] = it.value().text(4)
        it += 1
    assert texts["1.1.200"] == "Nicht im ETS-Projekt"
    assert texts["1.1"].startswith("64 / 64 Teilnehmer · Busstrom")
