"""
Tests fuer "Adressen neu ordnen" (FA-701 bis FA-706): geplante Projekte
werden lueckenlos neu aufgebaut, ids und Felder bleiben, Verweise wandern mit.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
    Bedienelement, SensorFunktion,
)
from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.address_generator import regenerate_addresses, insert_ga
from knix_arranger.services.renumber_service import (
    can_renumber, plan_renumbering, apply_renumbering,
)


def _project(variant: str = "A") -> KnxProject:
    project = KnxProject(name="Test")
    project.config.mg_variant = variant
    areal = Areal(name="A")
    building = Building(name="B")
    wing = Wing(name="W")
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    apt = Apartment(name="EG")
    wohnen = Room(number="E01", name="Wohnen")
    wohnen.gewerk_assignments = [GewerkAssignment(gewerk_code="LD", count=1),
                                 GewerkAssignment(gewerk_code="J", count=1)]
    kueche = Room(number="E02", name="Kueche")
    kueche.gewerk_assignments = [GewerkAssignment(gewerk_code="LD", count=1)]
    apt.rooms = [wohnen, kueche]
    floor.apartments = [apt]
    wing.floors = [floor]
    building.wings = [wing]
    areal.buildings = [building]
    project.areal = areal
    regenerate_addresses(project)
    return project


def _wohnen(project) -> Room:
    return project.all_rooms[0]


def _by_designation(project, designation: str) -> GroupAddress:
    return next(ga for ga in project.group_addresses.all_addresses()
                if ga.designation == designation)


def _grow_wohnen(project) -> None:
    """Zweites Licht in E01: der Block wird bei der normalen Neuberechnung
    ans Ende angehängt, E01 steht dann hinter E02."""
    _wohnen(project).gewerk_assignments[0].count = 2
    regenerate_addresses(project)


class TestPlan:
    def test_no_changes_when_fresh(self):
        project = _project()
        plan = plan_renumbering(project)
        assert not plan.has_changes
        assert plan.gaps_after == 0

    def test_restores_room_order_and_closes_gap(self):
        project = _project()
        _grow_wohnen(project)
        assert _by_designation(project, "LD_E01_01 E/A (Wohnen)").address == "2/0/10"

        plan = plan_renumbering(project)
        assert plan.gaps_before == 5
        assert plan.gaps_after == 0
        assert plan.address_map["2/0/10"] == "2/0/0"
        assert plan.address_map["2/0/5"] == "2/0/10"
        assert not plan.added and not plan.removed
        # Projekt bleibt bis zum Übernehmen unverändert
        assert _by_designation(project, "LD_E01_01 E/A (Wohnen)").address == "2/0/10"

    def test_central_group_untouched(self):
        project = _project()
        _grow_wohnen(project)
        before = {ga.id: ga.address for hg in project.group_addresses.main_groups
                  if hg.number == 0 for mg in hg.middle_groups for ga in mg.group_addresses}
        plan = plan_renumbering(project)
        after = {ga.id: ga.address for hg in plan.structure.main_groups
                 if hg.number == 0 for mg in hg.middle_groups for ga in mg.group_addresses}
        assert after == before
        assert "0/0/0" not in after.values()

    @pytest.mark.parametrize("variant", ["A", "B"])
    def test_ids_and_fields_kept(self, variant):
        project = _project(variant)
        _grow_wohnen(project)
        ga = _by_designation(project, "LD_E01_01 E/A (Wohnen)")
        ga.central = "true"
        ga.security = "Ein"
        ga.description = "Notiz"
        old_id = ga.id

        plan = plan_renumbering(project)
        apply_renumbering(project, plan)

        moved = _by_designation(project, "LD_E01_01 E/A (Wohnen)")
        assert moved.id == old_id
        assert (moved.central, moved.security, moved.description) == ("true", "Ein", "Notiz")

    def test_variant_b_feedback_aligned(self):
        project = _project("B")
        _grow_wohnen(project)
        apply_renumbering(project, plan_renumbering(project))
        cmd = _by_designation(project, "LD_E01_02 E/A (Wohnen)")
        rm = _by_designation(project, "LD_E01_02 RM (Wohnen)")
        assert rm.middle_group == 6
        assert rm.sub_group == cmd.sub_group

    def test_manual_ga_stays(self):
        project = _project()
        manual = GroupAddress(main_group=2, middle_group=3, sub_group=200,
                              designation="Spezial", is_manual=True)
        insert_ga(project.group_addresses, manual)
        _grow_wohnen(project)
        apply_renumbering(project, plan_renumbering(project))
        kept = _by_designation(project, "Spezial")
        assert kept.id == manual.id and kept.address == "2/3/200"


class TestReferences:
    def test_references_follow(self):
        project = _project()
        _grow_wohnen(project)
        be = Bedienelement(element_type="Tastereinheit")
        be.funktionen.append(SensorFunktion(ga_designation="2/0/10  LD_E01_01 E/A (Wohnen)"))
        _wohnen(project).bedienelemente.append(be)
        project.scenes.append(Scene(
            name="Kino", source_ga_addresses=["2/0/5"],
            actions=[SceneAction(ga_address="2/0/10")]))
        device = Device(communication_objects=[
            CommunicationObject(connected_gas=["2/0/10", "2/0/5", "9/9/9"])])
        project.topology.areas.append(Area(lines=[Line(devices=[device])]))

        plan = plan_renumbering(project)
        count = apply_renumbering(project, plan)

        assert be.funktionen[0].ga_designation == "2/0/0  LD_E01_01 E/A (Wohnen)"
        assert project.scenes[0].source_ga_addresses == ["2/0/10"]
        assert project.scenes[0].actions[0].ga_address == "2/0/0"
        # Gleichzeitige Zuordnung, kein Verketten; Fremde Adressen bleiben
        assert device.communication_objects[0].connected_gas == ["2/0/0", "2/0/10", "9/9/9"]
        assert count == 5


class TestGuard:
    def test_imported_project_not_renumbered(self):
        project = _project()
        assert can_renumber(project)
        project.topology.is_imported = True
        assert not can_renumber(project)
