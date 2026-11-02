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

    def test_ga_menu_has_five_jump_menus(self, gewerk_catalog):
        project, wohnen, _k = _project(gewerk_catalog)
        menu = QMenu()
        add_ga_jump_menus(menu, _jumps(project), _ga(project, wohnen))
        titles = [a.text() for a in menu.actions() if a.menu()]
        assert titles == ["In Topologie zeigen", "Gewerk im Raum zeigen", "In Szenen zeigen",
                          "Im Zeitprogramm zeigen", "In ETS-Funktionen zeigen"]

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


class TestGewerk:
    """FA-1011j: Gewerk eines Raums zu Geräten und GAs."""

    def _two_elements(self, gewerk_catalog):
        project, wohnen, kueche = _project(gewerk_catalog)
        assignment = wohnen.gewerk_assignments[0]
        assignment.count = 2
        assignment.set_element_labels(["Decke", "Wand"])
        regenerate_addresses(project)
        return project, wohnen, kueche, assignment

    def test_room_gewerk_addresses_per_element(self, gewerk_catalog):
        project, wohnen, kueche, _a = self._two_elements(gewerk_catalog)
        found = ReportService(project).room_gewerk_addresses(wohnen.id, "L")
        assert sorted(found) == [1, 2]
        own = {g.address for g in project.group_addresses.all_addresses()
               if g.room_id == wohnen.id and g.gewerk_code == "L" and not g.is_placeholder}
        assert {a for addrs in found.values() for a in addrs} == own
        assert _ga(project, kueche).address not in found[1]
        assert ReportService(project).room_gewerk_addresses(wohnen.id, "J") == {}

    def test_devices_of_gewerk_once_per_element(self, gewerk_catalog):
        project, wohnen, _k, assignment = self._two_elements(gewerk_catalog)
        actor = Device(physical_address="1.1.5")
        view = SimpleNamespace(linked_devices=lambda a: [((actor, f"KO {a}"), f"1.1.5 Aktor – {a}")])
        jumps = ViewJumps(SimpleNamespace(_project=project, _topology_view=view,
                                          _refresh_view=lambda key: None))
        found = jumps.devices_of_gewerk(wohnen, assignment)
        assert [t[0] for t, _l in found] == [actor, actor]
        assert found[0][1].startswith("1 Decke: 1.1.5 Aktor")
        assert found[1][1].startswith("2 Wand: 1.1.5 Aktor")
        _d, address, row = found[0][0]
        assert row == f"KO {address}"

    def test_gewerk_menu(self, gewerk_catalog):
        from knix_arranger.ui.jump_menu import add_gewerk_jump_menus
        project, wohnen, _k = _project(gewerk_catalog)
        menu = QMenu()
        add_gewerk_jump_menus(menu, _jumps(project), wohnen, wohnen.gewerk_assignments[0])
        assert [a.text() for a in menu.actions()] == [
            "Geräte in der Topologie zeigen", "GAs des Gewerks zeigen"]
        empty = QMenu()
        add_gewerk_jump_menus(empty, None, wohnen, wohnen.gewerk_assignments[0])
        assert empty.isEmpty()

    def test_building_view_gewerk_row_only_for_jumps(self, gewerk_catalog):
        from PySide6.QtCore import Qt
        from knix_arranger.ui.views.building_view import _GEWERK_ROLE, BuildingView
        from PySide6.QtWidgets import QTreeWidgetItem
        _p, wohnen, _k = _project(gewerk_catalog)
        room_item = QTreeWidgetItem(["Wohnen"])
        BuildingView()._add_gewerk_items(room_item, wohnen)
        row = room_item.child(0).child(0)
        assert row.data(0, _GEWERK_ROLE) == (wohnen, wohnen.gewerk_assignments[0])
        assert row.data(0, Qt.UserRole) is None


class TestMoreJumps:
    """FA-1011k bis p: GA zum Gewerk, Arbeitsliste, gleiches Produkt,
    Steigschema, Taster an der Szenen-GA, Secure-Archiv und DALI."""

    def test_gewerke_of_ga(self, gewerk_catalog):
        project, wohnen, kueche = _project(gewerk_catalog)
        found = _jumps(project).gewerke_of(_ga(project, wohnen).address)
        assert [t for t, _l in found] == [(wohnen, wohnen.gewerk_assignments[0])]
        assert found[0][1].startswith("L ") and found[0][1].endswith("Raum 01 Wohnen")
        assert _jumps(project).gewerke_of("31/7/255") == []

    def test_gewerke_of_ga_names_element(self, gewerk_catalog):
        project, wohnen, _k, assignment = TestGewerk()._two_elements(gewerk_catalog)
        ga = next(g for g in project.group_addresses.all_addresses()
                  if g.room_id == wohnen.id and g.element_number == 2)
        [(_t, label)] = _jumps(project).gewerke_of(ga.address)
        assert "Element 2 Wand" in label

    def test_gewerk_view_selects_assignment_through_filter(self, gewerk_catalog):
        from knix_arranger.ui.views.gewerk_view import GewerkView, _COL_LABEL
        project, _w, kueche = _project(gewerk_catalog)
        view = GewerkView()
        view.set_project(project)
        view._zone_combo.addItem("Andere", "Andere")
        view._zone_combo.setCurrentIndex(view._zone_combo.count() - 1)
        assert view._table.rowCount() == 0
        assert view.select_assignment(kueche.gewerk_assignments[0])
        row = view._table.currentRow()
        assert view._table.item(row, _COL_LABEL).data(256)[0] is kueche

    def test_worklist_targets_from_where_and_task(self, gewerk_catalog):
        from knix_arranger.services.ets_worklist import WorkItem
        from knix_arranger.services.validation_targets import DEVICE, GA, worklist_targets
        project, wohnen, _k = _project(gewerk_catalog)
        device = Device(physical_address="1.1.40")
        project.topology.areas[0].lines[0].devices.append(device)
        address = _ga(project, wohnen).address
        item = WorkItem("k", 1, "FA-614", f"{device.physical_address} KO 6 «Taste»",
                        f"{address} trennen (zweite sendende GA).")
        targets = worklist_targets(item, project)
        assert [(t.kind, t.key) for t in targets] == [(DEVICE, device.physical_address),
                                                     (GA, address)]
        assert worklist_targets(WorkItem("k", 1, "X", "9.9.9", "31/7/255"), project) == []

    def test_worklist_dialog_lists_items(self, gewerk_catalog, monkeypatch):
        from knix_arranger.services import ets_worklist
        from knix_arranger.services.ets_worklist import WorkItem
        from knix_arranger.ui.dialogs.ets_worklist_dialog import EtsWorklistDialog
        project, wohnen, _k = _project(gewerk_catalog)
        address = _ga(project, wohnen).address
        item = WorkItem("k", ets_worklist.PRIO_CHECK, "FA-604", f"GA {address}", "DPT setzen.")
        monkeypatch.setattr(ets_worklist, "current_items", lambda p: [item])
        jumped = []
        dialog = EtsWorklistDialog(project, jumped.append, lambda: None)
        group = dialog._tree.topLevelItem(0)
        assert group.text(0) == "Prüfen (1)"
        dialog._jump(group.child(0))
        assert [t.key for t in jumped] == [address]

    def test_devices_with_product(self, gewerk_catalog):
        project, _w, _k = _project(gewerk_catalog)
        line = project.topology.areas[0].lines[0]
        a = Device(physical_address="1.1.70", order_number="SA-8", product="Schaltaktor")
        b = Device(physical_address="1.1.71", order_number="SA-8", product="Schaltaktor")
        c = Device(physical_address="1.1.72", order_number="SA-4", product="Schaltaktor")
        line.devices += [a, b, c]
        jumps = _jumps(project)
        assert [d for d, _l in jumps.devices_with_product("SA-8", "", exclude=a)] == [b]
        named = [d for d, _l in jumps.devices_with_product("", "Schaltaktor")]
        assert {id(a), id(b), id(c)} <= {id(d) for d in named}
        assert jumps.devices_with_product("", "") == []

    def test_keys_at_scene_address(self, gewerk_catalog):
        project, wohnen, _k = _project(gewerk_catalog)
        taster = Device(physical_address="1.1.40", device_type="sensor", room_id=wohnen.id)
        wohnen.bedienelemente.append(Bedienelement(participant_number="1.1.40"))
        project.topology.areas[0].lines[0].devices.append(taster)
        view = SimpleNamespace(linked_devices=lambda a: [((taster, "Taste 1"), "1.1.40 Taster")])
        jumps = ViewJumps(SimpleNamespace(_project=project, _topology_view=view,
                                          _refresh_view=lambda key: None))
        [(be_id, label)] = jumps.keys_at("0/1/0")
        assert be_id == wohnen.bedienelemente[0].id
        assert label.startswith("1.1.40") and "Wohnen" in label

    def test_riser_selects_line(self, gewerk_catalog):
        from knix_arranger.models.topology import Line
        from knix_arranger.ui.views.riser_diagram_view import RiserDiagramView
        project, _w, _k = _project(gewerk_catalog)
        view = RiserDiagramView()
        view.set_project(project)
        line = project.topology.areas[0].lines[0]
        assert view.select_line(line)
        assert view._highlight == f"line:{line.id}"
        assert not view.select_line(Line(line_number=9))
        assert view._highlight == ""

    def test_secure_view_selects_device(self, gewerk_catalog):
        from knix_arranger.models.knx_secure import DeviceSecureInfo
        from knix_arranger.ui.views.knx_secure_view import KnxSecureView
        project, _w, _k = _project(gewerk_catalog)
        device = Device(physical_address="1.1.80", product="Schaltaktor")
        project.topology.areas[0].lines[0].devices.append(device)
        project.knx_secure.enabled = True
        project.knx_secure.device_infos[device.id] = DeviceSecureInfo(
            device_id=device.id, device_name="Schaltaktor", physical_address="1.1.80")
        view = KnxSecureView(project)
        view.set_project(project)
        assert view.select_device(device)
        assert view._tabs.currentIndex() == 2
        assert not view.select_device(Device(physical_address="1.1.81"))

    def test_dali_view_selects_gateway(self, gewerk_catalog):
        from knix_arranger.ui.views.dali_config_view import DaliConfigView
        project, _w, _k = _project(gewerk_catalog)
        gateway = Device(physical_address="1.1.90", device_type="gateway",
                         product="DALI-Gateway 2-fach")
        project.topology.areas[0].lines[0].devices.append(gateway)
        view = DaliConfigView(project)
        view.set_project(project)
        assert view.select_gateway(gateway)
        assert not view.select_gateway(Device(physical_address="1.1.91"))


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


class TestFunctionsMatrixKeys:
    """FA-1011g bis i: ETS-Funktion, Verknüpfungsmatrix, Tastenbelegung."""

    def _group(self):
        from tests.test_group_functions import _project as group_project
        from knix_arranger.services.group_function_detection import (
            adopt, suggest_group_functions,
        )
        project, _room, _lights = group_project()
        function = adopt(project, suggest_group_functions(project)[0], "Licht Küche")
        return project, function

    def test_functions_with_function_ga_and_member(self):
        project, function = self._group()
        jumps = _jumps(project)
        by = {g.address: g for g in project.group_addresses.all_addresses()}
        assert jumps.functions_with(by["3/4/89"]) == [
            ((function.id, "3/4/89"), "Licht Küche – Funktions-GA")]
        assert jumps.functions_with(by["3/0/70"]) == [
            ((function.id, ""), "Licht Küche – bedient dieses Element")]
        assert jumps.functions_with(by["3/7/70"]) == []

    def test_ets_functions_view_selects_function_ga(self):
        from knix_arranger.ui.views.ets_functions_view import EtsFunctionsView
        project, function = self._group()
        view = EtsFunctionsView()
        view.set_project(project)
        assert view.select_function(function.id, "3/4/89")
        current = view._plan_tree.currentItem()
        assert current.text(3) == "3/4/89"
        assert view._tabs.currentIndex() == 1
        assert view.select_function(function.id)
        assert view._plan_tree.currentItem().data(0, 256) == function.id

    def test_device_at(self, gewerk_catalog):
        project, _w, _k = _project(gewerk_catalog)
        device = Device(physical_address="1.1.77")
        project.topology.areas[0].lines[0].devices.append(device)
        assert _jumps(project).device_at("1.1.77") is device
        assert _jumps(project).device_at("") is None

    def test_matrix_menu_entries(self):
        from knix_arranger.ui.views.linking_matrix_view import LinkingMatrixView
        project, _function = self._group()
        view = LinkingMatrixView()
        view.jumps = _jumps(project)
        texts = [t for t, _run in view._jump_actions("1.1.1", ["3/0/70", "3/0/70"], "be-1")]
        assert texts == ["Zur Gruppenadresse 3/0/70 springen",
                         "Gerät 1.1.1 in der Topologie zeigen", "",
                         "Tastenbelegung bearbeiten…"]
        assert [t for t, _r in view._jump_actions("9.9.9", [])] == []
        view.jumps = None
        assert view._jump_actions("1.1.1", ["3/0/70"]) == []
