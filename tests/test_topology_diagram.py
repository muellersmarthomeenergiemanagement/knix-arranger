"""Koppler und Spannungsversorgungen: gleiche Regel in Topologie-Ansicht,
Topologie-Diagramm und Topologie-Bericht (nur anzeigen, was als Geraet
vorhanden ist)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import (
    Area, Line, Device, area_coupler, line_coupler, line_power_supplies,
    power_supply_address, line_title,
)
from knix_arranger.services.topology_diagram import build_topology_diagram


def _imported_project() -> KnxProject:
    """Wie Chalet: Linie 1.1 ohne Koppler (coupler_address trotzdem gesetzt),
    Linie 1.2 mit Koppler 1.2.0, SV ohne ETS-Adresse, leerer Bereich 0."""
    project = KnxProject(name="Import")
    project.topology.is_imported = True
    project.topology.areas = [
        Area(area_number=1, coupler_address="1.0.0", lines=[
            Line(line_number=1, name="Linie 1", coupler_address="1.1.0", devices=[
                Device(physical_address="1.1.-", device_type="power_supply",
                       product="SV/S30.640.3.1 Power Supply,640mA,MDRC"),
                Device(physical_address="1.1.1", device_type="actor", product="Schaltaktor"),
                Device(physical_address="1.1.2", device_type="sensor", product="Taster"),
            ]),
            Line(line_number=2, name="Linie 2", coupler_address="1.2.0", devices=[
                Device(physical_address="1.2.0", device_type="coupler", product="LK/S4.2.1"),
                Device(physical_address="1.2.1", device_type="actor", product="Dimmaktor"),
            ]),
        ]),
        Area(area_number=0, lines=[Line(line_number=0)]),
    ]
    return project


def test_koppler_nur_als_geraet():
    area = _imported_project().topology.areas[0]
    l1, l2 = area.lines
    assert line_coupler(area, l1) is None                   # nur coupler_address
    assert line_coupler(area, l2).product == "LK/S4.2.1"
    assert area_coupler(area) is None


def test_spannungsversorgung_nur_als_geraet():
    area = _imported_project().topology.areas[0]
    l1, l2 = area.lines
    assert [d.physical_address for d in line_power_supplies(l1)] == ["1.1.-"]
    assert line_power_supplies(l2) == []
    assert power_supply_address(area, l1, Device(device_type="power_supply")) == "1.1.-"


def test_linientitel():
    area = Area(area_number=1)
    assert line_title(area, Line(line_number=2, name="Linie 2")) == "Linie 1.2"
    assert line_title(area, Line(line_number=2, name="Wohnung 1")) == "Linie 1.2: Wohnung 1"


def test_diagramm_knoten():
    diagram = build_topology_diagram(_imported_project(), include_empty_lines=False)
    assert diagram["backbone"] == ""                        # leerer Bereich 0 zaehlt nicht
    assert [a["title"] for a in diagram["areas"]] == ["Bereich 1"]
    l1, l2 = diagram["areas"][0]["nodes"]
    assert l1["lines"] == ["SV 1.1.-", "1 Aktor", "1 Sensor"]
    assert l2["lines"] == ["Koppler 1.2.0", "1 Aktor"]


def test_diagramm_app_zeigt_leere_linien():
    diagram = build_topology_diagram(_imported_project(), include_empty_lines=True)
    assert [a["title"] for a in diagram["areas"]] == ["Bereich 0", "Bereich 1"]
    assert diagram["areas"][0]["nodes"][0]["lines"] == []


def test_baumansicht_ohne_virtuelle_koppler():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.topology_view import TopologyView
    app = QApplication.instance() or QApplication([])  # noqa: F841
    view = TopologyView()
    view.set_topology(_imported_project().topology)

    labels = []

    def walk(item, depth=0):
        labels.append((item.text(0), item.text(1)))
        for i in range(item.childCount()):
            walk(item.child(i), depth + 1)
    for i in range(view._tree.topLevelItemCount()):
        walk(view._tree.topLevelItem(i))

    assert ("Linienkoppler (LK)", "1.1.0") not in labels
    assert ("Linienkoppler (LK)", "1.2.0") in labels
    assert ("Speisegerät (SV)", "1.1.-") in labels
    assert ("Speisegerät (SV)", "1.2.-") not in labels


def test_baumansicht_raum_als_hinweis_ohne_einbauort():
    """Chalet 1.1.39: kein Einbauort aus der ETS, Raum 04 Schlafen als
    grauer Hinweis; das Gerät selbst bleibt ohne Einbauort."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room
    from knix_arranger.ui.views.topology_view import TopologyView, _COLOR_ROOM_HINT
    app = QApplication.instance() or QApplication([])  # noqa: F841

    room = Room(number="04", name="Schlafen")
    project = _imported_project()
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        apartments=[Apartment(rooms=[room])])])])])
    taster = project.topology.areas[0].lines[0].devices[2]
    taster.room_id = room.id
    aktor = project.topology.areas[0].lines[0].devices[1]
    aktor.room_id, aktor.installation_location = room.id, "UV1"
    view = TopologyView()
    view.set_project(project)

    items = {}

    def walk(item):
        items[item.text(1)] = item
        for i in range(item.childCount()):
            walk(item.child(i))
    for i in range(view._tree.topLevelItemCount()):
        walk(view._tree.topLevelItem(i))

    hint = items["1.1.2"]
    assert hint.text(3) == "04 Schlafen"
    assert hint.foreground(3).color() == _COLOR_ROOM_HINT and hint.font(3).italic()
    assert taster.installation_location == ""
    assert items["1.1.1"].text(3) == "UV1"                 # ETS-Einbauort hat Vorrang
    assert not items["1.1.1"].font(3).italic()
