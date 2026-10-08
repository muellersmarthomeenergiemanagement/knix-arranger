"""
GAs löschen in der Baumansicht: generierte werden zur Reserve (Funktion
weggelassen), manuelle und importierte entfernt – samt Verweisen.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, GewerkAssignment, Room,
    SensorFunktion, Wing,
)
from knix_arranger.models.dali_config import DaliGateway, DaliGroup
from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.address_generator import insert_ga, regenerate_addresses
from knix_arranger.services.ga_delete import (
    DELETABLE, GENERATED, KEEP, classify, delete_gas, omitted_function_of, restore_function,
)
from knix_arranger.services.topology_engine import TopologyEngine


def _project(gewerk_catalog) -> KnxProject:
    room = Room(number="E01", name="Wohnen")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="J", count=2)]
    floor = Floor(name="EG", short_code="EG", main_group_number=1,
                  apartments=[Apartment(name="Wohnung", rooms=[room])])
    project = KnxProject(name="Löschen")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    regenerate_addresses(project)
    return project


def _ga(project, element: int, function: str) -> GroupAddress:
    return next(g for g in project.group_addresses.all_addresses()
                if g.gewerk_code == "J" and g.element_number == element
                and g.function_name == function)


def _addresses(project) -> dict[str, str]:
    return {g.address: g.designation for g in project.group_addresses.all_addresses()}


def test_generated_ga_becomes_reserve_and_stays_omitted(gewerk_catalog):
    project = _project(gewerk_catalog)
    sperren = _ga(project, 1, "SPERREN")
    before = _addresses(project)
    assert classify(project, sperren)[0] == GENERATED

    result = delete_gas(project, [sperren])
    assert result.omitted == [sperren.address]
    after = _addresses(project)
    assert set(after) == set(before)                      # keine Adresse verschoben
    reserve = next(g for g in project.group_addresses.all_addresses()
                   if g.address == sperren.address)
    assert reserve.is_placeholder and omitted_function_of(reserve) == "SPERREN"
    assert _ga(project, 2, "SPERREN")                      # Element 2 unberührt

    regenerate_addresses(project)                          # bleibt weggelassen
    reserve = next(g for g in project.group_addresses.all_addresses()
                   if g.address == sperren.address)
    assert reserve.is_placeholder
    assert project.all_rooms[0].gewerk_assignments[0].omitted_functions == {1: ["SPERREN"]}


def test_restore_function(gewerk_catalog):
    project = _project(gewerk_catalog)
    sperren = _ga(project, 1, "SPERREN")
    address = sperren.address
    delete_gas(project, [sperren])
    reserve = next(g for g in project.group_addresses.all_addresses() if g.address == address)
    assert restore_function(project, reserve)
    restored = next(g for g in project.group_addresses.all_addresses() if g.address == address)
    assert restored.function_name == "SPERREN" and not restored.is_placeholder
    assert restored.description == ""
    assert project.all_rooms[0].gewerk_assignments[0].omitted_functions == {}


def test_manual_ga_removed_with_references(gewerk_catalog):
    project = _project(gewerk_catalog)
    manual = GroupAddress(main_group=1, middle_group=5, sub_group=7,
                          designation="Treppenlicht", is_manual=True)
    insert_ga(project.group_addresses, manual)
    room = project.all_rooms[0]
    room.bedienelemente = [Bedienelement(element_type="Tastereinheit", funktionen=[
        SensorFunktion(ga_designation="1/5/7 Treppenlicht")])]
    project.scenes = [Scene(name="Abend", scene_number=1, actions=[
        SceneAction(group_address="Treppenlicht", ga_address="1/5/7", value="Ein"),
        SceneAction(group_address=_ga(project, 1, "AUF/AB").designation, value="Ab")])]
    project.dali_configs = {"gw": DaliGateway(groups=[DaliGroup(ga_switch="1/5/7")])}
    device = Device(physical_address="1.1.30", device_type="actor", communication_objects=[
        CommunicationObject(object_number=1, connected_gas=["1/5/7", "1/1/0"])])
    project.topology.areas[0].lines[0].devices.append(device)
    project.ets_corrections.unlinked = ["1.1.30|1|1/5/7", "1.1.30|1|1/5/70"]

    assert classify(project, manual)[0] == DELETABLE
    result = delete_gas(project, [manual])
    assert result.deleted == ["1/5/7"]
    assert "1/5/7" not in _addresses(project)
    assert room.bedienelemente[0].funktionen[0].ga_designation == ""
    assert [a.value for a in project.scenes[0].actions] == ["Ab"]
    assert project.dali_configs["gw"].groups[0].ga_switch == ""
    assert device.communication_objects[0].connected_gas == ["1/1/0"]
    assert project.ets_corrections.unlinked == ["1.1.30|1|1/5/70"]   # exakter Vergleich


def test_imported_ga_is_deleted(gewerk_catalog):
    project = _project(gewerk_catalog)
    project.topology.is_imported = True
    ga = _ga(project, 1, "AUF/AB")
    assert classify(project, ga)[0] == DELETABLE
    delete_gas(project, [ga])
    assert ga.address not in _addresses(project)


def test_reserve_and_central_are_kept(gewerk_catalog):
    project = _project(gewerk_catalog)
    reserve = next(g for g in project.group_addresses.all_addresses() if g.is_placeholder)
    central = next(g for g in project.group_addresses.all_addresses()
                   if g.main_group == 0 and not g.is_placeholder)
    assert classify(project, reserve)[0] == KEEP
    assert classify(project, central)[0] == KEEP
    result = delete_gas(project, [reserve, central])
    assert len(result.kept) == 2 and not result.deleted and not result.omitted


def test_omitted_functions_saved(gewerk_catalog):
    assignment = GewerkAssignment(gewerk_code="J", count=2)
    assignment.omitted_functions = {2: ["SPERREN", "BESCHATTUNG"]}
    loaded = GewerkAssignment.from_dict(assignment.to_dict())
    assert loaded.omitted_functions == {2: ["SPERREN", "BESCHATTUNG"]}


def test_tree_view_deletes_selection(gewerk_catalog, monkeypatch):
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication, QMessageBox
    from knix_arranger.ui.views.address_tree_view import AddressTreeView
    QApplication.instance() or QApplication([])
    project = _project(gewerk_catalog)
    view = AddressTreeView()
    bus = MagicMock()
    view.set_bus(bus)
    view.set_project(project)
    view.set_structure(project.group_addresses)
    targets = {_ga(project, 1, "SPERREN").address, _ga(project, 2, "SPERREN").address}

    def items(item):
        yield item
        for i in range(item.childCount()):
            yield from items(item.child(i))
    for item in items(view._tree.invisibleRootItem()):
        if item.data(0, view.GA_OBJECT_ROLE) is not None and \
                item.data(0, view.GA_OBJECT_ROLE).address in targets:
            item.setSelected(True)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    emitted = []
    view.ga_modified.connect(lambda: emitted.append(True))
    view._delete_selected()
    assert asked and "2 GA löschen?" in asked[0] and "Reserve" in asked[0]
    bus.begin_change.assert_called_once()
    assert emitted
    reserves = [g for g in project.group_addresses.all_addresses() if g.address in targets]
    assert all(g.is_placeholder for g in reserves)
