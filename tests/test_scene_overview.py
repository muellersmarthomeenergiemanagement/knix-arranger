"""Szenen nach Szenen-Adresse: gemeinsamer Service, Szenen-Verwaltung (FA-1812)."""
from __future__ import annotations
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import patch

from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.scene_overview import build_scene_overview, linked_devices


def _project() -> KnxProject:
    project = KnxProject(name="Chalet")
    kueche = Room(number="05", name="Küche")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        name="OG", short_code="OG", apartments=[Apartment(name="Chalet", rooms=[kueche])])])])])
    gas = [
        GroupAddress(main_group=0, middle_group=4, sub_group=1, designation="Anwesendheit Chalet",
                     datapoint_type="DPST-18-1", comment="#1: Anwesend"),
        GroupAddress(main_group=0, middle_group=2, sub_group=150, designation="WP Betriebsart",
                     datapoint_type="DPST-26-1"),
        GroupAddress(main_group=2, middle_group=4, sub_group=0, designation="Raum1_Szene High",
                     datapoint_type="DPST-1-1"),
    ]
    project.group_addresses = GroupAddressStructure(main_groups=[
        MainGroup(number=n, middle_groups=[MiddleGroup(number=m, group_addresses=[
            g for g in gas if (g.main_group, g.middle_group) == (n, m)]) for m in range(8)])
        for n in (0, 2)])

    def detected(name, number, addr, kind="dpt"):
        return Scene(name=name, scene_number=number, scope="central", is_detected=True,
                     detection_kind=kind, source_ga_addresses=[addr])
    project.scenes = [
        detected("Anwesendheit Chalet", 0, "0/4/1"),
        detected("Anwesend", 1, "0/4/1"),
        detected("Abwesend", 2, "0/4/1"),
        detected("WP Betriebsart", 0, "0/2/150"),
        detected("High (Carnozet)", 0, "2/4/0", kind="pattern"),
        Scene(name="Kochen", scene_number=1, scope="room", scope_id=kueche.id),
        Scene(name="Essen", scene_number=2, scope="room", scope_id=kueche.id),
    ]
    taster = Device(physical_address="1.1.61", device_type="sensor", product="Taster",
                    communication_objects=[CommunicationObject(
                        object_number=0, name="Taste 1, links", object_function="senden, Wert",
                        flags="K--Ü--", connected_gas=["0/4/1"])])
    aktor = Device(physical_address="1.1.10", device_type="actor", product="Schaltaktor",
                   communication_objects=[CommunicationObject(
                       object_number=17, name="Ausgang A", object_function="8-Bit-Szene",
                       flags="KS----", connected_gas=["0/4/1"])])
    dali = Device(physical_address="1.1.8", device_type="gateway", product="DALI-Gateway",
                  communication_objects=[CommunicationObject(
                      object_number=5, name="Szene", flags="", connected_gas=["0/4/1"])])
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1,
                                                               devices=[aktor, dali, taster])])]
    return project, kueche


def test_einteilung_nach_adresse():
    project, _kueche = _project()
    overview = build_scene_overview(project)
    keys = [g.key for g in overview.addresses]
    assert keys == ["0/4/1", "geplant:Szenenaufruf Küche"]        # bestehende zuerst
    chalet = overview.addresses[0]
    assert chalet.channel.name == "Anwesendheit Chalet"            # Kanal ist keine Szene
    assert [(s.scene_number, s.name) for s in chalet.scenes] == [(1, "Anwesend"), (2, "Abwesend")]
    assert chalet.free_number() == 3
    kueche = overview.addresses[1]
    assert kueche.planned and [s.name for s in kueche.scenes] == ["Kochen", "Essen"]
    assert [s.name for s in overview.visu] == ["High (Carnozet)"]
    assert [g.designation for g in overview.unclear] == ["WP Betriebsart"]


def test_sender_und_empfaenger():
    project, _kueche = _project()
    links = linked_devices(project, "0/4/1")
    assert [(l.device.physical_address, l.role) for l in links] == [
        ("1.1.61", "sendet"), ("1.1.8", "empfängt"), ("1.1.10", "empfängt")]
    assert links[2].objects == ["17: Ausgang A – 8-Bit-Szene"]


# ── Szenen-Verwaltung ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _view(project):
    from knix_arranger.ui.views.scene_view import SceneView
    view = SceneView()
    view.set_project(project)
    return view


def _top_texts(view):
    return [view._tree.topLevelItem(i).text(0) for i in range(view._tree.topLevelItemCount())]


def test_baum_zeigt_adressen_mit_szenen(qapp):
    project, _kueche = _project()
    view = _view(project)
    tops = _top_texts(view)
    assert tops[0].startswith("0/4/1") and "Anwesendheit Chalet" in tops[0]
    assert tops[1] == "Szenenaufruf Küche  (wird in Schritt 10 erzeugt)"
    assert tops[2] == "Szenen der Visualisierung (1)"
    assert tops[3] == "Nicht eindeutig (1)"
    chalet = view._tree.topLevelItem(0)
    assert [(chalet.child(i).text(1), chalet.child(i).text(0))
            for i in range(chalet.childCount())] == [("1", "Anwesend"), ("2", "Abwesend")]
    assert not view._tree.topLevelItem(2).isExpanded()        # Visu zugeklappt


def test_geltungsbereich_gilt_fuer_alle_szenen_der_adresse(qapp):
    project, kueche = _project()
    view = _view(project)
    group = view._overview.addresses[1]
    view._select_scene(group)
    view._scene_scope.setCurrentIndex(view._scene_scope.findData("central"))
    view._apply_address_changes()
    assert [(s.scope, s.scope_id) for s in project.scenes if s.name in ("Kochen", "Essen")] \
        == [("central", ""), ("central", "")]


def test_doppelte_nummer_wird_abgelehnt(qapp):
    project, _kueche = _project()
    view = _view(project)
    essen = next(s for s in project.scenes if s.name == "Essen")
    view._select_scene(essen)
    view._scene_number.setValue(1)                             # gehört "Kochen"
    with patch("knix_arranger.ui.views.scene_view.QMessageBox.warning") as warning:
        view._apply_changes()
    warning.assert_called_once()
    assert essen.scene_number == 2


def test_szene_auf_andere_adresse_verschieben(qapp):
    project, _kueche = _project()
    view = _view(project)
    essen = next(s for s in project.scenes if s.name == "Essen")
    view._select_scene(essen)
    view._scene_address.setCurrentIndex(view._scene_address.findData("0/4/1"))
    view._scene_number.setValue(3)
    view._apply_changes()
    assert essen.source_ga_addresses == ["0/4/1"] and essen.scope == "central"
    chalet = view._overview.addresses[0]
    assert [s.name for s in chalet.scenes] == ["Anwesend", "Abwesend", "Essen"]


def test_erkannte_szene_nicht_verschiebbar(qapp):
    project, _kueche = _project()
    view = _view(project)
    view._select_scene(next(s for s in project.scenes if s.name == "Anwesend"))
    assert not view._scene_address.isEnabled()
    assert view._address_group.isVisible() or not view.isVisible()


def test_neue_adresse_mit_geltungsbereich(qapp):
    project, kueche = _project()
    view = _view(project)
    with patch("knix_arranger.ui.views.scene_view.QInputDialog.getItem",
               return_value=("Raum 05 Küche", True)):
        view._add_scene()
    new = project.scenes[-1]
    assert (new.scope, new.scope_id, new.scene_number) == ("room", kueche.id, 3)
    assert view._get_selected_scene() is new
