"""
Tests für das Zusammenführen zweier Räume (Schritt 3, "Zusammenführen…").

Auslöser: Projekt_23 – Raum CDG07 Halle sollte samt Gewerken, Taster 1.1.106
und Tastenbelegung in CDG01 Galerie aufgehen und danach gelöscht werden.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, GewerkAssignment, Room,
    SensorFunktion, Wing,
)
from knix_arranger.models.dali_config import DaliGateway, DaliGroup
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.recalc_service import RecalcService
from knix_arranger.services.room_merge import merge_problem, merge_rooms
from knix_arranger.services.topology_engine import TopologyEngine


def _project(gewerk_catalog):
    galerie = Room(number="E01", name="Galerie")
    galerie.gewerk_assignments = [
        GewerkAssignment(gewerk_code="J", count=1, element_labels=["Ost"]),
    ]
    halle = Room(number="E02", name="Halle")
    halle.gewerk_assignments = [
        GewerkAssignment(gewerk_code="LD", count=1, element_labels=["Spots"]),
        GewerkAssignment(gewerk_code="J", count=2, element_labels=["Panorama", "Treppe"]),
    ]
    flur = Room(number="E03", name="Flur")
    flur.bedienelemente = [Bedienelement(
        element_type="Tastereinheit", taster_index=1,
        funktionen=[SensorFunktion(gewerk_code="J", element_number=2,
                                   source_room_id=halle.id)],
    )]
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=1)
    floor.apartments = [Apartment(name="Wohnung", rooms=[galerie, halle, flur])]
    areal = Areal(buildings=[Building(name="Haus", wings=[Wing(name="Haus", floors=[floor])])])

    project = KnxProject(name="Test")
    project.areal = areal
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(areal)
    RecalcService().recalc_actors_and_addresses(project)
    return project, galerie, halle, flur


def _gas_of(project, room):
    return {ga.address: ga.designation for ga in project.group_addresses.all_addresses()
            if ga.room_id == room.id}


def test_merge_moves_gewerke_and_deletes_source(gewerk_catalog):
    project, galerie, halle, _flur = _project(gewerk_catalog)
    merge_rooms(project, halle, galerie)
    assert halle not in project.all_rooms
    codes = {g.gewerk_code: g for g in galerie.gewerk_assignments}
    assert codes["LD"].element_labels == ["Spots"]
    # gleiche Gewerke zusammengezählt, Elemente des Quellraums hinten angehängt
    assert codes["J"].count == 3
    assert codes["J"].element_labels == ["Ost", "Panorama", "Treppe"]
    assert not any(halle.id in l.assigned_room_ids
                   for a in project.topology.areas for l in a.lines)


def test_taste_in_other_room_follows_element(gewerk_catalog):
    project, galerie, halle, flur = _project(gewerk_catalog)
    merge_rooms(project, halle, galerie)
    sf = flur.bedienelemente[0].funktionen[0]
    # Treppe war Element 2 in der Halle, ist jetzt Element 3 in der Galerie
    assert (sf.source_room_id, sf.element_number) == (galerie.id, 3)


def test_tastereinheit_moves_with_next_free_number(gewerk_catalog):
    project, galerie, halle, _flur = _project(gewerk_catalog)
    halle.bedienelemente.append(Bedienelement(
        element_type="Tastereinheit", taster_index=1, participant_number="1.1.106",
        funktionen=[SensorFunktion(gewerk_code="J", element_number=1)],
    ))
    galerie.bedienelemente.append(Bedienelement(element_type="Tastereinheit", taster_index=1))
    merge_rooms(project, halle, galerie)
    moved = next(be for be in galerie.bedienelemente if be.participant_number == "1.1.106")
    assert moved.taster_index == 2
    sf = moved.funktionen[0]
    # Panorama: Element 1 der Halle → Element 2 der Galerie, jetzt eigener Raum
    assert (sf.source_room_id, sf.element_number) == ("", 2)


def test_gas_keep_addresses_and_get_target_name(gewerk_catalog):
    """Gewerke, die nur im Quellraum vorkommen, behalten ihre Adressen;
    gleiche Gewerke bilden einen grösseren Block (neue Adressen erlaubt,
    Planungsphase). Keine GA geht verloren, alle tragen den Zielraum."""
    project, galerie, halle, _flur = _project(gewerk_catalog)
    before = _gas_of(project, halle)
    ld_before = {a for a, d in before.items() if d.startswith("LD_")}
    total = len(project.group_addresses.all_addresses())
    merge_rooms(project, halle, galerie)
    RecalcService().recalc_actors_and_addresses(project)
    after = _gas_of(project, galerie)
    assert ld_before and ld_before <= set(after)
    assert len(project.group_addresses.all_addresses()) == total
    assert not _gas_of(project, halle)
    assert all("E01" in d and "Halle" not in d for d in after.values())
    assert sum(d.startswith("J_E01_03 AUF/AB") for d in after.values()) == 1


def test_dali_group_and_scene_names_follow(gewerk_catalog):
    project, galerie, halle, _flur = _project(gewerk_catalog)
    ld, label = next((a, d) for a, d in _gas_of(project, halle).items()
                     if d.startswith("LD_"))
    project.dali_configs = {"gw": DaliGateway(groups=[
        DaliGroup(name="Halle Spots", ga_switch=ld)])}
    project.scenes = [Scene(name=label, scope="central", actions=[
        SceneAction(group_address=label, ga_address=ld)])]
    merge_rooms(project, halle, galerie)
    # Umbenennung beim Zusammenführen (die Neuberechnung entfernt danach die
    # Test-Konfiguration, sie gehört zu keinem Gateway)
    assert project.dali_configs["gw"].groups[0].name == "Galerie Spots"
    RecalcService().recalc_actors_and_addresses(project)
    new_label = _gas_of(project, galerie)[ld]
    assert project.scenes[0].actions[0].group_address == new_label
    assert project.scenes[0].name == new_label


def test_scene_labels_follow_room_rename(gewerk_catalog):
    """Auch ohne Zusammenführen: Raum umbenannt → erkannte Szene nachgeführt."""
    project, _galerie, halle, _flur = _project(gewerk_catalog)
    address, label = next(iter(_gas_of(project, halle).items()))
    project.scenes = [Scene(name="Abend", actions=[
        SceneAction(group_address=label, ga_address=address)])]
    halle.name = "Eingangshalle"
    regenerate_addresses(project)
    action = project.scenes[0].actions[0]
    assert "Eingangshalle" in action.group_address
    assert project.scenes[0].name == "Abend"   # eigener Name bleibt


@pytest.mark.parametrize("case", ["same", "imported", "product", "too_many"])
def test_merge_problem(gewerk_catalog, case):
    project, galerie, halle, _flur = _project(gewerk_catalog)
    if case == "same":
        assert merge_problem(project, halle, halle)
        return
    if case == "imported":
        project.topology.is_imported = True
    elif case == "product":
        halle.gewerk_assignments[1].linked_product = {"order_number": "X"}
    elif case == "too_many":
        halle.gewerk_assignments[1].count = 20
    assert merge_problem(project, halle, galerie)
    with pytest.raises(ValueError):
        merge_rooms(project, halle, galerie)
    assert halle in project.all_rooms


def test_no_problem_for_normal_merge(gewerk_catalog):
    project, galerie, halle, _flur = _project(gewerk_catalog)
    assert merge_problem(project, halle, galerie) == ""


def test_step03_button_merges_selected_room(gewerk_catalog, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from knix_arranger.ui.wizard.step03_rooms import Step03Rooms, _KIND_ROOM
    QApplication.instance() or QApplication([])
    project, galerie, halle, _flur = _project(gewerk_catalog)
    step = Step03Rooms(project)
    step.on_enter()
    step._select_by_data(_KIND_ROOM, halle)
    monkeypatch.setattr(QInputDialog, "getItem",
                        lambda *a, **k: ("E01 Galerie", True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    step._merge_room()
    assert halle not in project.all_rooms
    assert step._tree.currentItem().data(0, 256)[1] is galerie
