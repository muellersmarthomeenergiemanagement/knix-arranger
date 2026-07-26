"""
Tests fuer BelegungsplanService (Sensor/Aktor-Belegungsplan).

Schwerpunkt: Kanal-Vergabe an Aktoren (channel_number).
Kernregel: Jede eindeutige (Raum, Gewerk, Element-Nr.) Kombination
erhält eine eigene fortlaufende Kanalnummer.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
    Bedienelement, FunctionAssignment,
)
from knix_arranger.models.topology import Topology, Area, Line, Device, CommunicationObject
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.services.belegungsplan_service import BelegungsplanService


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _make_project(rooms: list[Room], actor_product: str, gas: list[GroupAddress]) -> KnxProject:
    """Erstellt ein minimales Testprojekt mit einer Linie und einem Aktor."""
    project = KnxProject(name="Test")

    # Gebäude
    apt = Apartment(name="WG")
    apt.rooms = rooms
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Test")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])

    # Topologie: eine Linie mit einem Aktor
    line = Line(name="Linie 1", line_number=1)
    line.assigned_room_ids = [r.id for r in rooms]
    actor = Device(device_type="actor", product=actor_product, physical_address="1.1.1")
    line.devices = [actor]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    topology = Topology()
    topology.areas = [area]
    project.topology = topology

    # Gruppenadressen
    mg = MiddleGroup(number=0, name="Test")
    mg.group_addresses = gas
    hg = MainGroup(number=1, name="EG")
    hg.middle_groups = [mg]
    structure = GroupAddressStructure()
    structure.main_groups = [hg]
    project.group_addresses = structure

    return project


def _ga(room: Room, gewerk: str, elem: int, fn: str, sub: int) -> GroupAddress:
    """Erstellt eine GroupAddress mit room_id, element_number und function_name."""
    return GroupAddress(
        main_group=1, middle_group=0, sub_group=sub,
        designation=f"{gewerk}_{room.number}_{elem:02d} {fn}",
        gewerk_code=gewerk,
        room_id=room.id,
        room_number=room.number,
        element_number=elem,
        function_name=fn,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestAktorKanalVergabe:

    def test_einzelelement_erhaelt_kanal_1(self):
        """Ein einzelnes Element pro Raum/Gewerk → Kanal 1."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [_ga(room, "L", 1, "E/A", 0), _ga(room, "L", 1, "DIM", 1)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) > 0
        assert all(r.channel_number == "1" for r in rows)

    def test_zwei_elemente_erhalten_separate_kanaele(self):
        """Zwei Elemente (element_number 1 und 2) in gleichem Raum/Gewerk → Kanal 1 und 2."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _ga(room, "L", 2, "E/A", 1),  # zweiter Stromkreis
        ]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2"], (
            "Zwei Elemente im gleichen Raum/Gewerk müssen separate Kanäle erhalten"
        )

    def test_drei_elemente_erhalten_drei_kanaele(self):
        """Drei Elemente (Küche: 3× Licht) → Kanal 1, 2, 3."""
        room = Room(number="E02", name="Kueche")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _ga(room, "L", 2, "E/A", 1),
            _ga(room, "L", 3, "E/A", 2),
        ]
        project = _make_project([room], "Schaltaktor 8-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2", "3"]

    def test_zwei_raeume_erhalten_separate_kanaele(self):
        """Zwei Räume mit je einem Element → Kanal 1 und 2."""
        room1 = Room(number="E01", name="Wohnzimmer")
        room2 = Room(number="E02", name="Schlafzimmer")
        gas = [
            _ga(room1, "L", 1, "E/A", 0),
            _ga(room2, "L", 1, "E/A", 1),
        ]
        project = _make_project([room1, room2], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2"]

    def test_jalousie_mehrere_elemente_pro_raum(self):
        """Jalousieaktor: 2 Jalousien im Wohnzimmer → 2 separate Kanäle."""
        room = Room(number="E04", name="Wohnzimmer")
        gas = [
            _ga(room, "J", 1, "AUF/AB", 0),
            _ga(room, "J", 1, "STOPP",  1),
            _ga(room, "J", 2, "AUF/AB", 2),  # zweite Jalousie
            _ga(room, "J", 2, "STOPP",  3),
        ]
        project = _make_project([room], "Jalousieaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2"], (
            "Zwei Jalousien im gleichen Raum müssen separate Kanäle erhalten"
        )

    def test_gleiche_funktion_gleicher_kanal(self):
        """Alle GAs desselben Elements teilen denselben Kanal."""
        room = Room(number="E01", name="Zimmer")
        gas = [
            _ga(room, "LD", 1, "E/A",   0),
            _ga(room, "LD", 1, "DIM",   1),
            _ga(room, "LD", 1, "WERT",  2),
            _ga(room, "LD", 1, "RM",    3),
        ]
        project = _make_project([room], "Dimmaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) == 4
        assert all(r.channel_number == "1" for r in rows), (
            "Alle GAs desselben Elements müssen denselben Kanal haben"
        )

    def test_gemischte_gewerke_erhalten_separate_kanaele(self):
        """Schaltaktor: Licht (L) und Steckdose (V) in gleichem Raum → je eigener Kanal."""
        room = Room(number="E02", name="Kueche")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _ga(room, "V", 1, "E/A", 1),
        ]
        project = _make_project([room], "Schaltaktor 8-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_by_gewerk = {r.gewerk_code: r.channel_number for r in rows}
        assert channel_by_gewerk.get("L") != channel_by_gewerk.get("V"), (
            "Verschiedene Gewerke im gleichen Raum müssen separate Kanäle haben"
        )

    def test_kanaele_fortlaufend_ab_1(self):
        """Kanalnummern sind immer fortlaufend ab 1 ohne Lücken."""
        room1 = Room(number="E01", name="Zimmer 1")
        room2 = Room(number="E02", name="Zimmer 2")
        room3 = Room(number="E03", name="Zimmer 3")
        gas = [
            _ga(room1, "L", 1, "E/A", 0),
            _ga(room2, "L", 1, "E/A", 1),
            _ga(room3, "L", 1, "E/A", 2),
        ]
        project = _make_project([room1, room2, room3], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        nums = sorted(int(r.channel_number) for r in rows if r.channel_number.isdigit())
        assert nums == list(range(1, len(nums) + 1)), "Kanalnummern müssen lückenlos ab 1 sein"

    def test_raum_mit_mehreren_elementen_und_mehreren_raeumen(self):
        """
        Kombiniert: Wohnzimmer mit 2 Jalousien + Schlafzimmer mit 1 Jalousie
        → Jalousieaktor sollte 3 Kanäle vergeben.
        """
        wohn = Room(number="E04", name="Wohnzimmer")
        schlaf = Room(number="E05", name="Schlafzimmer")
        gas = [
            _ga(wohn,  "J", 1, "AUF/AB", 0),
            _ga(wohn,  "J", 2, "AUF/AB", 1),  # zweite Jalousie im Wohnzimmer
            _ga(schlaf,"J", 1, "AUF/AB", 2),
        ]
        project = _make_project([wohn, schlaf], "Jalousieaktor 8-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2", "3"]


class TestAktorRowFelder:

    def test_actor_row_hat_element_number(self):
        """ActorRow enthält das element_number-Feld."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 2, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) > 0
        assert rows[0].element_number == 2

    def test_actor_row_felder_vollstaendig(self):
        """ActorRow enthält alle erwarteten Felder."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        row = BelegungsplanService().generate(project).actor_rows[0]
        assert row.physical_address == "1.1.1"
        assert row.room_number == "E01"
        assert row.gewerk_code == "L"
        assert row.channel_number == "1"
        assert row.element_number == 1


class TestVerknuepfungsmatrixFelder:
    """FA-2501 (Stockwerk-Filter) / FA-2502 (Funktionsspalten aus Gewerk-Code)."""

    def test_actor_row_hat_floor_name(self):
        """ActorRow traegt den Stockwerksnamen fuer den FA-2501 Stockwerk-Filter."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        row = BelegungsplanService().generate(project).actor_rows[0]
        assert row.floor_name == "EG"

    def test_sensor_row_hat_gewerk_code_aus_co_gekoppelter_ga(self):
        """SensorRow.gewerk_code kommt von der ueber ein KO verknuepften GA --
        Grundlage der Funktionsspalten in der Verknuepfungsmatrix (FA-2502).

        Nutzt den CO-Fallback-Pfad (_sensor_rows_from_cos), da
        auto_assign_functions() manuell gesetzte function_assignments ohne
        zugehörige Gewerk-Zuweisung im Raum wieder verwirft.
        """
        room = Room(number="E01", name="Wohnzimmer")
        ga = _ga(room, "L", 1, "E/A", 0)
        project = _make_project([room], "Schaltaktor 4-fach", [ga])

        sensor_dev = Device(
            device_type="sensor", product="Taster 2-fach", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(object_number=1, name="Taste 1",
                                 object_function="Schalten", connected_gas=[ga.address]),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2")
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert len(rows) == 1
        assert rows[0].gewerk_code == "L"
        assert rows[0].floor_name == "EG"

    def test_sensor_row_gewerk_code_leer_ohne_aufgeloeste_ga(self):
        """Ohne auflösbare GA (unbekannte Adresse im KO) bleibt gewerk_code
        leer statt zu raten."""
        room = Room(number="E01", name="Wohnzimmer")
        project = _make_project([room], "Schaltaktor 4-fach", [])

        sensor_dev = Device(
            device_type="sensor", product="Taster 2-fach", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(object_number=1, name="Taste 1",
                                 object_function="Schalten", connected_gas=["9/7/255"]),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2")
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert len(rows) == 1
        assert rows[0].gewerk_code == ""
