"""
KO-Flags je GA (FA-627/628): Deutung aller Schreibweisen, Prüfungen und
Anzeige in der Topologie.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import (
    Area, CommunicationObject, Device, Line, Topology,
)
from knix_arranger.services.ko_links import (
    COMMUNICATE, READ, TRANSMIT, UPDATE, WRITE, flags_text, ko_links, parse_flags,
)
from knix_arranger.services.product_sync import _co_dict
from knix_arranger.services.validation_engine import ValidationEngine


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.mark.parametrize("flags, expected", [
    ("K-S---", {COMMUNICATE, WRITE}),              # ETS-Report
    ("KL-Ü--", {COMMUNICATE, READ, TRANSMIT}),
    ("K-SÜA-", {COMMUNICATE, WRITE, TRANSMIT, UPDATE}),
    ("KSUE-A", {COMMUNICATE, WRITE, TRANSMIT, UPDATE}),   # knxproj
    ("KSUA", {COMMUNICATE, WRITE, TRANSMIT, UPDATE}),     # KNiX-Kurzform, U = Ü
    ("KLU", {COMMUNICATE, READ, TRANSMIT}),
    ("CRWTU", {COMMUNICATE, READ, WRITE, TRANSMIT, UPDATE}),   # englisch
    ("K-Ü--", {COMMUNICATE, WRITE}),               # Produktdaten bis 1.3.1
    ("KL-S-", {COMMUNICATE, READ, TRANSMIT}),
    ("K-ÜSU", {COMMUNICATE, WRITE, TRANSMIT, UPDATE}),
    ("", set()),
])
def test_parse_flags(flags, expected):
    assert parse_flags(flags) == expected


def test_flags_text_and_catalog_roundtrip():
    assert flags_text("K-Ü--") == "K S"
    co = CommunicationObject(object_number=1, flags="KL-Ü--")
    data = _co_dict(co)
    assert (data["read_flag"], data["write_flag"], data["transmit_flag"]) == (True, False, True)


def _ga(address: str, function: str) -> GroupAddress:
    main, middle, sub = (int(x) for x in address.split("/"))
    return GroupAddress(main_group=main, middle_group=middle, sub_group=sub,
                        designation=f"GA {address} {function}", function_name=function)


def _project(devices, gas) -> KnxProject:
    project = KnxProject(name="Flags")
    line = Line(name="Linie 1", line_number=1, devices=devices)
    project.topology = Topology(areas=[Area(area_number=1, lines=[line])])
    project.topology.is_imported = True
    mgs: dict[tuple, MiddleGroup] = {}
    for ga in gas:
        mgs.setdefault((ga.main_group, ga.middle_group),
                       MiddleGroup(number=ga.middle_group)).group_addresses.append(ga)
    project.group_addresses = GroupAddressStructure(main_groups=[
        MainGroup(number=m, middle_groups=[mg for (mm, _n), mg in mgs.items() if mm == m])
        for m in sorted({k[0] for k in mgs})])
    return project


def _device(pa, *cos):
    return Device(device_type="actor", product="Aktor", physical_address=pa,
                  communication_objects=[CommunicationObject(object_number=n, name=name,
                                                             flags=flags, connected_gas=gas)
                                         for n, name, flags, gas in cos])


def test_links_sending_ga_is_first():
    taster = _device("1.1.10", (1, "Schalten", "K-SÜ--", ["1/0/0", "1/6/0"]))
    links = ko_links(_project([taster], []))
    assert [(l.ga_address, l.sending) for l in links] == [("1/0/0", True), ("1/6/0", False)]


def _issues(project, rule):
    return [i for i in ValidationEngine().validate(project.group_addresses, project)
            if i.rule_id == rule]


def test_several_readers_reported():
    a = _device("1.1.10", (89, "Ausgang D", "KL-Ü--", ["2/7/30"]))
    b = _device("1.1.15", (41, "Ausgang 5", "KL-Ü--", ["2/7/30"]))
    visu = _device("1.1.50", (3, "Anzeige", "K-S-A-", ["2/7/30"]))
    project = _project([a, b, visu], [_ga("2/7/30", "RM")])
    found = _issues(project, "FA-627")
    assert len(found) == 1 and found[0].address == "2/7/30"
    assert "1.1.10" in found[0].message and "1.1.15" in found[0].message
    assert found[0].level == "info"                     # importiert: ETS massgebend
    project.topology.is_imported = False
    assert _issues(project, "FA-627")[0].level == "warning"


def test_command_without_receiver():
    taster = _device("1.1.10", (1, "Schalten", "K--Ü--", ["1/0/0"]))
    project = _project([taster], [_ga("1/0/0", "E/A")])
    assert [i.address for i in _issues(project, "FA-628")] == ["1/0/0"]
    actor = _device("1.1.1", (0, "Kanal A Schalten", "K-S---", ["1/0/0"]))
    project = _project([taster, actor], [_ga("1/0/0", "E/A")])
    assert _issues(project, "FA-628") == []
    # Rückmeldung braucht keinen Empfänger
    project = _project([_device("1.1.1", (5, "Status", "KL-Ü--", ["1/6/0"]))],
                       [_ga("1/6/0", "RM")])
    assert _issues(project, "FA-628") == []


def test_topology_shows_flags():
    from knix_arranger.ui.views.topology_view import TopologyView
    actor = _device("1.1.1", (0, "Kanal A", "K-S---", ["1/0/0"]),
                    (1, "Kanal A Status", "KL-Ü--", ["1/6/0"]))
    project = _project([actor], [_ga("1/0/0", "E/A"), _ga("1/6/0", "RM")])
    view = TopologyView()
    view.set_project(project)
    view._tree.expandAll()
    texts = {}
    it = QTreeWidgetItemIterator(view._tree)
    while it.value():
        texts[it.value().text(1)] = (it.value().text(4), it.value().toolTip(4))
        it += 1
    assert "Flags K S" in texts["1/0/0"][0]
    assert "Flags K L Ü" in texts["1/6/0"][0]
    assert "L Lesen" in texts["1/6/0"][1]


def test_proposals_only_for_display(gewerk_catalog):
    """Ohne KO-Zuordnung zeigt die Topologie die Flags des Vorschlags; die
    Prüfungen bleiben bei bestätigten Zuordnungen."""
    from knix_arranger.models.building import (
        Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
    )
    from knix_arranger.services.address_generator import regenerate_addresses
    room = Room(number="E01", name="Wohnen",
                gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)])
    project = KnxProject(name="Vorschlag")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        name="EG", short_code="EG", main_group_number=1,
        apartments=[Apartment(name="W", rooms=[room])])])])])
    project._gewerk_catalog = gewerk_catalog
    # Produktdaten in der Fünf-Stellen-Form bis 1.3.1, vier Kanäle wie ein echter Aktor
    cos = []
    for ch in "ABCD":
        for function, flags in (("Schalten", "K-Ü--"), ("Status Schalten", "KL-S-")):
            cos.append(CommunicationObject(object_number=len(cos), name=f"Kanal {ch}",
                                           object_function=function, flags=flags,
                                           data_type="DPST-1-1"))
    actor = Device(device_type="actor", product="Schaltaktor 4-fach", physical_address="1.1.1",
                   communication_objects=cos)
    project.topology = Topology(areas=[Area(area_number=1, lines=[Line(
        name="L1", line_number=1, assigned_room_ids=[room.id], devices=[actor])])])
    regenerate_addresses(project)

    assert ko_links(project) == []
    proposed = ko_links(project, proposals=True)
    assert proposed and all(l.proposed for l in proposed)
    by_ga = {l.ga_address: flags_text(l.co.flags) for l in proposed}
    ea = next(g.address for g in project.group_addresses.all_addresses()
              if g.function_name == "E/A" and g.element_number)
    assert by_ga[ea] == "K S"


def _link(key, channel, function, dpt, feedback):
    from knix_arranger.services.sensor_channels import SensorLink
    return SensorLink(key=key, channel=channel, function=function, ga_address="1/0/0",
                      ga_designation="", ga_function=function, dpt=dpt, feedback=feedback)


def test_keys_without_text_or_dpt():
    """Feller EDIZIOdue: KOs «Taste 1», «Taste 1, Signal-LED» ohne DPT."""
    from knix_arranger.services.sensor_channels import suggested_sensor_co_map
    cos = []
    for n in (1, 2):
        for name, flags in ((f"Taste {n}", "K-SÜ--"), (f"Taste {n}", "K--Ü--"),
                            (f"Taste {n}, Signal-LED", "K-S-A-")):
            cos.append(CommunicationObject(object_number=len(cos), name=name,
                                           object_function=name, flags=flags))
    links = [
        _link("r|LD|1|RM", "Status 1", "RM", "DPST-1-1", True),        # Rückmeldung zuerst
        _link("r|LD|1|RM WERT", "Status 1", "RM WERT", "DPST-5-1", True),
        _link("r|LD|1|E/A", "Taste 1 kurz", "E/A", "DPST-1-1", False),
        _link("r|LD|1|DIM", "Taste 1 lang", "DIM", "DPST-3-7", False),
        _link("r|S|1|E/A", "Taste 2 kurz", "E/A", "DPST-1-1", False),
    ]
    result = suggested_sensor_co_map(None, links, cos)
    assert result["r|LD|1|E/A"] == 0 and result["r|LD|1|DIM"] == 1
    assert result["r|LD|1|RM"] == 0            # hört am Schalt-KO mit
    assert "r|LD|1|RM WERT" not in result      # Wert nicht auf ein Tasten-KO
    assert result["r|S|1|E/A"] == 3

    single = suggested_sensor_co_map(None, [_link("x|L|1|E/A", "Taste kurz", "E/A",
                                                  "DPST-1-1", False)], cos)
    assert single == {"x|L|1|E/A": 0}             # Einzeltaster = Taste 1


def test_template_only_unlinked_is_ignored():
    from knix_arranger.services.ko_templates import apply_sensor_template
    link = _link("r|L|1|E/A", "Taste 1 kurz", "E/A", "DPST-1-1", False)
    from knix_arranger.services.ko_templates import sensor_signature
    assert apply_sensor_template({sensor_signature(link): -1}, [link], {0}) == {}
    assert apply_sensor_template({sensor_signature(link): -1, "x": 0}, [link], {0}) == {
        "r|L|1|E/A": -1}


def test_rocker_product_sides():
    """Wippen-Produkt: Taste 1 = Wippe 1 links, Taste 2 = Wippe 1 rechts,
    Taste 3 = Wippe 2 links (Feller EDIZIOdue)."""
    from knix_arranger.services.sensor_channels import suggested_sensor_co_map
    cos = []
    for n in (1, 2):
        for name, flags in ((f"Taste {n}", "K-SÜ--"), (f"Taste {n}", "K--Ü--"),
                            (f"Taste {n}, Signal-LED", "K-S-A-"),
                            (f"Taste {n}, rechts", "K-SÜ--"),
                            (f"Taste {n}, rechts, Signal-LED", "K-S-A-")):
            cos.append(CommunicationObject(object_number=len(cos), name=name,
                                           object_function=name, flags=flags))
    links = [_link(f"r|L|{k}|E/A", f"Taste {k} kurz", "E/A", "DPST-1-1", False)
             for k in (1, 2, 3, 4)]
    links.append(_link("r|L|2|RM", "Status 2", "RM", "DPST-1-1", True))
    result = suggested_sensor_co_map(None, links, cos)
    names = {key: cos[number].name for key, number in result.items()}
    assert names == {"r|L|1|E/A": "Taste 1", "r|L|2|E/A": "Taste 1, rechts",
                     "r|L|3|E/A": "Taste 2", "r|L|4|E/A": "Taste 2, rechts",
                     "r|L|2|RM": "Taste 1, rechts"}


def test_real_variant_before_placeholder():
    """Griesser JAX-9: je KO-Nummer eine echte Variante und Platzhalter
    «{{0:GO}}» mit allen Flags -- die Anzeige nimmt die echte."""
    from knix_arranger.services.ko_links import _by_number
    cos = [CommunicationObject(object_number=2, name="GO0002",
                               object_function="Operation of Blinds (M1), End position",
                               flags="K-S---"),
           CommunicationObject(object_number=2, name="GO0002", object_function="{{0:GO}}",
                               flags="KLSÜA-"),
           CommunicationObject(object_number=9, name="GO0009", object_function="{{0:GO}}",
                               flags="KLSÜA-"),
           CommunicationObject(object_number=9, name="GO0009",
                               object_function="Sun Protection (M1), Height feedback",
                               flags="KL-Ü--")]
    chosen = _by_number(cos)
    assert flags_text(chosen[2].flags) == "K S"
    assert flags_text(chosen[9].flags) == "K L Ü"
