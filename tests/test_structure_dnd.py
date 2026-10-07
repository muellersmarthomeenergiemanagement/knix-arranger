"""
Tests fuer Ziehen und Ablegen (FA-1015 a-d): Raeume in Zonen/Stockwerke,
Geraete auf Linien, Gewerke auf Raeume, Gruppenadressen tauschen/verschieben.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Apartment, Bedienelement, Floor, GewerkAssignment, Room, SensorFunktion,
)
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.ga_move import (
    can_move_to_middle_group, can_reorder, can_swap, is_draggable,
    move_to_middle_group, swap_addresses,
)
from knix_arranger.services.structure_move import (
    add_gewerk, can_move_device, can_move_gewerk, can_move_room, move_device,
    move_gewerk, move_kind, move_room, move_room_to_line, room_target_on_floor,
)

from tests.test_renumber_service import _project, _by_designation


def _ga(project, designation):
    return _by_designation(project, designation)


# ── a) Räume ───────────────────────────────────────────────────────────────

class TestRoomMove:
    def _two_floors(self):
        project = _project()
        wing = project.areal.buildings[0].wings[0]
        og = Floor(name="Obergeschoss", short_code="OG", main_group_number=3)
        og.apartments = [Apartment(name="OG")]
        wing.floors.append(og)
        return project, og

    def test_room_moves_to_other_floor_and_addresses_follow(self):
        project, og = self._two_floors()
        kueche = project.all_rooms[1]
        assert can_move_room(project.areal, kueche, og.apartments[0])
        assert move_room(project.areal, kueche, og.apartments[0])
        assert kueche in og.apartments[0].rooms
        assert kueche.floor_id == og.id
        regenerate_addresses(project)
        assert _ga(project, "LD_E02_01 E/A (OG / Kueche)").main_group == 3

    def test_same_apartment_is_no_target(self):
        project, _og = self._two_floors()
        kueche = project.all_rooms[1]
        eg_apt = project.areal.all_floors[0].apartments[0]
        assert not can_move_room(project.areal, kueche, eg_apt)

    def test_floor_drop_prefers_same_zone(self):
        project, og = self._two_floors()
        og.apartments.insert(0, Apartment(name="Andere"))
        og.apartments.append(Apartment(name="EG"))   # Maisonette-Zone
        kueche = project.all_rooms[1]
        assert room_target_on_floor(project.areal, kueche, og).name == "EG"


# ── b) Geräte und Linien ───────────────────────────────────────────────────

def _topology(imported: bool) -> tuple[Topology, Line, Line, Device]:
    topo = Topology(is_imported=imported)
    l1 = Line(line_number=1, name="EG", coupler_address="1.1.0", assigned_room_ids=["r1"])
    l2 = Line(line_number=2, name="OG", coupler_address="1.2.0")
    sensor = Device(device_type="sensor", product="Taster", physical_address="1.1.101",
                    room_id="r1")
    l1.devices = [sensor]
    l2.devices = [Device(device_type="sensor", product="Taster", physical_address="1.2.101")]
    topo.areas = [Area(area_number=1, lines=[l1, l2])]
    return topo, l1, l2, sensor


class TestDeviceMove:
    def test_imported_device_moves_with_free_address(self):
        topo, l1, l2, sensor = _topology(imported=True)
        assert move_kind(topo, sensor) == "device"
        assert move_device(topo, sensor, l2) == "1.2.1"   # 101 belegt
        assert sensor in l2.devices and sensor not in l1.devices

    def test_imported_device_keeps_free_number(self):
        topo, _l1, l2, sensor = _topology(imported=True)
        l2.devices.clear()
        assert move_device(topo, sensor, l2) == "1.2.101"

    def test_planned_device_moves_its_room(self):
        topo, l1, l2, sensor = _topology(imported=False)
        assert move_kind(topo, sensor) == "room"
        assert can_move_device(topo, sensor, l2)
        assert move_room_to_line(topo, "r1", l2)
        assert l2.assigned_room_ids == ["r1"] and not l1.assigned_room_ids
        assert not can_move_device(topo, sensor, l2)

    def test_programmed_and_planned_actor_not_movable(self):
        topo, _l1, l2, sensor = _topology(imported=False)
        sensor.is_programmed = True
        assert not can_move_device(topo, sensor, l2)
        actor = Device(device_type="actor", product="Schaltaktor")
        assert move_kind(topo, actor) == ""


# ── c) Gewerke ─────────────────────────────────────────────────────────────

class TestGewerkMove:
    def test_catalog_drop_adds_or_increments(self):
        room = Room(number="E01", name="Wohnen")
        add_gewerk(room, "LD")
        add_gewerk(room, "LD")
        assert [(g.gewerk_code, g.count) for g in room.gewerk_assignments] == [("LD", 2)]

    def test_move_keeps_button_reference(self):
        project = _project()
        wohnen, kueche = project.all_rooms
        jal = wohnen.gewerk_assignments[1]
        be = Bedienelement(element_type="Tastereinheit")
        be.funktionen = [SensorFunktion(gewerk_code="J", element_number=1)]
        wohnen.bedienelemente = [be]
        assert can_move_gewerk(wohnen, jal, kueche)
        assert move_gewerk(project.areal, wohnen, jal, kueche)
        assert jal in kueche.gewerk_assignments and jal not in wohnen.gewerk_assignments
        assert be.funktionen[0].source_room_id == kueche.id

    def test_move_refused_when_code_exists(self):
        project = _project()
        wohnen, kueche = project.all_rooms
        assert not can_move_gewerk(wohnen, wohnen.gewerk_assignments[0], kueche)


# ── d) Gruppenadressen ─────────────────────────────────────────────────────

class TestGaMove:
    def test_swap_survives_regeneration_and_remaps_references(self):
        project = _project()
        ea = _ga(project, "LD_E01_01 E/A (Wohnen)")
        wert = _ga(project, "LD_E01_01 WERT (Wohnen)")
        project.scenes = [Scene(name="Abend", actions=[SceneAction(ga_address="2/0/0")])]
        assert can_swap(ea, wert)
        swap_addresses(project, ea, wert)
        assert (ea.address, wert.address) == ("2/0/2", "2/0/0")
        assert project.scenes[0].actions[0].ga_address == "2/0/2"
        regenerate_addresses(project)
        assert _ga(project, "LD_E01_01 E/A (Wohnen)").address == "2/0/2"
        assert _ga(project, "LD_E01_01 WERT (Wohnen)").address == "2/0/0"

    def test_move_to_middle_group_survives_regeneration(self):
        project = _project()
        ea = _ga(project, "LD_E02_01 E/A (Kueche)")
        assert can_move_to_middle_group([ea], 2, 1)
        move_to_middle_group(project, [ea], 2, 1)
        assert ea.address == "2/1/10"
        regenerate_addresses(project)
        assert _ga(project, "LD_E02_01 E/A (Kueche)").address == "2/1/10"
        assert len(project.group_addresses.all_addresses()) == len(
            {ga.address for ga in project.group_addresses.all_addresses()})

    def test_variant_b_feedback_follows_command(self):
        project = _project("B")
        ea = _ga(project, "LD_E01_01 E/A (Wohnen)")
        wert = _ga(project, "LD_E01_01 WERT (Wohnen)")
        rm = _ga(project, "LD_E01_01 RM (Wohnen)")
        assert not is_draggable(rm)
        swap_addresses(project, ea, wert)
        assert rm.address == "2/6/2"
        regenerate_addresses(project)
        assert _ga(project, "LD_E01_01 E/A (Wohnen)").address == "2/0/2"
        assert _ga(project, "LD_E01_01 RM (Wohnen)").address == "2/6/2"
        assert _ga(project, "LD_E01_01 RM WERT (Wohnen)").address == "2/6/0"

    def test_central_and_other_floor_not_allowed(self):
        project = _project()
        central = next(ga for ga in project.group_addresses.all_addresses()
                       if ga.main_group == 0)
        ea = _ga(project, "LD_E01_01 E/A (Wohnen)")
        assert not is_draggable(central)
        assert not can_swap(ea, central)
        assert not can_move_to_middle_group([ea], 3, 0)

    def test_only_planned_projects(self):
        project = _project()
        assert can_reorder(project)
        project.ets_transferred = "2026-10-07"
        assert not can_reorder(project)
