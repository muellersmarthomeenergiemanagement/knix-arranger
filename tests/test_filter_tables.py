"""
Filtertabellen nachrechnen (FA-643). Nach dem Chalet: Z-Server 1.1.200
(extern) in Linie 1.1 ohne Koppler, Revox 1.2.7 hinter LK 1.2.0.
"""
from __future__ import annotations

from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.filter_tables import CouplerFilters, dummy_needs


def _device(pa, gas=(), **kw) -> Device:
    return Device(physical_address=pa, device_type=kw.pop("device_type", "actor"),
                  product=kw.pop("product", "Aktor"),
                  communication_objects=[CommunicationObject(connected_gas=list(gas))], **kw)


def _project(unfiltered: str = "") -> KnxProject:
    zserver = Device(physical_address="1.1.200", product="Z-Server", device_type="other",
                     external=True)
    taster = _device("1.1.51", ["3/5/61"], device_type="sensor", product="Taster")
    coupler = _device("1.2.0", device_type="coupler", product="LK/S4.1")
    revox = _device("1.2.7", ["3/5/61", "3/5/76", "12/0/100"], device_type="gateway",
                    product="Revox")
    project = KnxProject(name="Chalet")
    project.topology = Topology(is_imported=True, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[zserver, taster]),
        Line(line_number=2, devices=[coupler, revox])])])
    ga = GroupAddress(main_group=3, middle_group=5, sub_group=76, designation="Text1",
                      unfiltered=unfiltered)
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=3, middle_groups=[MiddleGroup(number=5, group_addresses=[ga])])])
    project.bus_recordings.append({"file": "Telegramme.xml", "pairs": [
        ["1.1.200", "3/5/76", "Read", 6, 0, ""],
        ["1.1.200", "3/5/61", "Read", 2, 0, ""],
        ["1.1.200", "12/0/100", "Write", 3, 0, "1"],
        ["1.1.200", "0/5/7", "Write", 1, 0, "1"],          # nirgends verknüpft
    ]})
    return project


def test_table_only_gas_used_outside_the_line():
    f = CouplerFilters.from_project(_project())
    assert f.line_couplers == {"1.2"}
    assert f.table("1.2") == ["3/5/61"]            # auch in 1.1 verknüpft
    assert f.blocking("1.1", "3/5/76") == ["1.2.0"]
    assert f.blocking("1.1", "3/5/61") == []
    assert f.blocking("1.2", "3/5/76") == []       # in der eigenen Linie
    assert f.blocking("1.1", "0/5/7") == []        # ohne Verknüpfung: kein Ziel


def test_dummy_need_from_recording():
    (need,) = dummy_needs(_project())
    assert need.device.physical_address == "1.1.200" and need.line == "1.1"
    assert need.gas == ["3/5/76", "12/0/100"] and need.couplers == ["1.2.0"]
    assert need.task.startswith("Dummy 1.1.200 in Linie 1.1 anlegen, mit 2 GA(s)")
    assert need.task.endswith("1.2.0 programmieren (Filtertabelle).")


def test_unfiltered_ga_passes():
    (need,) = dummy_needs(_project(unfiltered="true"))
    assert need.gas == ["12/0/100"]


def test_external_device_on_coupled_line():
    """Hat die Linie des externen Geräts einen Koppler, sperrt schon dieser
    alles, was dort nicht verknüpft ist -- auch zu Linien ohne Koppler."""
    project = _project()
    lines = project.topology.areas[0].lines
    lines[0].devices.append(_device("1.1.0", device_type="coupler", product="LK"))
    lines.append(Line(line_number=3, devices=[_device("1.3.5", ["5/0/1"])]))
    f = CouplerFilters.from_project(project)
    assert f.blocking("1.1", "5/0/1") == ["1.1.0"]
    assert f.blocking("1.1", "3/5/76") == ["1.1.0", "1.2.0"]
    assert f.blocking("1.1", "3/5/61") == []


def test_area_coupler():
    project = _project()
    other = Area(area_number=2, lines=[
        Line(line_number=0, devices=[_device("2.0.0", device_type="coupler", product="BK")]),
        Line(line_number=1, devices=[_device("2.1.3", ["7/0/1"])])])
    project.topology.areas.append(other)
    f = CouplerFilters.from_project(project)
    assert f.area_couplers == {"2"}
    assert f.blocking("1.1", "7/0/1") == ["2.0.0"]


def test_ets_dummy_resolves_need():
    """Steht der Dummy in der ETS (gleiche Adresse, verknüpfte GAs), entfällt
    das externe Gerät (FA-609b) und mit ihm die Aufgabe."""
    project = _project()
    line1 = project.topology.areas[0].lines[0]
    line1.devices[0] = _device("1.1.200", ["3/5/76", "12/0/100"], device_type="other",
                               product="Dummy")
    assert dummy_needs(project) == []
    assert CouplerFilters.from_project(project).table("1.2") == ["3/5/61", "3/5/76", "12/0/100"]


def test_worklist_and_bus_analysis():
    from knix_arranger.services.bus_monitor import analyze
    from knix_arranger.services.ets_worklist import PRIO_MUST, current_items
    project = _project()
    (item,) = [i for i in current_items(project) if i.rule_id == "FA-643"]
    assert item.priority == PRIO_MUST and item.where == "Linie 1.1"
    assert "Dummy 1.1.200" in item.task
    summary = {"pairs": project.bus_recordings[0]["pairs"], "telegrams": 12, "frames": 12,
               "repeats": 0, "acks": 0, "start": "2026-11-06T15:15:34",
               "stop": "2026-11-06T15:57:30"}
    a = analyze(project, summary)
    (need,) = a.dummy_needs
    assert need.gas == ["3/5/76", "12/0/100"]
    assert any(f.title == "Z-Server 1.1.200: 2 GA(s) durch Koppler 1.2.0 gesperrt"
               for f in a.findings)
    (issue,) = [i for i in a.unanswered if i.ga == "3/5/76"]
    assert issue.blocked_by == ["1.2.0"] and "Koppler 1.2.0 sperrt" in issue.text


def test_dummy_in_ets_lists_only_missing_gas():
    """Z-Server als Dummy in der ETS, mit 3/5/76 verknüpft: die ETS trägt 3/5/76
    in die Tabelle des 1.2.0 ein, fehlen bleibt 12/0/100."""
    project = _project()
    zserver = project.topology.areas[0].lines[0].devices[0]
    zserver.external, zserver.dummy = False, True
    zserver.communication_objects = [CommunicationObject(connected_gas=["3/5/76"])]
    (need,) = dummy_needs(project)
    assert need.gas == ["12/0/100"] and need.couplers == ["1.2.0"]
    assert need.task == ("Dummy 1.1.200 mit 1 GA(s) verbinden: 12/0/100; "
                         "1.2.0 programmieren (Filtertabelle).")
