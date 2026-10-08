"""
DALI-Gruppen in geplanten Projekten (FA-2801, FA-2803): je LDA-Element eine
Gruppe mit allen GAs dieses Elements, Name aus der Bezeichnung (FA-403),
keine Gruppen-GAs als Gateway-Broadcast.
"""
from __future__ import annotations
import logging
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.dali_config import DaliGroup
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Device
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.dali_service import DaliService
from knix_arranger.services.topology_engine import TopologyEngine


def _project(variant: str = "A", labels=("Decke", "Wand")) -> KnxProject:
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="DALI-Test")
    project.config.mg_variant = variant
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    wohnen = Room(number="E01", name="Wohnen")
    lda = GewerkAssignment(gewerk_code="LDA", count=2)
    lda.set_element_labels(list(labels))
    wohnen.gewerk_assignments = [lda]
    kueche = Room(number="E02", name="Küche",
                  gewerk_assignments=[GewerkAssignment(gewerk_code="LDA", count=1)])
    floor.apartments = [Apartment(name="EG", rooms=[wohnen, kueche])]
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(floors=[floor])])])
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    regenerate_addresses(project)
    logging.disable(logging.NOTSET)
    return project


def _groups(project):
    (gw,) = project.dali_configs.values()
    return gw, sorted(gw.groups, key=lambda g: g.number)


@pytest.mark.parametrize("variant, rm_mg", [("A", 0), ("B", 6)])
def test_each_element_one_group_with_all_its_gas(variant, rm_mg):
    project = _project(variant)
    assert DaliService().configure_planned(project) == 3
    gw, groups = _groups(project)
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    assert [g.name for g in groups] == ["Wohnen Decke", "Wohnen Wand", "Küche"]
    for group in groups:
        gas = [by_address[a] for a in (group.ga_switch, group.ga_dim, group.ga_value,
                                       group.ga_status, group.ga_scene, group.ga_fault)]
        # alle GAs gehören zum selben Element
        assert len({(ga.room_id, ga.element_number) for ga in gas}) == 1
        assert [ga.function_name for ga in gas] == \
            ["E/A", "DIM", "WERT", "RM WERT", "SZENE", "STOERUNG"]
        assert by_address[group.ga_status].middle_group == rm_mg
    # keine Gruppen-GAs als Broadcast
    assert (gw.ga_switch_broadcast, gw.ga_dim_broadcast, gw.ga_scene) == ("", "", "")


def test_names_without_labels():
    project = _project(labels=())
    DaliService().configure_planned(project)
    _gw, groups = _groups(project)
    assert [g.name for g in groups] == ["Wohnen 1", "Wohnen 2", "Küche"]


def test_existing_groups_kept_and_wrong_broadcast_cleaned():
    project = _project()
    svc = DaliService()
    (device,) = svc.get_dali_gateways_from_topology(project)
    gw = svc.get_or_create(project, device.id)
    gw.groups = [DaliGroup(number=0, name="Von Hand")]
    gw.ga_switch_broadcast = "2/0/0"      # Gruppen-GA aus früherer Version
    gw.ga_dim_broadcast = "0/0/1"         # Zentraladresse von Hand: bleibt
    assert svc.configure_planned(project) == 0
    assert [g.name for g in gw.groups] == ["Von Hand"]
    assert gw.ga_switch_broadcast == "" and gw.ga_dim_broadcast == "0/0/1"
    # Neu ableiten ersetzt die Gruppen
    assert svc.rederive_groups(project, gw) == 3


def test_link_gas_never_uses_element_gas_in_planned_project():
    project = _project()
    svc = DaliService()
    (device,) = svc.get_dali_gateways_from_topology(project)
    gw = svc.get_or_create(project, device.id)
    svc.link_gas_from_structure(gw, project)
    element_gas = {ga.address for ga in project.group_addresses.all_addresses()
                   if ga.gewerk_code == "LDA" and ga.room_id}
    linked = {gw.ga_switch_broadcast, gw.ga_dim_broadcast, gw.ga_scene,
              gw.ga_status_value, gw.ga_status_fault} - {""}
    assert not linked & element_gas
    assert gw.ga_switch_broadcast == "" and gw.ga_dim_broadcast == ""
    # Szenenabruf darf eine Szenen-GA sein (das Gateway empfängt KNX-Szenen)
    assert gw.ga_scene in ("", "0/4/1")


def test_only_rooms_of_gateway_line_and_16_per_gateway():
    project = _project()
    svc = DaliService()
    (device,) = svc.get_dali_gateways_from_topology(project)
    line = next(ln for a in project.topology.areas for ln in a.lines if device in ln.devices)
    # Küche gehört nicht zur Linie des Gateways
    kueche = next(r for r in project.all_rooms if r.name == "Küche")
    line.assigned_room_ids = [r for r in line.assigned_room_ids if r != kueche.id]
    gw = svc.get_or_create(project, device.id)
    assert svc.derive_groups_from_planning(gw, device, project) == 2

    # zweites Gateway auf derselben Linie: erhält die Gruppen ab der 17.
    wohnen = next(r for r in project.all_rooms if r.name == "Wohnen")
    wohnen.gewerk_assignments[0].count = 18
    regenerate_addresses(project)
    second = Device(device_type="gateway", product="DALI-Gateway 16-fach")
    line.devices.append(second)
    gw2 = svc.get_or_create(project, second.id)
    assert svc.derive_groups_from_planning(gw, device, project) == 16
    assert svc.derive_groups_from_planning(gw2, second, project) == 2
    assert [g.number for g in gw2.groups] == [0, 1]
    assert gw2.groups[0].name == "Wohnen 17"


def test_group_addresses_in_dali_document(tmp_path):
    from knix_arranger.services.documentation_service import DocumentationService
    project = _project()
    DaliService().configure_planned(project)
    path = tmp_path / "dali.pdf"
    DocumentationService(project).generate_dali_device_list(str(path))
    with fitz.open(path) as doc:
        text = " ".join("".join(p.get_text() for p in doc).split())
    assert "Gruppen" in text and "Wohnen Decke" in text and "2/0/0" in text


def test_view_configures_planned_project():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.views.dali_config_view import DaliConfigView, _CG_NAME, _CG_SCENE
    project = _project()
    view = DaliConfigView(project)
    view.set_project(project)          # wie beim Öffnen der Ansicht im Hauptfenster
    assert view._groups_table.rowCount() == 3
    assert view._groups_table.item(0, _CG_NAME).text() == "Wohnen Decke"
    assert view._groups_table.item(0, _CG_SCENE).text() == "2/0/5"
    # Bearbeitung einer neuen Spalte wird gespeichert
    view._groups_table.item(0, _CG_SCENE).setText("2/0/7")
    (gw,) = project.dali_configs.values()
    assert sorted(gw.groups, key=lambda g: g.number)[0].ga_scene == "2/0/7"


def test_dali_list_in_revision_package_without_evgs(tmp_path):
    from knix_arranger.services.documentation_service import DocumentationService
    project = _project()
    assert project.dali_configs == {}          # DALI-Ansicht nie geöffnet
    DocumentationService(project).generate_revision_package(str(tmp_path), parts={"dali"})
    assert (tmp_path / "DALI-Test_DALI_Geraete.pdf").exists()
    (gw,) = project.dali_configs.values()
    assert not gw.devices and len(gw.groups) == 3


# ── Bemessung und Zuordnung (Projekt_23: 28 Elemente auf einem "32-fach") ────

def _big_project(elements: int = 20) -> KnxProject:
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="DALI gross")
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    rooms = [Room(number=f"E{i:02d}", name=f"Raum {i}",
                  gewerk_assignments=[GewerkAssignment(gewerk_code="LDA", count=2)])
             for i in range(1, elements // 2 + 1)]
    floor.apartments = [Apartment(name="EG", rooms=rooms)]
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(floors=[floor])])])
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    from knix_arranger.services.recalc_service import RecalcService
    RecalcService().recalc_actors_and_addresses(project)
    logging.disable(logging.NOTSET)
    return project


def test_more_than_16_elements_need_second_gateway_with_matching_groups():
    from knix_arranger.services.belegungsplan_service import BelegungsplanService
    project = _big_project(20)
    gateways = DaliService().get_dali_gateways_from_topology(project)
    assert len(gateways) == 2
    assert all("16-fach" in g.product for g in gateways)
    assert sorted(len(c.groups) for c in project.dali_configs.values()) == [4, 16]
    rows = [r for r in BelegungsplanService().generate(project).actor_rows
            if r.gewerk_code == "LDA" and r.function_name == "E/A"]
    assert len(rows) == 20
    # jedes Element hat eine Gruppe, und Gruppe = Kanal - 1
    assert all(r.dali_group == int(r.channel_number) - 1 for r in rows)
    assert all(r.channel_label == f"Gr. {r.dali_group}" for r in rows)


def test_config_follows_gateway_address_and_keeps_evgs():
    from knix_arranger.models.dali_config import DaliDevice
    project = _project()
    svc = DaliService()
    svc.configure_planned(project)
    (device,) = svc.get_dali_gateways_from_topology(project)
    gw, _groups_ = _groups(project)
    gw.devices = [DaliDevice(short_address=0, name="EVG Decke")]
    assert gw.gateway_address == device.physical_address
    # Neuberechnung legt das Gateway mit neuer ID an
    old_id = device.id
    device.id = "neue-id"
    svc.configure_planned(project)
    assert list(project.dali_configs) == ["neue-id"]
    assert project.dali_configs["neue-id"] is gw and gw.devices[0].name == "EVG Decke"
    assert old_id not in project.dali_configs


def test_orphan_config_without_evgs_removed_with_evgs_kept():
    from knix_arranger.models.dali_config import DaliDevice, DaliGateway
    project = _project()
    project.dali_configs["weg"] = DaliGateway(gateway_device_id="weg", name="alt")
    project.dali_configs["bleibt"] = DaliGateway(
        gateway_device_id="bleibt", name="mit EVG", devices=[DaliDevice(short_address=1)])
    DaliService().configure_planned(project)
    assert "weg" not in project.dali_configs
    assert "bleibt" in project.dali_configs
