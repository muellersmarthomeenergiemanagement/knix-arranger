"""
Tests fuer GewerkService: Ableitung von Gewerk-Zuweisungen aus GA-Bezeichnungen
und nachtraegliche assignment_id-Verknuepfung nach einem Reimport (FA-519b/FA-521e).
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.services.gewerk_service import GewerkService
from knix_arranger.services.naming_engine import NamingEngine


def _dot_convention_areal():
    """Areal mit einem Raum, dessen Nummer der externen ETS-Punkt-Konvention
    entspricht (reine 2-stellige Ziffer, siehe derive_gewerk_assignments)."""
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")
    og = Floor(name="Obergeschoss", short_code="OG")
    apt = Apartment(name="OG")
    room = Room(number="00", name="Technikraum")
    apt.rooms.append(room)
    og.apartments.append(apt)
    wing.floors.append(og)
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal, room


def _structure_with_designation(designation: str, main_group: int = 1,
                                 assignment_id: str = "") -> tuple[GroupAddressStructure, GroupAddress]:
    structure = GroupAddressStructure()
    hg = MainGroup(number=main_group, name="Test")
    mg = MiddleGroup(number=0, name="Test")
    ga = GroupAddress(
        main_group=main_group, middle_group=0, sub_group=0,
        designation=designation, assignment_id=assignment_id,
    )
    mg.group_addresses.append(ga)
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)
    return structure, ga


class TestDeriveGewerkAssignments:
    """Regressionsschutz fuer das _build_room_index/_match_ga_designation-
    Refactoring -- bestehendes Verhalten muss unveraendert bleiben."""

    def test_creates_assignment_from_dot_convention_designation(self, gewerk_catalog):
        areal, room = _dot_convention_areal()
        structure, _ga = _structure_with_designation("LDA.OG.00.01_ea", main_group=1)

        svc = GewerkService(gewerk_catalog)
        created = svc.derive_gewerk_assignments(structure, areal)

        assert created == 1
        assert len(room.gewerk_assignments) == 1
        assert room.gewerk_assignments[0].gewerk_code == "LDA"
        assert room.gewerk_assignments[0].count == 1

    def test_central_address_not_counted(self, gewerk_catalog):
        areal, room = _dot_convention_areal()
        structure, _ga = _structure_with_designation("LDA.OG.00.01_ea", main_group=0)

        svc = GewerkService(gewerk_catalog)
        created = svc.derive_gewerk_assignments(structure, areal)

        assert created == 0
        assert room.gewerk_assignments == []
        assert len(svc.last_central_addresses) == 1

    def test_combined_addressing_not_counted(self, gewerk_catalog):
        areal, room = _dot_convention_areal()
        structure, _ga = _structure_with_designation("LDA.OG.00.01+02_ea", main_group=1)

        svc = GewerkService(gewerk_catalog)
        created = svc.derive_gewerk_assignments(structure, areal)

        assert created == 0
        assert room.gewerk_assignments == []
        assert len(svc.last_ambiguous_designations) == 1


class TestRelinkAssignmentIds:
    """FA-521e: importierte GAs ohne assignment_id nachtraeglich mit einer
    bestehenden GewerkAssignment verknuepfen (verhindert Duplikat-Bloecke bei
    der naechsten Neugenerierung)."""

    def test_relinks_native_naming_engine_format(self, simple_efh, gewerk_catalog):
        room = next(r for r in simple_efh.all_rooms if r.number == "E01")
        assignment = GewerkAssignment(gewerk_code="L", count=1)
        room.gewerk_assignments = [assignment]

        designation = NamingEngine.create_designation("L", "E01", 1, "E/A", "Schlafzimmer")
        structure, ga = _structure_with_designation(designation, main_group=2)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, simple_efh)

        assert relinked == 1
        assert ga.assignment_id == assignment.id

    def test_relinks_dot_convention_fallback(self, gewerk_catalog):
        areal, room = _dot_convention_areal()
        assignment = GewerkAssignment(gewerk_code="LDA", count=1)
        room.gewerk_assignments = [assignment]
        structure, ga = _structure_with_designation("LDA.OG.00.01_ea", main_group=1)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, areal)

        assert relinked == 1
        assert ga.assignment_id == assignment.id

    def test_does_not_overwrite_existing_assignment_id(self, simple_efh, gewerk_catalog):
        room = next(r for r in simple_efh.all_rooms if r.number == "E01")
        assignment = GewerkAssignment(gewerk_code="L", count=1)
        room.gewerk_assignments = [assignment]

        designation = NamingEngine.create_designation("L", "E01", 1, "E/A")
        structure, ga = _structure_with_designation(
            designation, main_group=2, assignment_id="already-set",
        )

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, simple_efh)

        assert relinked == 0
        assert ga.assignment_id == "already-set"

    def test_skips_central_address(self, simple_efh, gewerk_catalog):
        room = next(r for r in simple_efh.all_rooms if r.number == "E01")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]

        designation = NamingEngine.create_designation("L", "E01", 1, "E/A")
        structure, ga = _structure_with_designation(designation, main_group=0)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, simple_efh)

        assert relinked == 0
        assert ga.assignment_id == ""

    def test_skips_unknown_gewerk_code(self, simple_efh, gewerk_catalog):
        room = next(r for r in simple_efh.all_rooms if r.number == "E01")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="ZZZ", count=1)]

        designation = NamingEngine.create_designation("ZZZ", "E01", 1, "E/A")
        structure, ga = _structure_with_designation(designation, main_group=2)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, simple_efh)

        assert relinked == 0
        assert ga.assignment_id == ""

    def test_skips_when_no_matching_room(self, simple_efh, gewerk_catalog):
        designation = NamingEngine.create_designation("L", "X99", 1, "E/A")
        structure, ga = _structure_with_designation(designation, main_group=2)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, simple_efh)

        assert relinked == 0
        assert ga.assignment_id == ""

    def test_skips_when_room_has_no_matching_assignment(self, simple_efh, gewerk_catalog):
        room = next(r for r in simple_efh.all_rooms if r.number == "E01")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="J", count=1)]

        designation = NamingEngine.create_designation("L", "E01", 1, "E/A")
        structure, ga = _structure_with_designation(designation, main_group=2)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, simple_efh)

        assert relinked == 0
        assert ga.assignment_id == ""

    def test_skips_combined_addressing_dot_convention(self, gewerk_catalog):
        areal, room = _dot_convention_areal()
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=2)]
        structure, ga = _structure_with_designation("L.OG.00.01+02_ea", main_group=1)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, areal)

        assert relinked == 0
        assert ga.assignment_id == ""

    def test_reserve_placeholder_sandwiched_between_matches_gets_relinked(
        self, simple_efh, gewerk_catalog,
    ):
        """Reserve-Eintraege ("--") tragen keinen auswertbaren Inhalt, gehoeren
        aber zum selben Block wie ihre Nachbarn -- Position statt Inhalt."""
        room = next(r for r in simple_efh.all_rooms if r.number == "E01")
        assignment = GewerkAssignment(gewerk_code="H", count=1)
        room.gewerk_assignments = [assignment]

        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="Test")
        mg = MiddleGroup(number=2, name="Heizung")
        d1 = NamingEngine.create_designation("H", "E01", 1, "STELLGROESSE")
        d2 = NamingEngine.create_designation("H", "E01", 1, "IST")
        ga_before = GroupAddress(main_group=2, middle_group=2, sub_group=0, designation=d1)
        ga_gap = GroupAddress(main_group=2, middle_group=2, sub_group=1, designation="--")
        ga_after = GroupAddress(main_group=2, middle_group=2, sub_group=2, designation=d2)
        mg.group_addresses = [ga_before, ga_gap, ga_after]
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        svc = GewerkService(gewerk_catalog)
        relinked = svc.relink_assignment_ids(structure, simple_efh)

        assert relinked == 3
        assert ga_gap.assignment_id == assignment.id

    def test_edge_gap_without_both_side_neighbor_not_relinked(
        self, simple_efh, gewerk_catalog,
    ):
        """Eine Luecke am Rand einer Mittelgruppe (kein Nachbar auf einer
        Seite) bleibt bewusst unverknuepft -- keine eindeutige Zuordnung."""
        room = next(r for r in simple_efh.all_rooms if r.number == "E01")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="H", count=1)]

        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="Test")
        mg = MiddleGroup(number=2, name="Heizung")
        d1 = NamingEngine.create_designation("H", "E01", 1, "STELLGROESSE")
        ga_gap = GroupAddress(main_group=2, middle_group=2, sub_group=0, designation="--")
        ga_after = GroupAddress(main_group=2, middle_group=2, sub_group=1, designation=d1)
        mg.group_addresses = [ga_gap, ga_after]
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        svc = GewerkService(gewerk_catalog)
        svc.relink_assignment_ids(structure, simple_efh)

        assert ga_gap.assignment_id == ""
