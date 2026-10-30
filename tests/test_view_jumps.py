"""
Sprünge zwischen Ansichten, Paket 2 (FA-1011b bis FA-1011f): GA zu Szenen
und Zeitprogrammen, Raum zu Geräten und GAs, Gerät zur Materialliste,
Verlauf für Zurück/Vorwärts.
"""
from __future__ import annotations
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.models.time_program import DayProfile, SwitchPoint, TimeProgram
from knix_arranger.models.topology import Device
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.report_service import ReportService
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.ui.jump_menu import add_ga_jump_menus
from knix_arranger.ui.view_jumps import ViewHistory, ViewJumps
from knix_arranger.ui.views.address_tree_view import AddressTreeView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _project(gewerk_catalog):
    wohnen = Room(number="01", name="Wohnen")
    wohnen.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
    kueche = Room(number="02", name="Küche")
    kueche.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
    wohnung = Apartment(name="Wohnung", rooms=[wohnen, kueche])
    floor = Floor(name="EG", short_code="EG", main_group_number=1, apartments=[wohnung])
    project = KnxProject(name="Sprünge")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    regenerate_addresses(project)
    return project, wohnen, kueche


def _ga(project, room):
    return next(g for g in project.group_addresses.all_addresses()
                if g.room_id == room.id and g.function_name == "E/A")


def _jumps(project):
    return ViewJumps(SimpleNamespace(_project=project))


class TestHistory:
    def test_back_and_forward(self):
        h = ViewHistory()
        for key in ("overview", "topology", "addresses"):
            h.visit(key)
        assert h.back() == "topology"
        assert h.back() == "overview"
        assert h.back() is None
        assert h.forward() == "topology"
        assert h.can_forward()

    def test_visit_after_back_drops_forward(self):
        h = ViewHistory()
        for key in ("overview", "topology", "addresses"):
            h.visit(key)
        h.back()
        h.visit("scenes")
        assert not h.can_forward()
        assert h.back() == "topology"

    def test_same_view_twice_is_one_entry(self):
        h = ViewHistory()
        h.visit("topology")
        h.visit("topology")
        assert not h.can_back()


class TestScenesAndPrograms:
    def test_scenes_with_value_and_call_address(self, gewerk_catalog):
        project, wohnen, _k = _project(gewerk_catalog)
        ga = _ga(project, wohnen)
        scene = Scene(name="Kino", scene_number=3, scope="central",
                      actions=[SceneAction(group_address=ga.designation, value="Aus")])
        other = Scene(name="Hell", scene_number=4, scope="central")
        project.scenes = [scene, other]
        found = _jumps(project).scenes_with(ga)
        assert found == [(scene, "Szene 3 Kino – Wert Aus")]

    def test_programs_with_switch_points_on_ga(self, gewerk_catalog):
        project, wohnen, kueche = _project(gewerk_catalog)
        ga = _ga(project, wohnen)
        tp = TimeProgram(name="Morgen", day_profiles=[DayProfile(switch_points=[
            SwitchPoint(fixed_time="06:30", target_ga_id=ga.id),
            SwitchPoint(fixed_time="07:00", target_ga_id=_ga(project, kueche).id)])])
        off = TimeProgram(name="Ferien", active=False, day_profiles=[DayProfile(
            switch_points=[SwitchPoint(fixed_time="09:00", target_ga_id=ga.id)])])
        project.time_programs = [tp, off]
        found = _jumps(project).programs_with(ga)
        assert [t for t, _l in found] == [tp, off]
        assert "06:30" in found[0][1] and "07:00" not in found[0][1]
        assert "(inaktiv)" in found[1][1]

    def test_ga_menu_has_three_jump_menus(self, gewerk_catalog):
        project, wohnen, _k = _project(gewerk_catalog)
        menu = QMenu()
        add_ga_jump_menus(menu, _jumps(project), _ga(project, wohnen))
        titles = [a.text() for a in menu.actions() if a.menu()]
        assert titles == ["In Topologie zeigen", "In Szenen zeigen", "Im Zeitprogramm zeigen"]

    def test_no_jump_menus_for_reserve(self, gewerk_catalog):
        project, wohnen, _k = _project(gewerk_catalog)
        ga = _ga(project, wohnen)
        ga.is_placeholder = True
        menu = QMenu()
        add_ga_jump_menus(menu, _jumps(project), ga)
        assert menu.isEmpty()


class TestRoom:
    def test_room_ga_addresses_only_own_room(self, gewerk_catalog):
        project, wohnen, kueche = _project(gewerk_catalog)
        addresses = ReportService(project).room_ga_addresses(wohnen.id)
        assert _ga(project, wohnen).address in addresses
        assert _ga(project, kueche).address not in addresses

    def test_tree_shows_only_room_gas(self, gewerk_catalog):
        project, wohnen, kueche = _project(gewerk_catalog)
        tree = AddressTreeView()
        tree.set_structure(project.group_addresses)
        addresses = ReportService(project).room_ga_addresses(wohnen.id)
        assert tree.show_only(addresses, "Raum 01 Wohnen") == len(addresses)
        visible = {i.data(0, 256) for i in _leaves(tree) if not i.isHidden()}
        assert visible == addresses

    def test_jump_to_other_ga_lifts_room_filter(self, gewerk_catalog):
        project, wohnen, kueche = _project(gewerk_catalog)
        tree = AddressTreeView()
        tree.set_structure(project.group_addresses)
        tree.show_only(ReportService(project).room_ga_addresses(wohnen.id), "Raum")
        other = _ga(project, kueche).address
        assert tree.select_address(other)
        assert tree._only is None
        assert tree._tree.currentItem().text(0) == other

    def test_room_of_device_over_bedienelement(self, gewerk_catalog):
        project, wohnen, _k = _project(gewerk_catalog)
        wohnen.bedienelemente.append(Bedienelement(participant_number="1.1.40"))
        jumps = _jumps(project)
        assert jumps.room_of_device(Device(physical_address="1.1.40")) == wohnen.id
        assert jumps.room_of_device(Device(physical_address="1.1.41")) == ""
        assert jumps.room_of_device(Device(room_id="abc")) == "abc"


def _leaves(tree):
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(tree._tree)
    while it.value():
        if it.value().data(0, tree.GA_OBJECT_ROLE) is not None:
            yield it.value()
        it += 1


class TestTargets:
    def test_time_program_selects_switch_point(self, gewerk_catalog):
        from knix_arranger.ui.views.time_program_view import TimeProgramView
        project, wohnen, kueche = _project(gewerk_catalog)
        ga = _ga(project, wohnen)
        target = SwitchPoint(fixed_time="22:00", target_ga_id=ga.id)
        first = TimeProgram(name="Küche", day_profiles=[DayProfile(switch_points=[
            SwitchPoint(fixed_time="06:00", target_ga_id=_ga(project, kueche).id)])])
        tp = TimeProgram(name="Abend", day_profiles=[
            DayProfile(switch_points=[SwitchPoint(fixed_time="07:00")]),
            DayProfile(switch_points=[SwitchPoint(fixed_time="21:00"), target])])
        project.time_programs = [first, tp]
        view = TimeProgramView(project)
        view.set_project(project)
        assert view.select_switch_point(tp, ga.id)
        assert view._current_tp is tp
        assert view._current_dp is tp.day_profiles[1]
        row = view._sp_table.currentRow()
        assert view._sp_table.item(row, 0).data(256) == target.id

    def test_scene_view_selects_scene(self, gewerk_catalog):
        from knix_arranger.ui.views.scene_view import SceneView
        project, wohnen, _k = _project(gewerk_catalog)
        scene = Scene(name="Kino", scene_number=3, scope="room", scope_id=wohnen.id)
        project.scenes = [Scene(name="Hell", scene_number=1, scope="central"), scene]
        view = SceneView()
        view.set_project(project)
        assert view.select_scene(scene)

    def test_scene_action_address_over_designation(self, gewerk_catalog):
        from knix_arranger.ui.views.scene_view import SceneView
        project, wohnen, _k = _project(gewerk_catalog)
        ga = _ga(project, wohnen)
        view = SceneView()
        view.set_project(project)
        assert view._action_address(SceneAction(group_address=ga.designation)) == ga.address
        assert view._action_address(SceneAction(ga_address="5/5/5")) == "5/5/5"
        assert view._action_address(SceneAction(group_address="unbekannt")) == ""

    def test_material_list_selects_device(self, gewerk_catalog):
        from knix_arranger.ui.views.material_list_view import MaterialListView
        project, _w, _k = _project(gewerk_catalog)
        device = Device(physical_address="1.1.77", device_type="actor", product="Schaltaktor")
        project.topology.areas[0].lines[0].devices.append(device)
        view = MaterialListView()
        view.set_project(project)
        assert view.select_device(device)
        row = view._table.currentRow()
        entry_id = view._table.item(row, 0).data(256)
        entry = next(e for e in view._material_list.entries if e.id == entry_id)
        assert device.physical_address in entry.physical_addresses or entry.device_id == device.id
