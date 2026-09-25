"""
Tests fuer GewerkChannelAssignDialog mit mehreren Elementen (z.B. "J ×2":
jeder Storen bekommt seinen eigenen Aktor-Kanal).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.ui.dialogs.gewerk_channel_assign_dialog import GewerkChannelAssignDialog


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project():
    room = Room(number="04", name="Essen / Küche")
    assignment = GewerkAssignment(gewerk_code="J", count=2)
    room.gewerk_assignments.append(assignment)
    floor = Floor(name="OG", short_code="OG", apartments=[Apartment(name="OG", rooms=[room])])
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])

    mg = MiddleGroup(number=1, name="Jalousie")
    gas = {}
    for element, base in ((1, 35), (2, 40)):
        for offset, fn in enumerate(("move", "step")):
            ga = GroupAddress(main_group=3, middle_group=1, sub_group=base + offset,
                              designation=f"J.OG.04.0{element}_{fn}")
            mg.group_addresses.append(ga)
            gas[(element, fn)] = ga
    structure = GroupAddressStructure()
    structure.main_groups.append(MainGroup(number=3, name="OG", middle_groups=[mg]))
    project.group_addresses = structure

    def actor(addr, channel, element):
        return Device(
            physical_address=addr, device_type="actor", product="Jalousieaktor",
            communication_objects=[
                CommunicationObject(object_number=1, name=channel, object_function="Auf/Ab",
                                    connected_gas=[gas[(element, "move")].address]),
                CommunicationObject(object_number=2, name=channel, object_function="Stopp",
                                    connected_gas=[gas[(element, "step")].address]),
            ],
        )
    line = Line(line_number=1)
    line.devices = [actor("1.1.4", "M7", 1), actor("1.1.5", "M9", 2)]
    project.topology = Topology(areas=[Area(area_number=1, lines=[line])])
    project.topology.is_imported = True
    return project, room, assignment, gas


def _choose(dlg, device_addr, channel):
    table = dlg._device_table
    row = next(r for r in range(table.rowCount())
               if table.item(r, 0).text() == device_addr)
    table.selectRow(row)
    dlg._on_device_chosen()
    dlg._channel_table.selectRow(dlg._channel_names.index(channel))
    dlg._on_channel_chosen()
    dlg._on_accept()


def test_two_elements_get_their_own_channel():
    project, room, assignment, gas = _project()
    gewerk = project.gewerk_catalog.get("J")
    dlg = GewerkChannelAssignDialog(project, room, assignment, gewerk)
    assert dlg._element_label.text().endswith("1 von 2")

    _choose(dlg, "1.1.4", "M7")
    assert dlg.result() != QDialog.Accepted
    assert dlg._element_label.text().endswith("2 von 2")
    assert dlg._btn_finish.text() == "Übernehmen"

    _choose(dlg, "1.1.5", "M9")
    assert dlg.result() == QDialog.Accepted
    assert dlg.linked_by_element[1]["AUF/AB"] == gas[(1, "move")].id
    assert dlg.linked_by_element[2]["AUF/AB"] == gas[(2, "move")].id
    assert dlg.linked_by_element[2]["STOPP"] == gas[(2, "step")].id


def test_skip_element():
    project, room, assignment, gas = _project()
    dlg = GewerkChannelAssignDialog(project, room, assignment, project.gewerk_catalog.get("J"))
    dlg._next_element()                 # Element 1 überspringen
    _choose(dlg, "1.1.5", "M9")
    assert dlg.result() == QDialog.Accepted
    assert list(dlg.linked_by_element) == [2]


def test_channel_of_other_element_is_marked():
    project, room, assignment, gas = _project()
    assignment.element_links(1)["AUF/AB"] = gas[(1, "move")].id
    dlg = GewerkChannelAssignDialog(project, room, assignment, project.gewerk_catalog.get("J"))
    dlg._selected_device = project.topology.areas[0].lines[0].devices[0]
    dlg._reload_channels()
    assert "Element 1" in dlg._channel_table.item(0, 2).text()


def test_assignment_round_trip_keeps_element_links():
    assignment = GewerkAssignment(gewerk_code="J", count=2, linked_ga_ids={"AUF/AB": "a"})
    assignment.element_links(2)["AUF/AB"] = "b"
    restored = GewerkAssignment.from_dict(assignment.to_dict())
    assert restored.all_element_links() == {1: {"AUF/AB": "a"}, 2: {"AUF/AB": "b"}}
