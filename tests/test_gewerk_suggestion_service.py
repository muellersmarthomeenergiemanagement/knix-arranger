"""
Tests fuer GewerkSuggestionService: schlaegt aus einer importierten
Topologie Raum+Gewerk-Kombinationen fuer unverknuepfte Aktor-Kanaele vor.
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.topology import Device, CommunicationObject, Line, Area
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.services.gewerk_suggestion_service import (
    suggest_gewerk_assignments, find_reusable_assignment, assignment_for_suggestion,
)


def _project_with_room():
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")
    floor = Floor(name="EG", short_code="EG")
    apt = Apartment(name="EG")
    room = Room(number="01", name="Energiekeller")
    apt.rooms.append(room)
    floor.apartments.append(apt)
    wing.floors.append(floor)
    building.wings.append(wing)
    areal.buildings.append(building)

    project = KnxProject(name="Test")
    project.areal = areal
    project.topology.is_imported = True
    return project, room


def _add_ga(project, address_str: str, designation: str = "") -> GroupAddress:
    hg_num, mg_num, sub_num = (int(x) for x in address_str.split("/"))
    structure = project.group_addresses
    hg = next((h for h in structure.main_groups if h.number == hg_num), None)
    if hg is None:
        hg = MainGroup(number=hg_num, name=f"HG{hg_num}")
        structure.main_groups.append(hg)
    mg = next((m for m in hg.middle_groups if m.number == mg_num), None)
    if mg is None:
        mg = MiddleGroup(number=mg_num, name=f"MG{mg_num}")
        hg.middle_groups.append(mg)
    ga = GroupAddress(
        main_group=hg_num, middle_group=mg_num, sub_group=sub_num,
        designation=designation,
    )
    mg.group_addresses.append(ga)
    return ga


def _switch_actuator_device(room_id: str) -> Device:
    """ABB-artiger Schaltaktor-Kanal 'Ausgang A' (Chalet-Projekt 1.1.10)."""
    device = Device(
        physical_address="1.1.10", manufacturer="ABB",
        product="SA/S8.16.1", room_id=room_id,
    )
    device.communication_objects = [
        CommunicationObject(
            name="Ausgang A", object_function="Schalten",
            data_type="1 bit", connected_gas=["0/2/50"],
        ),
        CommunicationObject(
            name="Ausgang A", object_function="Telegr. Status Schalten",
            data_type="1 bit", connected_gas=["0/2/51"],
        ),
    ]
    return device


def _heating_actuator_device(room_id: str) -> Device:
    """Heizungsaktor -- kein Code in _MATCHABLE_CODES, darf keinen
    Vorschlag erzeugen (nur STOERUNG/SPERREN waeren ueberhaupt erkennbar,
    das reicht laut _PRIMARY_FUNCTIONS nicht aus)."""
    device = Device(
        physical_address="1.1.30", manufacturer="Test",
        product="Heizaktor", room_id=room_id,
    )
    device.communication_objects = [
        CommunicationObject(
            name="Kanal 1", object_function="Stellgroesse",
            data_type="1 byte", connected_gas=["0/5/1"],
        ),
        CommunicationObject(
            name="Kanal 1", object_function="Sperren",
            data_type="1 bit", connected_gas=["0/5/2"],
        ),
    ]
    return device


def _leak_sensor_device(room_id: str) -> Device:
    """Realdaten-Fall (Elsner Leak KNX 2.0, Chalet-Projekt 1.1.24): ein
    reines 1-Bit-Alarmobjekt matcht das generische 'schalten'-Stichwort
    von E/A, ist aber kein Lichtaktor -- darf ohne zweite Funktion
    (z.B. RM) nicht vorgeschlagen werden."""
    device = Device(
        physical_address="1.1.24", manufacturer="Elsner Elektronik GmbH",
        product="Leak KNX 2.0", room_id=room_id,
    )
    device.communication_objects = [
        CommunicationObject(
            name="Leckage Sensorfehler (1 = An | 0 = Aus)",
            object_function="Ein / Aus", data_type="1 bit",
            connected_gas=["0/5/50"],
        ),
    ]
    return device


def _wire_device_into_project(project, device):
    area = Area(area_number=1)
    line = Line(line_number=1)
    line.devices.append(device)
    area.lines.append(line)
    project.topology.areas.append(area)


class TestSuggestGewerkAssignments:
    def test_switch_channel_suggests_light_gewerk(self):
        project, room = _project_with_room()
        device = _switch_actuator_device(room.id)
        _wire_device_into_project(project, device)
        _add_ga(project, "0/2/50", "HS.OG.05.03_ea   ( Grill )")
        _add_ga(project, "0/2/51", "HS.OG.05.03_status   ( Grill )")

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert warnings == []
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s.gewerk_code == "L"
        assert s.room.id == room.id
        assert s.channel_name == "Ausgang A"
        assert set(s.matched.keys()) == {"E/A", "RM"}
        assert s.matched["E/A"].address == "0/2/50"

    def test_fully_linked_channel_is_not_suggested_again(self):
        project, room = _project_with_room()
        device = _switch_actuator_device(room.id)
        _wire_device_into_project(project, device)
        ga_ea = _add_ga(project, "0/2/50")
        ga_rm = _add_ga(project, "0/2/51")

        room.gewerk_assignments.append(GewerkAssignment(
            gewerk_code="L", count=1,
            linked_ga_ids={"E/A": ga_ea.id, "RM": ga_rm.id},
        ))

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert suggestions == []

    def test_partially_linked_channel_is_suggested_for_remaining_functions(self):
        """Nur E/A wurde bisher manuell verknuepft -- der Kanal gilt nicht
        als vollstaendig erledigt und wird (mit beiden erkannten
        Funktionen) erneut vorgeschlagen, statt stillschweigend die
        offene RM-Funktion zu verlieren."""
        project, room = _project_with_room()
        device = _switch_actuator_device(room.id)
        _wire_device_into_project(project, device)
        ga_ea = _add_ga(project, "0/2/50")
        _add_ga(project, "0/2/51")

        room.gewerk_assignments.append(GewerkAssignment(
            gewerk_code="L", count=1, linked_ga_ids={"E/A": ga_ea.id},
        ))

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert len(suggestions) == 1
        assert set(suggestions[0].matched.keys()) == {"E/A", "RM"}

    def test_device_without_room_id_is_skipped_and_counted(self):
        project, room = _project_with_room()
        device = _switch_actuator_device(room_id="")
        _wire_device_into_project(project, device)
        _add_ga(project, "0/2/50")
        _add_ga(project, "0/2/51")

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert suggestions == []
        assert len(warnings) == 1
        assert "1" in warnings[0]

    def test_single_function_match_on_unrelated_device_is_rejected(self):
        project, room = _project_with_room()
        device = _leak_sensor_device(room.id)
        _wire_device_into_project(project, device)
        _add_ga(project, "0/5/50")

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert suggestions == []

    def test_non_matchable_gewerk_produces_no_suggestion(self):
        project, room = _project_with_room()
        device = _heating_actuator_device(room.id)
        _wire_device_into_project(project, device)
        _add_ga(project, "0/5/1")
        _add_ga(project, "0/5/2")

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert suggestions == []

    def test_channel_without_any_ga_is_skipped(self):
        project, room = _project_with_room()
        device = Device(physical_address="1.1.99", room_id=room.id)
        device.communication_objects = [
            CommunicationObject(name="Ausgang X", object_function="Schalten"),
        ]
        _wire_device_into_project(project, device)

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert suggestions == []

    def test_existing_unlinked_placeholder_is_offered_for_reuse(self):
        """Reproduziert einen realen Fund im Chalet-Projekt: die
        Bezeichnungs-basierte Gewerk-Ableitung beim Import (FA-519b,
        GewerkService.derive_gewerk_assignments, läuft automatisch bei
        jedem GA-Import) legt oft schon eine leere 'L'-Zuweisung im Raum
        an, bevor dieser Kanal-Scan überhaupt läuft. Ohne Wiederverwendung
        würde ein zweiter, verwirrender Eintrag für dasselbe Gewerk im
        selben Raum entstehen."""
        project, room = _project_with_room()
        device = _switch_actuator_device(room.id)
        _wire_device_into_project(project, device)
        _add_ga(project, "0/2/50")
        _add_ga(project, "0/2/51")

        placeholder = GewerkAssignment(gewerk_code="L", count=1)
        room.gewerk_assignments.append(placeholder)

        suggestions, warnings = suggest_gewerk_assignments(project)

        assert len(suggestions) == 1
        assert suggestions[0].existing_assignment is placeholder

    def test_multi_count_placeholder_is_reused_per_free_element(self):
        """Mehrfach-Zuweisungen werden je Element wiederverwendet, solange
        das Element existiert und noch unverknüpft ist."""
        project, room = _project_with_room()
        multi = GewerkAssignment(gewerk_code="L", count=3)
        room.gewerk_assignments.append(multi)

        assert find_reusable_assignment(room, "L", 2) is multi
        multi.element_links(2)["E/A"] = "x"
        assert find_reusable_assignment(room, "L", 2) is None
        assert find_reusable_assignment(room, "L", 4) is None


# ── Raum/Gewerk/Element aus der GA-Bezeichnung ───────────────────────────────

def _jalousie_channel(address, channel, gas, device_type="actor"):
    """Jalousieaktor-Kanal im Verteiler (Raum des Geraets != Raum des Storen)."""
    device = Device(physical_address=address, product="JAX-9", device_type=device_type)
    device.communication_objects = [
        CommunicationObject(name=channel, object_function="Auf/Ab", connected_gas=[gas[0]]),
        CommunicationObject(name=channel, object_function="Stopp", connected_gas=[gas[1]]),
    ]
    return device


def _project_with_two_blinds():
    """Wie Chalet Franziska OG.04: "J ×2" aus den Bezeichnungen, Storen 1 an
    1.1.5 M9, Storen 2 an 1.1.4 M7, beide Aktoren im Verteiler."""
    project, room = _project_with_room()
    verteiler = Room(number="", name="Verteiler")
    project.areal.buildings[0].wings[0].floors[0].apartments[0].rooms.append(verteiler)
    placeholder = GewerkAssignment(gewerk_code="J", count=2)
    room.gewerk_assignments.append(placeholder)
    for sub, name in ((35, "J.EG.01.01_move"), (36, "J.EG.01.01_step"),
                      (40, "J.EG.01.02_move"), (41, "J.EG.01.02_step")):
        _add_ga(project, f"3/1/{sub}", name)
    second = _jalousie_channel("1.1.4", "M7", ["3/1/40", "3/1/41"])
    first = _jalousie_channel("1.1.5", "M9", ["3/1/35", "3/1/36"])
    second.room_id = first.room_id = verteiler.id
    area = Area(area_number=1)
    area.lines.append(Line(line_number=1, devices=[second, first]))
    project.topology.areas.append(area)
    return project, room, placeholder


class TestSuggestionsFromDesignation:
    def test_room_and_element_come_from_designation(self):
        project, room, placeholder = _project_with_two_blinds()
        suggestions, _ = suggest_gewerk_assignments(project)

        by_channel = {s.channel_name: s for s in suggestions}
        assert set(by_channel) == {"M7", "M9"}
        assert by_channel["M9"].room is room and by_channel["M9"].element_nr == 1
        assert by_channel["M7"].room is room and by_channel["M7"].element_nr == 2
        assert all(s.existing_assignment is placeholder for s in suggestions)

    def test_sensors_are_not_suggested(self):
        project, room, _ = _project_with_two_blinds()
        taster = _jalousie_channel("1.1.47", "Taste 2", ["3/1/40", "3/1/41"], "sensor")
        project.topology.areas[0].lines[0].devices.append(taster)
        suggestions, _ = suggest_gewerk_assignments(project)
        assert {s.device.physical_address for s in suggestions} == {"1.1.4", "1.1.5"}

    def test_split_channel_of_one_device_is_merged(self):
        """DALI-Gateway: ein Kanal auf mehrere ComObject-Namen verteilt."""
        project, room = _project_with_room()
        _add_ga(project, "2/0/65", "L.EG.01.01_ea")
        _add_ga(project, "2/0/66", "L.EG.01.01_dim")
        gateway = Device(physical_address="1.1.8", device_type="gateway")
        gateway.communication_objects = [
            CommunicationObject(name="G7, Schalten,", object_function="Schalten",
                                connected_gas=["2/0/65"]),
            CommunicationObject(name="G7, Dimmen,", object_function="Dimmen",
                                connected_gas=["2/0/66"]),
        ]
        _wire_device_into_project(project, gateway)
        suggestions, _ = suggest_gewerk_assignments(project)
        assert len(suggestions) == 1
        assert set(suggestions[0].matched) == {"E/A", "DIM"}
        assert suggestions[0].channel_name == "G7, Schalten, / G7, Dimmen,"


class TestAssignmentForSuggestion:
    def test_reuses_free_element(self):
        project, room, placeholder = _project_with_two_blinds()
        assert assignment_for_suggestion(room, "J", 2) == (placeholder, 2)

    def test_extends_count_for_higher_element(self):
        project, room = _project_with_room()
        existing = GewerkAssignment(gewerk_code="L", count=1, linked_ga_ids={"E/A": "x"})
        room.gewerk_assignments.append(existing)
        assert assignment_for_suggestion(room, "L", 3) == (existing, 3)
        assert existing.count == 3

    def test_new_assignment_counts_up_to_element(self):
        project, room = _project_with_room()
        assignment, element = assignment_for_suggestion(room, "L", 2)
        assert (assignment.count, element) == (2, 2)
        assert room.gewerk_assignments == [assignment]
        assert assignment_for_suggestion(room, "L", 1) == (assignment, 1)
